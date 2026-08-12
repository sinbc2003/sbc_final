# -*- coding: utf-8 -*-
"""확장 채움 벤치 — 사전 매칭(제품 코드)+베이스(±표결) 3구성 (§42 Stage1).

사용: python fill_harness_bench.py [pairs_jsonl] [src_dir] [port]
프로토콜: 고정 서버(어댑터 없음), 스키마 enum=gold ids, 엄정 채점(실패=0점).
"""
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from engine.form_assist import prematch_fields  # noqa: E402
from engine.hwpml.hwpx_grid import parse_hwpx, extract_blank_fields  # noqa: E402

PAIRS = sys.argv[1] if len(sys.argv) > 1 else r"D:/lora_data/fill_eval_s777/fill_pairs.jsonl"
SRC = Path(sys.argv[2] if len(sys.argv) > 2 else r"D:/lora_data/form_bench/hwpx_converted")
PORT = sys.argv[3] if len(sys.argv) > 3 else "8410"
# 4번째 인자: 지시문 교체본 [{"i":N,"instruction":...}] (자유문장 평가 §42h)
INSTR_OVERRIDE = {}
if len(sys.argv) > 4:
    INSTR_OVERRIDE = {d["i"]: d["instruction"]
                      for d in __import__("json").load(
                          open(sys.argv[4], encoding="utf-8"))}
norm = lambda s: re.sub(r"\s+", " ", str(s)).strip()  # noqa: E731


def ask(prompt, ids, temp):
    schema = {"type": "object", "properties": {"채움": {"type": "array",
        "maxItems": len(ids), "items": {"type": "object", "properties": {
            "id": {"type": "string", "enum": ids}, "값": {"type": "string"}},
            "required": ["id", "값"]}}}, "required": ["채움"]}
    body = json.dumps({"model": "m", "temperature": temp, "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema",
            "json_schema": {"name": "fill", "schema": schema}}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            out = json.load(r)
        seen = {}
        for it in json.loads(out["choices"][0]["message"].get("content") or ""
                             ).get("채움", []):
            if isinstance(it, dict) and it.get("id") not in seen:
                seen[it["id"]] = norm(it.get("값", ""))
        return seen
    except Exception:
        return None


def build_prompt(instruction, grid, fields):
    blanks = "\n".join(f"- {f['id']} : {f.get('label', '')}" for f in fields)
    return f"""당신은 교사의 공문 양식을 채우는 비서입니다.

## 참고 문서
(참고 문서 없음)

## 교사 지시사항
{instruction}

{grid}

### 채워야 할 빈칸
{blanks}

위 참고 문서와 교사 지시를 바탕으로, 각 빈칸에 알맞은 값을 넣으세요.
- 빈칸 라벨(행 이름 × 열 이름)의 의미에 맞는 값을 채우세요.
- 값을 알 수 없거나 채울 필요가 없는 빈칸은 생략하세요.
- id는 위 '채워야 할 빈칸' 목록의 id를 정확히 그대로 쓰세요."""


def main():
    docs = []
    for li, line in enumerate(open(PAIRS, encoding="utf-8")):
        r = json.loads(line)
        if li in INSTR_OVERRIDE:
            r["instruction"] = INSTR_OVERRIDE[li]
        g = r["output"] if isinstance(r["output"], dict) else json.loads(r["output"])
        key = list(g.keys())[0]
        gold = {it["id"]: norm(it["값"]) for it in g[key]
                if isinstance(it, dict) and "id" in it}
        if not gold:
            continue
        try:
            doc = parse_hwpx(str(SRC / r["file"]))
            fields = [f for f in extract_blank_fields(doc, include_filled=True)
                      if f["id"] in gold]
        except Exception:
            continue
        if not fields:
            continue
        docs.append({"file": r["file"], "instr": r["instruction"],
                     "grid": r["grid"], "fields": fields, "gold": gold})
    total = sum(len(d["gold"]) for d in docs)
    print(f"평가 대상: {len(docs)}문서 / {total}필드", flush=True)

    stats = {k: 0 for k in ["base", "pre", "pre3"]}
    pre_ok = pre_n = 0
    for i, d in enumerate(docs):
        gm = d["gold"]
        all_ids = [f["id"] for f in d["fields"]]
        # (a) 베이스 단독
        seen = ask(build_prompt(d["instr"], d["grid"], d["fields"]), all_ids, 0.0) or {}
        stats["base"] += sum(1 for k, v in gm.items() if seen.get(k) == v)
        # (b) 사전 매칭 + 베이스
        filled, residual = prematch_fields(d["instr"], d["fields"])
        pre_hit = sum(1 for k, v in filled.items() if gm.get(k) == norm(v))
        pre_ok += pre_hit
        pre_n += len(filled)
        rids = [f["id"] for f in residual]
        seen1 = (ask(build_prompt(d["instr"], d["grid"], residual), rids, 0.0)
                 if rids else {}) or {}
        stats["pre"] += pre_hit + sum(1 for k in rids if seen1.get(k) == gm.get(k))
        # (c) + 3표결
        if rids:
            cnt = {}
            for _ in range(3):
                s = ask(build_prompt(d["instr"], d["grid"], residual), rids, 0.6)
                if s:
                    for k, v in s.items():
                        cnt.setdefault(k, Counter())[v] += 1
            seen3 = {k: c.most_common(1)[0][0] for k, c in cnt.items()}
        else:
            seen3 = {}
        stats["pre3"] += pre_hit + sum(1 for k in rids if seen3.get(k) == gm.get(k))
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(docs)} 진행 — base {stats['base']} / "
                  f"pre {stats['pre']} / pre3 {stats['pre3']}", flush=True)

    print(f"\n선채움 정밀도: {pre_ok}/{pre_n} "
          f"({100*pre_ok//max(pre_n,1)}%)", flush=True)
    for k, label in [("base", "베이스 단독"), ("pre", "선채움+베이스"),
                     ("pre3", "선채움+베이스+3표결")]:
        print(f"[{label}] {stats[k]}/{total} = {100*stats[k]//total}%", flush=True)


if __name__ == "__main__":
    main()
