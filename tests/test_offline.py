# -*- coding: utf-8 -*-
"""오프라인 테스트 — COM·LLM 불필요. 순수 파싱/채움/스키마 로직.

실행: python tests/test_offline.py   (또는 python tests/run_tests.py offline)
"""
import sys
import zipfile
from pathlib import Path

from helpers import ROOT, BENCH, have_bench, md_to_hwpx, inject_section_body, workdir

sys.path.insert(0, str(ROOT))

from engine.hwpml.hwpx_grid import (
    parse_hwpx, extract_blank_fields, extract_body_blanks, body_blank_runs,
    fill_hwpx_cells, find_below_marker, relocate_below_markers,
)
import engine.form_assist as fa
from engine.chat.live_chat import (
    build_live_envelope_schema, parse_envelope_response, LIVE_HWP_ACTIONS,
    LIVE_EXCEL_ACTIONS, LIVE_PPT_ACTIONS,
)
from engine.hwp.blocks import BlockManager
from engine.hwp.models import Block

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}")


# ── 1. placeholder 데이터손실 방어 ──
def t_placeholder():
    print("[placeholder]")
    cases = [("홍길동", False), ("3학년 2반", False),
             ("학생이 과제를 꼼꼼히 기입하였음", False), ("학생이 기입하였음", False),
             ("성적을 기입", False), ("예시", True), ("미기재", True), ("기입란", True),
             ("○○○", True), ("___", True), ("■□", False), ("O", False), ("해당없음", False)]
    for t, want in cases:
        check(f"_is_placeholder({t!r})={want}", fa._is_placeholder(t) == want)
    check("_is_fillable 실데이터 보호",
          fa._is_fillable({"is_empty": False, "current_value": "학생이 기입하였음"}) is False)
    check("_is_fillable 빈셀", fa._is_fillable({"is_empty": True}) is True)


# ── 2. fill 응답 파싱 (스키마형/배열형/평면/필터) ──
def t_parse_fill():
    print("[_parse_fill_response]")
    valid = {"s0_t0_r1_c1", "s0_t0_r2_c1"}
    import json as _j
    r = fa._parse_fill_response(_j.dumps({"채움": [
        {"id": "s0_t0_r1_c1", "값": "가"}, {"id": "s9_t9_r9_c9", "값": "버림"}]}), valid)
    check("스키마형+환각필터", r == {"s0_t0_r1_c1": "가"})
    r2 = fa._parse_fill_response('```json\n{"채움":[{"id":"s0_t0_r2_c1","값":"나"}]}\n```', valid)
    check("코드펜스", r2 == {"s0_t0_r2_c1": "나"})
    r3 = fa._parse_fill_response("설명만 있고 JSON 없음", valid)
    check("비JSON→빈dict", r3 == {})


# ── 3. envelope 스키마/파서 (3앱) ──
def t_envelope():
    print("[envelope]")
    check("hwp 23종", len(build_live_envelope_schema("hwp")["properties"]["액션"]["items"]["properties"]["action"]["enum"]) == len(LIVE_HWP_ACTIONS) == 23)
    check("excel 17종", len(LIVE_EXCEL_ACTIONS) == 17 and build_live_envelope_schema("excel"))
    check("ppt 9종", len(LIVE_PPT_ACTIONS) == 9 and build_live_envelope_schema("ppt"))
    check("word None", build_live_envelope_schema("word") is None)
    e = parse_envelope_response('{"응답":"제목 변경","액션":[{"action":"replace_paragraph","params":{"block_id":"1"}}]}')
    check("파싱 편집", e and e[0] == "제목 변경" and e[1][0]["action"] == "replace_paragraph")
    q = parse_envelope_response('{"응답":"제목은 A입니다","액션":[]}')
    check("파싱 질문(액션 None)", q and q[1] is None)
    check("비envelope→None", parse_envelope_response("그냥 텍스트") is None)


# ── 4. 셀 좌표 캘리브레이션 (셀 그룹) ──
def t_calibrate():
    print("[calibrate_with_scan]")
    bm = BlockManager(); bm._scan_mode = "hwpml"
    data = [(4, "td", 10, ""), (5, "text", 10, "항목"), (6, "td", 11, ""),
            (7, "text", 11, "내용"), (8, "td", 12, ""), (9, "text", 12, "장소"),
            (10, "td", 13, ""), (11, "text", 13, "국립과학관")]
    for bid, tp, vl, txt in data:
        bm.blocks[str(bid)] = Block(id=str(bid), position=(vl, 0 if tp == "td" else 1, 0),
                                    text=txt, block_type=tp)
    bm.blocks["2"] = Block(id="2", position=(0, 1, 0), text="제목", block_type="text")
    els = [{"type": "td", "text": "항목", "pos": [2, 0, 2], "list_id": 2},
           {"type": "td", "text": "내용", "pos": [3, 0, 2], "list_id": 3},
           {"type": "td", "text": "장소", "pos": [4, 0, 2], "list_id": 4},
           {"type": "td", "text": "국립과학관", "pos": [5, 0, 5], "list_id": 5}]
    st = bm.calibrate_with_scan(els)
    check("4셀/8블록 캘리브", st["calibrated_cells"] == 4 and st["calibrated_blocks"] == 8)
    check("내용블록 실좌표", bm.blocks["11"].position == (5, 0, 5) and bm.blocks["11"].calibrated)
    check("본문 무변경", bm.blocks["2"].calibrated is False)
    bm2 = BlockManager(); bm2._scan_mode = "hwpml"
    bm2.blocks["1"] = Block(id="1", position=(0, 0, 0), text="x", block_type="td")
    check("셀수 불일치→중단", bm2.calibrate_with_scan(els)["calibrated_cells"] == 0)


