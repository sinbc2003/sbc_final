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
    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map={"": 0},
        torch_dtype=torch.bfloat16, trust_remote_code=True)
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    # gemma-3n은 멀티모달(비전/오디오 타워 포함) — 접미사 매칭이 타워에도
    # 어댑터를 붙이면 텍스트 전용 GGUF 변환이 깨짐 → language_model로 한정.
    if any("language_model" in n for n, _ in model.named_modules()):
        tm = (r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj"
              r"|gate_proj|up_proj|down_proj)$")
    else:
        tm = ["q_proj", "k_proj", "v_proj", "o_proj",
              "gate_proj", "up_proj", "down_proj"]
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
