# -*- coding: utf-8 -*-
"""4단계: 익명화 md → 학습 데이터셋 (train.jsonl / val.jsonl).

v1 = 공문(기안문) 본문 생성 단일턴: {"prompt": 지시문, "completion": md}
- 선택: kind ∈ {본문, 시행}, 같은 (org, num)이면 본문 우선
- 필터: 변환 실패·120자 미만·표 위주(>70%)·8000자 초과(청킹은 2차)
- 지시문: 제목 기반 템플릿(하이엔드 역생성은 2차 레버)
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter

from common import (ANON_DIR, CONVERT_STATUS, DATASET_DIR, MANIFEST,
                    read_jsonl, write_jsonl)

sys.stdout.reconfigure(encoding="utf-8")

MIN_CHARS = 120
MAX_CHARS = 8000  # llm_generate CHUNK_THRESHOLD와 동일
TABLE_RATIO_MAX = 0.7

PROMPT_TEMPLATES = [
    "다음 제목으로 학교 공문(기안문) 본문을 작성하라.\n\n[제목]\n{title}",
    "'{title}' 제목의 공문 본문을 개조식으로 작성하라.",
    "학교 행정 문서 작성: 아래 건의 기안문 본문을 작성하라.\n\n건명: {title}",
]


_ESCAPES = [("\\.", "."), ("\\[", "["), ("\\]", "]"), ("\\(", "("),
            ("\\)", ")"), ("\\-", "-"), ("\\'", "'")]


def clean_md(md: str) -> str:
    """pandoc gfm 이스케이프·blockquote 잔재 제거 (공문 원문에 없는 표기)."""
    for a, b in _ESCAPES:
        md = md.replace(a, b)
    lines = [l[2:] if l.startswith("> ") else l for l in md.splitlines()]
    return "\n".join(lines).strip()


def table_ratio(md: str) -> float:
    """md 파이프 표 + hwp 노드가 내는 HTML 표 라인 비율."""
    lines = [l for l in md.splitlines() if l.strip()]
    if not lines:
        return 0.0
    def is_table(l: str) -> bool:
        s = l.lstrip()
        return s.startswith("|") or s.startswith("<t") or s.startswith("</t")
    return sum(1 for l in lines if is_table(l)) / len(lines)


def main() -> int:
    manifest = {r["idx"]: r for r in read_jsonl(MANIFEST)}
    status = {r["idx"]: r for r in read_jsonl(CONVERT_STATUS)}

    # (org, num) 그룹에서 본문 우선 대표 1건
    groups: dict[tuple, dict] = {}
    for idx, row in manifest.items():
        if row["kind"] not in ("본문", "시행") or not row["num"]:
            continue
        if not status.get(idx, {}).get("ok"):
            continue
        key = (row["org"], row["num"])
        cur = groups.get(key)
        if cur is None or (row["kind"] == "본문" and cur["kind"] != "본문"):
            groups[key] = row

    drops = Counter()
    examples = []
    rng = random.Random(42)
    for row in groups.values():
        p = ANON_DIR / f"{row['idx']:05d}.md"
        if not p.exists():
            drops["md없음"] += 1
            continue
        md = clean_md(p.read_text(encoding="utf-8"))
        if len(md) < MIN_CHARS:
            drops["짧음"] += 1
            continue
        if len(md) > MAX_CHARS:
            drops["초과길이"] += 1
            continue
        if table_ratio(md) > TABLE_RATIO_MAX:
            drops["표위주"] += 1
            continue
        tpl = rng.choice(PROMPT_TEMPLATES)
        examples.append({
            "prompt": tpl.format(title=row["title"]),
            "completion": md,
            "meta": {"idx": row["idx"], "kind": row["kind"],
                     "folder": row["folder"], "title": row["title"]},
        })

    rng.shuffle(examples)
    n_val = max(1, len(examples) // 20)
    val, train = examples[:n_val], examples[n_val:]

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(DATASET_DIR / "train.jsonl", train)
    write_jsonl(DATASET_DIR / "val.jsonl", val)

    stats = {
        "그룹(공문건)": len(groups), "채택": len(examples),
        "train": len(train), "val": len(val), "드롭": dict(drops),
        "평균길이": (sum(len(e["completion"]) for e in examples)
                  // max(1, len(examples))),
    }
    (DATASET_DIR / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"데이터셋: {stats}")
    print(f"→ {DATASET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
