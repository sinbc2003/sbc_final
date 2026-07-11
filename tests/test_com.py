# -*- coding: utf-8 -*-
"""COM 테스트 — 한/글 필요, LLM 불필요. 그리드↔스캔 정렬·라이브 기록.

전제: 한/글 설치. bench 픽스처 있으면 병합 16표 정렬까지 검증.
실행: python tests/test_com.py   (COM 없으면 자동 skip)
"""
import sys
import zipfile
from pathlib import Path

from helpers import ROOT, BENCH, have_bench, md_to_hwpx, inject_section_body, workdir, hwp_op

sys.path.insert(0, str(ROOT))

from engine.hwpml.hwpx_grid import parse_hwpx, fill_hwpx_cells, find_below_marker
from engine.form_assist import scan_hwp_structure
from engine.hwp.grid_live import fill_grid_live, align_grid_to_scan, grid_cells_in_doc_order

PASS, FAIL, SKIP = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}")


def com_available() -> bool:
    try:
        hwp_op("read", str(BENCH) if have_bench() else "")
        return True
    except Exception as e:
        print(f"  COM 미가용: {str(e)[:80]}")
        return False


def t_align_bench():
    """병합 16표: 그리드↔InitScan 정렬 1:1 + 텍스트 검산."""
    print("[align bench (병합 16표)]")
    if not have_bench():
        SKIP.append("align_bench"); print("  SKIP  bench 없음"); return
    doc = parse_hwpx(str(BENCH))
    gcells = grid_cells_in_doc_order(doc)
    elements = scan_hwp_structure(str(BENCH), lambda m: None, timeout=120)
    mapping, stats = align_grid_to_scan(doc, elements, log=lambda m: None)
    check(f"셀수 일치 {stats['grid_cells']}={stats['scan_cells']}",
          stats["grid_cells"] == stats["scan_cells"] == len(gcells))
    check(f"검산 전부 일치 ({stats['matched']})", stats["mismatched"] == 0)


def t_live_marker():
    """새 양식(마커 첫행)에 데이터 라이브 기록 → 마커 원위치 + 전체 무손상."""
    print("[live marker (라이브 기록+마커 이동)]")
    if not have_bench():
        SKIP.append("live_marker"); print("  SKIP  bench 없음"); return
    orig = parse_hwpx(str(BENCH))
    t1 = next(g for g in orig.tables if g.key == "s0_t1")
    hdr = t1.header_row_count()
    marker = find_below_marker(t1)
    gt = {f"{t1.key}_r{r}_c{c}": cell.text for (r, c), cell in t1.cells.items()
          if hdr <= r < t1.row_cnt - 2 and r != marker["row"] and cell.text.strip()}
    wd = workdir("com_mark_")
    tmpl = {k: "" for k in gt}
    for c, _t in marker["cells"]:
        tmpl[f"{t1.key}_r{marker['row']}_c{c}"] = ""
    for c, t in marker["cells"]:
        tmpl[f"{t1.key}_r{hdr}_c{c}"] = t
    blank = str(wd / "new.hwpx")
    fill_hwpx_cells(str(BENCH), blank, tmpl)
    elements = scan_hwp_structure(blank, lambda m: None, timeout=120)
    res = fill_grid_live(blank, gt, elements, log=lambda m: None, output_dir=str(wd))
    out = res["output"]
    check("저장본 생성", bool(out) and Path(out).exists())
    if out:
        rdoc = parse_hwpx(out)
        rc = {f"{g.key}_r{c.row}_c{c.col}": c.text.strip() for g in rdoc.tables for c in g.cells.values()}
        oc = {f"{g.key}_r{c.row}_c{c.col}": c.text.strip() for g in orig.tables for c in g.cells.values()}
        diffs = [k for k in oc if oc[k] != rc.get(k, "")]
        check(f"전체 셀 무손상 ({len(oc)-len(diffs)}/{len(oc)})", not diffs and not res["skipped"])


def t_body_live():
    """본문 밑줄 라이브 기록 — 표 안 밑줄/장식 무손상."""
    print("[body-blank live]")
    wd = workdir("com_body_")
    base = md_to_hwpx("# 초빙\n\n| 항목 | 내용 | 비고 |\n| --- | --- | --- |\n| 강사 |  | ______ |\n", "base", wd)
    P = lambda t: f'<hp:p><hp:run charPrIDRef="0"><hp:t>{t}</hp:t></hp:run></hp:p>'
    # 본문 3문단: u0=신청자, u1=소속, u2=연락처(채움 대상), u3=장식 구분선(비대상)
    form = inject_section_body(base, str(wd / "f.hwpx"),
                              P("신청자: ______ 소속: ______") + P("연락처: ______")
                              + P("________________________"))
    doc = parse_hwpx(form)
    cell_id = next(f"{g.key}_r{c.row}_c{c.col}" for g in doc.tables for c in g.cells.values()
                   if c.row == 1 and c.col == 1)
    fill = {cell_id: "김강사", "s0_u0": "박신청", "s0_u2": "010-1"}
    elements = scan_hwp_structure(form, lambda m: None, timeout=60)
    res = fill_grid_live(form, fill, elements, log=lambda m: None, output_dir=str(wd))
    out = res["output"]
    check("기록 3개·건너뜀0", res["filled"] == 3 and not res["skipped"])
    if out and Path(out).exists():
        with zipfile.ZipFile(out) as z:
            xml = z.read("Contents/section0.xml").decode("utf-8")
        check("본문 채움+비대상 보존", "신청자: 박신청 소속: ______" in xml)
        check("장식 구분선 보존", "________________________" in xml)


def main():
    if not com_available():
        print("\n=== COM: 전체 SKIP (한/글 미가용) ===")
        return 0
    for fn in (t_align_bench, t_live_marker, t_body_live):
        try:
            fn()
        except Exception as e:
            FAIL.append(f"{fn.__name__}: {e}")
            print(f"  FAIL {fn.__name__}: {str(e)[:120]}")
    print(f"\n=== COM: {len(PASS)} PASS, {len(FAIL)} FAIL, {len(SKIP)} SKIP ===")
    if FAIL:
        print("실패:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
