# -*- coding: utf-8 -*-
"""v9 멀티태스크 세트 병합 — 공문 생성(dataset/) + 양식 채움(fill_pairs).

채움 쌍은 런타임(form_assist._plan_grid_fill) 프롬프트 분포를 그대로 미러링
— 학습·추론 분포 일치가 소형모델에서 특히 중요(§25 교훈).
출력: D:\lora_data\dataset_v9\{train,val}.jsonl ({"prompt","completion"})
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

GONGMUN = Path(r"D:\lora_data\dataset")
# 기본은 v10(정화본, §41d). --v9로 이전 세트 재현 가능.
FILL_SRCS_V10 = [Path(r"D:\lora_data\fill_v10\fill_pairs.jsonl")]
FILL_SRCS = [Path(r"D:\lora_data\fill_v9\fill_pairs.jsonl"),
             Path(r"D:\lora_data\fill_v9_full\fill_pairs.jsonl")]
OUT = Path(r"D:\lora_data\dataset_v9")

# 런타임 프롬프트 미러 (form_assist._plan_grid_fill과 동일 골격)
FILL_PROMPT = """당신은 교사의 공문 양식을 채우는 비서입니다.

## 참고 문서
(참고 문서 없음)

## 교사 지시사항
{instruction}

{grid}

위 참고 문서와 교사 지시를 바탕으로, 각 빈칸에 알맞은 값을 넣으세요.
- 빈칸 라벨(행 이름 × 열 이름)의 의미에 맞는 값을 채우세요.
- 값을 알 수 없거나 채울 필요가 없는 빈칸은 생략하세요.
- 이미 의미 있는 값이 들어 있는 칸은 그대로 두세요(비어 있을 때만 채움).
- 값에는 빈칸에 들어갈 내용만 쓰세요 — 라벨이나 기호("(인)", "성명:" 등)를 반복하지 마세요.
- id는 위 '채워야 할 빈칸' 목록의 id를 정확히 그대로 쓰세요."""


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v9", action="store_true", help="구 오염 세트 재현(비교용)")
    args = ap.parse_args()
    srcs = FILL_SRCS if args.v9 else FILL_SRCS_V10
    out_dir = OUT if args.v9 else Path(r"D:\lora_data\dataset_v10")

    rng = random.Random(42)

    fill = []
    seen_files = set()
    for src in srcs:
        if not src.exists():
            continue
        for line in src.open(encoding="utf-8"):
            d = json.loads(line)
            key = (d["file"], d["instruction"][:50])
            if key in seen_files:
                continue  # 파일럿·확장 코퍼스 중복 양식 제거
            seen_files.add(key)
            prompt = FILL_PROMPT.format(instruction=d["instruction"], grid=d["grid"])
            if len(prompt) > 9000:
                continue  # 초대형 양식은 런타임도 청킹 — 학습 제외
            fill.append({"prompt": prompt,
                         "completion": json.dumps(d["output"], ensure_ascii=False)})

    g_train = [json.loads(l) for l in (GONGMUN / "train.jsonl").open(encoding="utf-8")]
    g_val = [json.loads(l) for l in (GONGMUN / "val.jsonl").open(encoding="utf-8")]

    rng.shuffle(fill)
    n_val = max(8, len(fill) // 20)
    f_val, f_train = fill[:n_val], fill[n_val:]

    train = g_train + f_train
    val = g_val + f_val
    rng.shuffle(train)

    out_dir.mkdir(exist_ok=True)
    with (out_dir / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / "val.jsonl").open("w", encoding="utf-8") as f:
        for r in val:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"공문 {len(g_train)}+{len(g_val)} / 채움 {len(f_train)}+{len(f_val)} "
          f"→ train {len(train)} / val {len(val)} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
