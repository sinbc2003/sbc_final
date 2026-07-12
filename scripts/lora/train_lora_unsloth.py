# -*- coding: utf-8 -*-
"""5단계(대안): gemma-3n 전용 unsloth QLoRA — 바닐라 HF가 16GB에서 스필나는
gemma-3n(E2B/E4B)을 unsloth 최적화로 학습 (핸드오프 §25 함정7 해법).

실행(unsloth 전용 venv):
  D:\\lora_train\\venv_unsloth\\Scripts\\python.exe scripts/lora/train_lora_unsloth.py ^
      --model D:\\models\\hf\\gemma-3n-E2B-it --out D:\\lora_train\\out\\gongmun_e2b_v1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default=r"D:\lora_data\dataset")
    ap.add_argument("--out", default=r"D:\lora_train\out\gongmun_e2b_v1")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    args = ap.parse_args()

    from unsloth import FastModel  # noqa: E402 (반드시 최상단 import)
    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth.chat_templates import train_on_responses_only

    model, tokenizer = FastModel.from_pretrained(
        args.model, max_seq_length=args.max_len,
        load_in_4bit=True, full_finetuning=False,
    )
    model = FastModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        finetune_vision_layers=False, finetune_language_layers=True,
        finetune_attention_modules=True, finetune_mlp_modules=True,
    )

    def load_split(name: str) -> Dataset:
        rows = []
        for line in (Path(args.data) / f"{name}.jsonl").read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            msgs = [{"role": "user", "content": r["prompt"]},
                    {"role": "assistant", "content": r["completion"]}]
            rows.append({"text": tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False)})
        return Dataset.from_list(rows)

    train_ds, val_ds = load_split("train"), load_split("val")
    print(f"train {len(train_ds)} / val {len(val_ds)}")

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer,
        train_dataset=train_ds, eval_dataset=val_ds,
        args=SFTConfig(
            output_dir=args.out, dataset_text_field="text",
            max_seq_length=args.max_len,
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs, learning_rate=args.lr,
            lr_scheduler_type="cosine", warmup_ratio=0.05,
            logging_steps=5, eval_strategy="epoch",
            save_strategy="epoch", save_total_limit=1,
            bf16=True, report_to=[], dataloader_pin_memory=False,
        ),
    )
    # 프롬프트 구간 마스킹 — gemma 채팅 템플릿 마커 기준
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<start_of_turn>user\n",
        response_part="<start_of_turn>model\n",
    )
    trainer.train()

    final = Path(args.out) / "final"
    model.save_pretrained(str(final))
    tokenizer.save_pretrained(str(final))
    print(f"어댑터 저장: {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