# ── 5. 본문 밑줄 블랭크 추출 (장식/누름틀 필터) ──
def t_body_blanks():
    print("[body blanks]")
    wd = workdir("off_body_")
    base = md_to_hwpx("# 테스트", "base", wd)
    P = lambda t: f'<hp:p><hp:run charPrIDRef="0"><hp:t>{t}</hp:t></hp:run></hp:p>'
    form = inject_section_body(base, str(wd / "b.hwpx"),
                              P("성명: ______ 소속: ______") + P("________________________"))
    blanks = extract_body_blanks(form)
    check("본문 블랭크 2개(장식 제외)", len(blanks) == 2)
    runs = body_blank_runs(form)
    check("전체 런 3개(장식 포함, ID정합)", len(runs) == 3 and runs[2][0] == "s0_u2")


# ── 6. 그리드 채움 라운드트립 (bench, 있으면) ──
def t_grid_roundtrip():
    print("[grid roundtrip (bench)]")
    if not have_bench():
        print("  SKIP  bench_score.hwpx 없음")
        return
    doc = parse_hwpx(str(BENCH))
    big = [g for g in doc.tables if g.row_cnt >= 10][0]
    hdr = big.header_row_count()
    ids = [f"{big.key}_r{r}_c{c}" for (r, c), cell in sorted(big.cells.items())
           if hdr <= r < big.row_cnt - 2 and cell.text.strip()]
    wd = workdir("off_grid_")
    blank = str(wd / "blank.hwpx")
    fill_hwpx_cells(str(BENCH), blank, {k: "" for k in ids})
    bdoc = parse_hwpx(blank)
    refound = {f["id"] for f in extract_blank_fields(bdoc) if f["is_empty"]}
    check("빈칸 재인식", all(i in refound for i in ids))
    out = str(wd / "filled.hwpx")
    n = fill_hwpx_cells(blank, out, {ids[0]: "테스트값"})
    rdoc = parse_hwpx(out)
    cell = {f"{g.key}_r{c.row}_c{c.col}": c.text for g in rdoc.tables for c in g.cells.values()}
    check("셀 주입", n >= 1 and cell.get(ids[0]) == "테스트값")


# ── 7. 채움 후 검증 + 재시도 (LLM 목킹) ──
def t_verify_retry():
    print("[verify + retry]")
    wd = workdir("off_vr_")
    form = md_to_hwpx("# 신청서\n\n| 항목 | 내용 |\n| --- | --- |\n| 성명 | ○○○ |\n| 소속 | ○○○ |\n",
                      "form", wd)
    doc = parse_hwpx(form)
    fields = [f for f in extract_blank_fields(doc, include_filled=True)
              if f.get("value_type") == "text" and fa._is_fillable(f)]
    ids = sorted(f["id"] for f in fields)
    # 1) 완전 반영 → missing 0
    out = str(wd / "full.hwpx")
    fill_hwpx_cells(form, out, {ids[0]: "홍길동", ids[1]: "1반"})
    ver, mis = fa._verify_hwpx_fill(out, {ids[0]: "홍길동", ids[1]: "1반"})
    check("전부 반영 검증", len(ver) == 2 and not mis)
    # 2) 일부 미반영 → missing 감지
    out2 = str(wd / "partial.hwpx")
    fill_hwpx_cells(form, out2, {ids[0]: "홍길동"})  # ids[1] 안 채움
    ver2, mis2 = fa._verify_hwpx_fill(out2, {ids[0]: "홍길동", ids[1]: "1반"})
    check("미반영 감지", list(mis2) == [ids[1]] and list(ver2) == [ids[0]])

    # 3) _retry_fill 단위: 미반영 subset만 재요청 → 값 반환 (enum도 그 subset)
    from engine import deps
    import json as _j
    seen_enum = {}

    class FakeLLM:
        def _pick_provider(self):
            return "local"

        def generate_chat(self, messages, *, max_tokens, temperature, provider, model,
                          json_schema=None):
            enum = json_schema["properties"]["채움"]["items"]["properties"]["id"]["enum"]
            seen_enum["ids"] = list(enum)
            return _j.dumps({"채움": [{"id": e, "값": "재시도값"} for e in enum]},
                            ensure_ascii=False)

    deps.llm_manager = FakeLLM()
    retry = fa._retry_fill({ids[1]: "x"}, fields, "", "지시", "local", "", {}, lambda m: None)
    check("재시도 enum=미반영 subset", seen_enum["ids"] == [ids[1]])
    check("재시도 값 반환", retry == {ids[1]: "재시도값"})

    # 4) run_form_assist 통합: 전부 반영 → 재시도 없음, 정직 보고
    class FakeLLM2:
        def _pick_provider(self):
            return "local"

        def generate_chat(self, messages, *, max_tokens, temperature, provider, model,
                          json_schema=None):
            enum = json_schema["properties"]["채움"]["items"]["properties"]["id"]["enum"]
            vmap = {ids[0]: "김철수", ids[1]: "3반"}
            return _j.dumps({"채움": [{"id": e, "값": vmap.get(e, "값")} for e in enum]},
                            ensure_ascii=False)

    deps.llm_manager = FakeLLM2()
    res = fa.run_form_assist(files=[{"path": form, "name": "form.hwpx"}],
                             instruction="테스트", output_file_idx=0,
                             llm_provider="local", output_dir=str(wd), log_cb=lambda m: None)
    check("통합: 미반영 0·검증 2", res.get("missing") == [] and res.get("verified") == 2)
    rdoc = parse_hwpx(res["file"])
    vals = {c.text for g in rdoc.tables for c in g.cells.values()}
    check("통합: 값 반영", "김철수" in vals and "3반" in vals)


