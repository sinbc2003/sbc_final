# -*- coding: utf-8 -*-
"""v12: 청크 단위 채움 학습쌍 — 런타임 _plan_grid_fill과 분포 일치 (§42e).

긴 양식 1문서 → (표 렌더 + 그 표의 빈칸 ≤15개) 샘플 N개로 분해.
max-len 필터 손실(v11에서 511/876)을 제거하고 학습-추론 분포를 정렬한다.
사용: python make_chunked_fill_dataset.py <out_dir>
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from engine.hwpml.hwpx_grid import parse_hwpx, ID_RE  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else r"D:/lora_data/dataset_fill_v12"
CHUNK_FIELDS = 15
n = lambda s: re.sub(r"\s+", "", str(s))  # noqa: E731

SRCS = ([(f"distill_s{s}", f"D:/lora_data/distill_s{s}",
          "D:/lora_data/form_bench/hwpx_converted") for s in range(1001, 1010)]
        + [(f"distill_m{s}", f"D:/lora_data/distill_m{s}",
            "D:/lora_data/form_bench/mac1_train") for s in (2001, 2002)])


def load_div(d):
    div = {}
    for p in glob.glob(f"{d}/instr_div*.json"):
        try:
            for it in json.load(open(p, encoding="utf-8")):
                div[it["i"]] = it["instruction"]
        except Exception:
            pass
    comp = {}
    for p in glob.glob(f"{d}/instr_compact*.json"):
        try:
            for c in json.load(open(p, encoding="utf-8")):
                comp[c["i"]] = c["values"]
        except Exception:
            pass
    return div, comp


def main():
    os.makedirs(OUT, exist_ok=True)
    tr = open(f"{OUT}/train.jsonl", "w", encoding="utf-8")
    va = open(f"{OUT}/val.jsonl", "w", encoding="utf-8")
    render_cache = {}
    tot = used_div = 0
    for name, d, src in SRCS:
        div, comp = load_div(d)
        for i, line in enumerate(open(f"{d}/fill_pairs.jsonl", encoding="utf-8")):
            r = json.loads(line)
            g = r["output"] if isinstance(r["output"], dict) else json.loads(r["output"])
            key = list(g.keys())[0]
            gold = [(it["id"], it["값"]) for it in g[key]
                    if isinstance(it, dict) and "id" in it]
            if not gold:
                continue
            instr = r["instruction"]
            if i in div and i in comp and all(n(v) in n(div[i]) for v in comp[i]):
                instr = div[i]
                used_div += 1
            fpath = f"{src}/{r['file']}"
            if fpath not in render_cache:
                try:
                    doc = parse_hwpx(fpath)
                    render_cache[fpath] = {
                        grid.key: grid.render(mark_blanks=True)
                        for grid in doc.tables}
                except Exception:
                    render_cache[fpath] = None
            renders = render_cache[fpath]
            if not renders:
                continue
            by_table = {}
            for cid, val in gold:
                m = ID_RE.match(str(cid))
                tkey = f"s{m.group(1)}_t{m.group(2)}" if m else "_misc"
                by_table.setdefault(tkey, []).append((cid, val))
            for tkey, cells in by_table.items():
                render = renders.get(tkey, "")
                for c0 in range(0, len(cells), CHUNK_FIELDS):
                    chunk = cells[c0:c0 + CHUNK_FIELDS]
                    blanks = "\n".join(f"- {cid}" for cid, _ in chunk)
                    prompt = (
                        "당신은 교사의 공문 양식을 채우는 비서입니다.\n\n"
                        "## 참고 문서\n(참고 문서 없음)\n\n"
                        f"## 교사 지시사항\n{instr}\n\n"
                        f"### 문서 표 구조 (빈칸은 {{셀ID}} 로 표시됨)\n{render}\n\n"
                        f"### 채워야 할 빈칸 ({len(chunk)}개)\n{blanks}\n\n"
                        "위 참고 문서와 교사 지시를 바탕으로, 각 빈칸에 알맞은 값을 넣으세요.\n"
                        "- id는 위 '채워야 할 빈칸' 목록의 id를 정확히 그대로 쓰세요.")
                    comp_json = json.dumps(
                        {"채움": [{"id": cid, "값": val} for cid, val in chunk]},
                        ensure_ascii=False)
                    row = json.dumps({"prompt": prompt, "completion": comp_json,
                                      "meta": {"src": name, "i": i, "t": tkey}},
                                     ensure_ascii=False) + "\n"
                    (va if tot % 25 == 24 else tr).write(row)
                    tot += 1
    tr.close()
    va.close()
    print(f"청크 샘플 {tot}개 (다양화 문서 {used_div}) → {OUT}")


if __name__ == "__main__":
    main()
