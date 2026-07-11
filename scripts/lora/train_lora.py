# -*- coding: utf-8 -*-
"""5단계: 공문 생성 LoRA 학습 (QLoRA, RTX5080 16GB).

실행(학습 전용 venv, 엔진 파이썬과 분리):
  D:\\lora_train\\venv\\Scripts\\python.exe scripts/lora/train_lora.py ^
      --model D:\\models\\hf\\gemma-3n-E4B-it --out D:\\lora_train\\out\\gongmun_v1

- 데이터: D:\\lora_data\\dataset\\{train,val}.jsonl ({"prompt","completion"})
- 프롬프트 토큰은 -100 마스킹 → completion만 학습
- rank 낮게 시작(기본 16) — 정형 포맷이라 과적합(제목 암기)이 더 큰 리스크
- 산출: HF 어댑터(out/) → convert_lora_to_gguf.py로 GGUF 변환(별도 단계)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_pairs(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append({"prompt": r["prompt"], "completion": r["completion"]})
    return rows


def build_dataset(tokenizer, pairs: list[dict], max_len: int):
    """chat template 적용 + 프롬프트 구간 -100 마스킹."""
    import torch
    from torch.utils.data import Dataset

    def _ids(msgs, gen_prompt):
        # transformers 5.x는 tokenize=True 시 BatchEncoding(dict) 반환
        enc = tokenizer.apply_chat_template(
            msgs, add_generation_prompt=gen_prompt, tokenize=True)
        return enc if isinstance(enc, list) else enc["input_ids"]

    class PairDataset(Dataset):
        def __init__(self):
            self.items = []
            skipped = 0
            for p in pairs:
                msgs_prompt = [{"role": "user", "content": p["prompt"]}]
                prompt_ids = _ids(msgs_prompt, True)
                msgs_full = msgs_prompt + [
                    {"role": "assistant", "content": p["completion"]}]
                full_ids = _ids(msgs_full, False)
                if len(full_ids) > max_len:
                    skipped += 1
                    continue
                labels = list(full_ids)
                labels[:len(prompt_ids)] = [-100] * len(prompt_ids)
                self.items.append({
                    "input_ids": torch.tensor(full_ids),
                    "labels": torch.tensor(labels),
                })
            if skipped:
                print(f"  길이 초과 스킵: {skipped}")

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            return self.items[i]

    return PairDataset()


def collate(tokenizer):
    import torch

    def _fn(batch):
        pad = tokenizer.pad_token_id or 0
        n = max(len(b["input_ids"]) for b in batch)
        ids, labels, attn = [], [], []
        for b in batch:
            k = n - len(b["input_ids"])
            ids.append(torch.cat([b["input_ids"],
                                  torch.full((k,), pad, dtype=torch.long)]))
            labels.append(torch.cat([b["labels"],
                                     torch.full((k,), -100, dtype=torch.long)]))
            attn.append(torch.cat([torch.ones(len(b["input_ids"]),
                                              dtype=torch.long),
                                   torch.zeros(k, dtype=torch.long)]))
        return {"input_ids": torch.stack(ids), "labels": torch.stack(labels),
                "attention_mask": torch.stack(attn)}
    return _fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF 베이스 모델 경로/이름")
    ap.add_argument("--data", default=r"D:\lora_data\dataset")
    ap.add_argument("--out", default=r"D:\lora_train\out\gongmun_v1")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    args = ap.parse_args()

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig, Trainer, TrainingArguments)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    print(f"torch {torch.__version__}, GPU: {torch.cuda.get_device_name(0)}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    # gemma-3n AltUp은 학습 중 coef weight를 clamp_(float in-place)함 —
    # 4bit(uint8) 양자화되면 "Float can't be cast to unsigned char" 크래시.
    # altup/laurel은 초소형 Linear라 제외 비용도 없음.
    # ⚠ tf 5.x는 skip 매칭이 접두사/정규식(re.match)/접미사만 — 경로 중간
    # 토큰은 ".*이름.*" 정규식으로 써야 매칭됨(quantizers_utils.should_convert_module).
    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_skip_modules=[".*altup.*", ".*laurel.*", "lm_head"])
    # tf 5.x: torch_dtype는 deprecated·무시됨 → dtype 사용.
    # (무시되면 비양자화 파트가 FP32로 올라가 VRAM 스필 — RTX5080 실측 원인)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map={"": 0},
        dtype=torch.bfloat16, trust_remote_code=True)
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    # 타깃 모듈 자동 감지 — 모델 패밀리별 레이어명 차이 흡수
    # (gemma: q/k/v/o/gate/up/down, EXAONE3.5: q/k/v/out_proj·c_fc_0/1·c_proj)
    candidates = {"q_proj", "k_proj", "v_proj", "o_proj", "out_proj",
                  "gate_proj", "up_proj", "down_proj",
                  "c_fc_0", "c_fc_1", "c_proj"}
    import torch.nn as nn
    found = set()
    has_lm_prefix = False
    for name, mod in model.named_modules():
        leaf = name.rsplit(".", 1)[-1]
        if leaf in candidates and (isinstance(mod, nn.Linear)
                                   or "Linear" in type(mod).__name__):
            found.add(leaf)
            if "language_model" in name:
                has_lm_prefix = True
    if not found:
        raise RuntimeError("타깃 후보 Linear 레이어를 찾지 못함 — 모델 구조 확인 필요")
    if has_lm_prefix:
        # gemma-3n 멀티모달: 비전/오디오 타워에 어댑터가 붙으면
        # 텍스트 전용 GGUF 변환이 깨짐 → language_model로 한정
        tm = r".*language_model.*\.(" + "|".join(sorted(found)) + r")$"
    else:
        tm = sorted(found)
    print(f"target_modules: {tm}")
    lora = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM", target_modules=tm)
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    data_dir = Path(args.data)
    train_ds = build_dataset(tokenizer, load_pairs(data_dir / "train.jsonl"),
                             args.max_len)
    val_ds = build_dataset(tokenizer, load_pairs(data_dir / "val.jsonl"),
                           args.max_len)
    print(f"train {len(train_ds)} / val {len(val_ds)}")

    targs = TrainingArguments(
        output_dir=args.out, num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, lr_scheduler_type="cosine",
        warmup_ratio=0.05, logging_steps=5,
        eval_strategy="epoch", save_strategy="epoch",
        save_total_limit=2, bf16=True,
        gradient_checkpointing=True, report_to=[],
        dataloader_pin_memory=False)
    trainer = Trainer(model=model, args=targs,
                      train_dataset=train_ds, eval_dataset=val_ds,
                      data_collator=collate(tokenizer))
    trainer.train()

    final = Path(args.out) / "final"
    model.save_pretrained(str(final))
    tokenizer.save_pretrained(str(final))
    print(f"어댑터 저장: {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
