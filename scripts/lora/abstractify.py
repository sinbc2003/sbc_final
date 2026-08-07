# -*- coding: utf-8 -*-
"""v5 역생성 — 완성 공문에서 개요를 역추출해 '개요→완성문' 학습쌍을 만든다.

배경(§30): v4까지의 프롬프트는 '제목→완성문 창작'이라 어댑터가 그럴듯한
지어내기를 배웠고 개요 준수를 배운 적이 없다(사실 순응 실측 저하).
개요를 베이스 모델(JSON 스키마 강제 — 추출은 벤치 100% 강점)로 역추출해
instruction으로 삼으면 서식과 사실 순응을 동시에 학습한다.

실행: python scripts/lora/abstractify.py [--server http://127.0.0.1:8400] [--limit N]
입력: D:\lora_data\dataset\{train,val}.jsonl (비증강 공문 쌍)
산출: D:\lora_data\dataset\abstracts.jsonl — {"key": ..., "개요": [...]} (멱등 재개)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DATASET = Path(r"D:\lora_data\dataset")
OUT = DATASET / "abstracts.jsonl"

SCHEMA = {
    "type": "object",
    "properties": {
        "개요": {
            "type": "array",
            "items": {"type": "string", "minLength": 4, "maxLength": 80},
            "minItems": 3, "maxItems": 8,
        }
    },
    "required": ["개요"],
}

PROMPT = """다음 학교 공문의 핵심 사실만 개요 항목으로 추출하라.
- 항목당 한 줄: 무엇을/대상/일시·기간/장소/방법·절차/기한 중 문서에 실제로 있는 것만.
- 기관명·문서번호·붙임 목록은 제외.
- 문서에 없는 내용을 만들지 마라.

[공문]
{doc}"""


def ex_key(e: dict) -> str:
    m = e.get("meta", {})
    return str(m.get("reg") or f"idx{m.get('idx')}_{m.get('kind','')}")


def extract(server: str, doc: str) -> list[str]:
    body = {
        "messages": [{"role": "user", "content": PROMPT.format(doc=doc[:3500])}],
        "max_tokens": 400, "temperature": 0.1,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "outline", "schema": SCHEMA}},
    }
    req = urllib.request.Request(server + "/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=180))
    return json.loads(r["choices"][0]["message"]["content"])["개요"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8400")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    done: set[str] = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["key"])

    # 비증강 공문 쌍 수집 (train+val, report 제외)
    targets = []
    seen = set()
    for name in ("train.jsonl", "val.jsonl"):
        for line in (DATASET / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            m = e.get("meta", {})
            if m.get("aug") or m.get("type") == "report":
                continue
            k = ex_key(e)
            if k in seen or k in done:
                continue
            seen.add(k)
            targets.append((k, e["completion"]))
    print(f"대상 {len(targets)}건 (기완료 {len(done)} 제외)")

    n = ok = fail = 0
    t0 = time.time()
    with OUT.open("a", encoding="utf-8") as f:
        for k, doc in targets:
            if args.limit and n >= args.limit:
                break
            n += 1
            try:
                items = extract(args.server, doc)
                # placeholder·빈 항목 정리
                items = [s.strip() for s in items
                         if s.strip() and "{기관명}" not in s and "{문서번호}" not in s]
                if len(items) < 2:
                    fail += 1
                    continue
                f.write(json.dumps({"key": k, "개요": items}, ensure_ascii=False) + "\n")
                f.flush()
                ok += 1
            except Exception as e:
                fail += 1
                print(f"[FAIL] {k}: {str(e)[:80]}")
            if n % 100 == 0:
                el = time.time() - t0
                print(f"진행 {n}/{len(targets)} (성공 {ok}/실패 {fail}, "
                      f"{el/n:.1f}s/건, 잔여 ~{(len(targets)-n)*el/n/60:.0f}분)")
    print(f"완료: 성공 {ok} / 실패 {fail} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
