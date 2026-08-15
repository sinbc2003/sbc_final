# -*- coding: utf-8 -*-
"""v15: v13 청크셋 + 견본행 교체 + 잉여값 부정 예제 (§42m 잔여 처방, §43 준비).

v14 실측 잔여 결함 2개를 데이터로 직접 가르친다:
  B. 견본행 — 표 상단 행에 "김○○"류 견본값이 있으면 소형모델이 행 정렬을
     잃음(순번→날짜 복사). 합성: 첫 gold 행 셀에 ○류 견본을 주입해 렌더
     (셀은 텍스트로 보임 = 런타임 _is_placeholder 후보와 동일 분포),
     빈칸 목록에 라벨 동봉(런타임 형식) → gold = 실값 교체.
  C. 잉여값 — 양식에 없는 라벨의 값을 지시문이 담고 있으면 남는 빈칸에
     밀어넣음(§42n 준비물 오배치 실측). 합성: ①지시문에 가짜 라벨:값 추가
     ②빈칸 목록에 지시문이 못 채우는 실제 빈칸 추가 → gold는 그대로
     (가짜값 미사용 + 모르는 빈칸 미채움이 정답).

사용: python make_fill_dataset_v15.py [out_dir]
"""
import copy
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from engine.hwpml.hwpx_grid import parse_hwpx, extract_blank_fields, ID_RE  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else r"D:/lora_data/dataset_fill_v15"
CHUNK_FIELDS = 15
n = lambda s: re.sub(r"\s+", "", str(s))  # noqa: E731

SRCS = ([(f"distill_s{s}", f"D:/lora_data/distill_s{s}",
          "D:/lora_data/form_bench/hwpx_converted") for s in range(1001, 1010)]
        + [(f"distill_m{s}", f"D:/lora_data/distill_m{s}",
            "D:/lora_data/form_bench/mac1_train") for s in (2001, 2002)])

# 잉여값 가짜 라벨 풀 — 렌더에 없는 것만 사용
FAKE_LABELS = ["참석자 대표", "예산 담당자", "차량 번호", "후원 기관",
               "면담 장소", "결재 번호", "안전 요원"]
FAKE_VALUES = ["박민수", "정하윤", "12가3456", "한국교육재단",
               "본관 2층 회의실", "2026-084", "이상혁"]

_DATE_RE = re.compile(r"\d{1,4}[.\-/년]\s*\d{1,2}")


def sample_of(val: str) -> str:
    """실값 → 런타임 _is_placeholder가 견본으로 감지하는 ○류 스캐폴드."""
    v = str(val).strip()
    if _DATE_RE.search(v):
        return "○월 ○일(○)"
    if v.replace(",", "").replace(" ", "").isdigit():
        return "○○"
    if re.fullmatch(r"[가-힣]{2,4}", v):        # 이름꼴 → "김○○" (○ 2개 이상 보장)
        return v[0] + "○" * max(2, len(v) - 1)
    if re.search(r"[가-힣]+(초|중|고|교|원|청|부|과)$", v):  # 기관꼴 → "○○초"
        return "○○" + v[-1]
    return "○○○"


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


def build_prompt(instr, render, blank_lines):
    return (
        "당신은 교사의 공문 양식을 채우는 비서입니다.\n\n"
        "## 참고 문서\n(참고 문서 없음)\n\n"
        f"## 교사 지시사항\n{instr}\n\n"
        f"### 문서 표 구조 (빈칸은 {{셀ID}} 로 표시됨)\n{render}\n\n"
        f"### 채워야 할 빈칸 ({len(blank_lines)}개)\n" + "\n".join(blank_lines) + "\n\n"
        "위 참고 문서와 교사 지시를 바탕으로, 각 빈칸에 알맞은 값을 넣으세요.\n"
        "- id는 위 '채워야 할 빈칸' 목록의 id를 정확히 그대로 쓰세요.")