# ── 8. 대형 양식 표 단위 청킹 (12000자 절단 제거) ──
def t_chunking():
    print("[table-chunk (대형 양식)]")
    wd = workdir("off_chunk_")
    # 큰 표 여러 개 → 그리드 렌더가 청크 예산 초과하도록 (긴 라벨 + 다수 행)
    rows = "\n".join(f"| 세부평가항목 및 배점 기준 {i:02d} |  |" for i in range(1, 61))
    one = f"| 구분 | 평가내용 |\n| --- | --- |\n{rows}\n"
    md = "# 대형 심사표\n\n" + "\n\n".join([one] * 5)
    form = md_to_hwpx(md, "big", wd)
    doc = parse_hwpx(form)
    fields = [f for f in extract_blank_fields(doc, include_filled=True)
              if f.get("value_type") == "text" and fa._is_fillable(f)]
    ids = [f["id"] for f in fields]
    check(f"빈칸 다수({len(ids)}개)", len(ids) >= 100)
    # 표별 렌더 합산이 청크 예산 초과 = 단일 프롬프트면 절단됐을 상황(청킹 필요)
    combined = sum(len(g.render(mark_blanks=True)) for g in doc.tables)
    check(f"단일 렌더면 절단({combined}자 > {fa._GRID_CHUNK_CHARS})", combined > fa._GRID_CHUNK_CHARS)

    # 목킹 LLM: 청크별 호출. 각 청크 enum의 id만 채우고, enum 합집합=전체 id 확인
    from engine import deps
    import json as _j
    seen = {"enum_union": set(), "calls": 0}

    class ChunkLLM:
        def _pick_provider(self):
            return "local"

        def generate_chat(self, messages, *, max_tokens, temperature, provider, model,
                          json_schema=None):
            enum = json_schema["properties"]["채움"]["items"]["properties"]["id"]["enum"]
            seen["enum_union"].update(enum)
            seen["calls"] += 1
            # 청크 렌더에 잘린 …(생략) 없어야 = 이 청크 id 전부 프롬프트에 노출
            content = messages[-1]["content"]
            for cid in enum:
                assert cid in content, f"셀ID {cid}가 청크 프롬프트에서 잘림!"
            return _j.dumps({"채움": [{"id": e, "값": f"v{e[-3:]}"} for e in enum]},
                            ensure_ascii=False)

    deps.llm_manager = ChunkLLM()
    plan = fa._plan_grid_fill(doc, fields, "", "지시", "", "local", "", {}, lambda m: None)
    check("2+청크 분할", seen["calls"] >= 2)
    check("모든 셀ID enum 노출(절단 없음)", seen["enum_union"] == set(ids))
    check("전 셀 채움 계획", len(plan) == len(ids))


def main():
    for fn in (t_placeholder, t_parse_fill, t_envelope, t_calibrate, t_body_blanks,
               t_grid_roundtrip, t_verify_retry, t_chunking):
        fn()
    print(f"\n=== 오프라인: {len(PASS)} PASS, {len(FAIL)} FAIL ===")
    if FAIL:
        print("실패:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