def main():
    os.makedirs(OUT, exist_ok=True)
    tr = open(f"{OUT}/train.jsonl", "w", encoding="utf-8")
    va = open(f"{OUT}/val.jsonl", "w", encoding="utf-8")
    doc_cache = {}
    tot = counts = None
    tot, counts, used_div = 0, {"A": 0, "B": 0, "C": 0}, 0
    seen_b_tables = set()          # 견본행은 (파일,표)당 1개
    fake_i = 0

    def emit(prompt, comp_json, src, i, tkey, kind):
        nonlocal tot
        row = json.dumps({"prompt": prompt, "completion": comp_json,
                          "meta": {"src": src, "i": i, "t": tkey, "k": kind}},
                         ensure_ascii=False) + "\n"
        (va if tot % 25 == 24 else tr).write(row)
        tot += 1
        counts[kind] += 1

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
            if fpath not in doc_cache:
                try:
                    doc = parse_hwpx(fpath)
                    labels = {f["id"]: f.get("label", "")
                              for f in extract_blank_fields(doc, include_filled=True)}
                    doc_cache[fpath] = ({t.key: t for t in doc.tables}, labels)
                except Exception:
                    doc_cache[fpath] = None
            if not doc_cache[fpath]:
                continue
            renders, labels = doc_cache[fpath]
            by_table = {}
            for cid, val in gold:
                m = ID_RE.match(str(cid))
                tkey = f"s{m.group(1)}_t{m.group(2)}" if m else "_misc"
                by_table.setdefault(tkey, []).append((cid, val))

            for tkey, cells in by_table.items():
                grid = renders.get(tkey)
                render = grid.render(mark_blanks=True) if grid else ""
                for c0 in range(0, len(cells), CHUNK_FIELDS):
                    chunk = cells[c0:c0 + CHUNK_FIELDS]
                    rows = set()
                    for cid, _ in chunk:
                        m = ID_RE.match(str(cid))
                        if m:
                            rows.add(int(m.group(3)))
                    if grid is not None and len(render) > 3000:
                        chunk_render = grid.render_row_window(rows, ctx=1)
                    else:
                        chunk_render = render
                    blanks = [f"- {cid}" for cid, _ in chunk]
                    comp_json = json.dumps(
                        {"채움": [{"id": cid, "값": val} for cid, val in chunk]},
                        ensure_ascii=False)

                    # ── A. 기본(v13 동일) ──
                    emit(build_prompt(instr, chunk_render, blanks),
                         comp_json, name, i, tkey, "A")

                    # ── C. 잉여값 부정 (6번에 1번) ──
                    if tot % 6 == 0 and grid is not None:
                        fl = FAKE_LABELS[fake_i % len(FAKE_LABELS)]
                        fv = FAKE_VALUES[fake_i % len(FAKE_VALUES)]
                        fake_i += 1
                        if fl not in chunk_render and fl not in instr:
                            c_instr = instr.rstrip() + f" 그리고 {fl}은(는) {fv}입니다."
                            gold_ids = {cid for cid, _ in chunk}
                            extras = [x for x in re.findall(
                                r"\{(" + re.escape(tkey) + r"_r\d+_c\d+)\}",
                                chunk_render) if x not in gold_ids][:2]
                            if extras:
                                c_blanks = blanks + [f"- {x}" for x in extras]
                                emit(build_prompt(c_instr, chunk_render, c_blanks),
                                     comp_json, name, i, tkey, "C")

                    # ── B. 견본행 주입 (표당 1회, 행 2개 이상 청크만) ──
                    if (fpath, tkey) in seen_b_tables or grid is None or len(rows) < 2:
                        continue
                    seen_b_tables.add((fpath, tkey))
                    first_row = min(rows)
                    inj = [(cid, val) for cid, val in chunk
                           if ID_RE.match(str(cid))
                           and int(ID_RE.match(str(cid)).group(3)) == first_row]
                    if not inj:
                        continue
                    g2 = copy.deepcopy(grid)
                    ok = 0
                    for cid, val in inj:
                        m = ID_RE.match(str(cid))
                        cell = g2.cells.get((int(m.group(3)), int(m.group(4))))
                        if cell is not None and not cell.text:
                            cell.text = sample_of(val)
                            ok += 1
                    if not ok:
                        continue
                    g2._occupancy = {}
                    if len(render) > 3000:
                        b_render = g2.render_row_window(rows, ctx=1)
                    else:
                        b_render = g2.render(mark_blanks=True)
                    # 런타임 형식: 견본 셀은 렌더에 {id}가 없으므로 라벨로 지목
                    b_blanks = [f"- {cid} : {labels.get(cid, '')}" for cid, _ in chunk]
                    emit(build_prompt(instr, b_render, b_blanks),
                         comp_json, name, i, tkey, "B")
    tr.close()
    va.close()
    print(f"v15 샘플 {tot}개 (A기본 {counts['A']} / B견본행 {counts['B']} / "
          f"C잉여값 {counts['C']} / 다양화 {used_div}) → {OUT}")


if __name__ == "__main__":
    main()
