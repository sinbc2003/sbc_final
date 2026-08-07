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


# ── 9. 실행 취소 (협조적 취소, 노드 경계) ──
def t_cancel():
    print("[runner cancel]")
    import threading
    from engine.loader import NodeDefinition, NodeRegistry
    from engine.runner import PipelineRunner, Workflow, CANCEL_MESSAGE

    ran: list[str] = []

    def make(nid, fn):
        return NodeDefinition(
            id=nid, name=nid, version="1.0.0", category="test", icon="", author="",
            description="", inputs=[], outputs=[], params=[], resource={},
            dependencies=[], use_when=[], execute_fn=fn,
        )

    ev = threading.Event()
    seen_ctx: dict = {}

    def step1(inputs, params, ctx):
        ran.append("a")
        seen_ctx["is_cancelled"] = callable(ctx.get("is_cancelled"))
        seen_ctx["before"] = ctx["is_cancelled"]()
        ev.set()          # 첫 노드 실행 중 사용자가 '중단'을 누른 상황
        seen_ctx["after"] = ctx["is_cancelled"]()
        return {}

    def step2(inputs, params, ctx):
        ran.append("b")
        return {}

    reg = NodeRegistry()
    reg._nodes = {"step1": make("step1", step1), "step2": make("step2", step2)}
    # 엣지로 실행 순서를 고정 (노드 집합 순회 순서에 의존하지 않게)
    wf = Workflow.from_json({
        "id": "t", "name": "t", "nodes": [
            {"id": "n1", "type": "step1"}, {"id": "n2", "type": "step2"}],
        "edges": [{"from": "n1", "from_port": "", "to": "n2", "to_port": ""}],
    })

    runner = PipelineRunner(registry=reg, config={"output_dir": "___없는경로___"},
                            on_log=lambda *_: None, cancel_event=ev)
    res = runner.run(wf)
    check("첫 노드는 실행, 다음 노드는 미실행", ran == ["a"])
    check("cancelled 플래그", res.cancelled is True and res.success is False)
    check("중단 사유 노출", CANCEL_MESSAGE in res.errors)
    check("노드 context에 is_cancelled 전달",
          seen_ctx.get("is_cancelled") is True
          and seen_ctx.get("before") is False and seen_ctx.get("after") is True)

    # 취소하지 않으면 전부 실행된다 (회귀 방어)
    ran.clear()
    runner2 = PipelineRunner(registry=reg, config={"output_dir": "___없는경로___"},
                             on_log=lambda *_: None)
    res2 = runner2.run(Workflow.from_json({
        "id": "t", "name": "t",
        "nodes": [{"id": "n1", "type": "step2"}, {"id": "n2", "type": "step2"}], "edges": []}))
    check("미취소 시 전 노드 실행", ran == ["b", "b"] and res2.success and not res2.cancelled)


# ── 10. 워크플로우 생성 envelope (GBNF 강제 스키마 + 파서) ──
def t_workflow_envelope():
    print("[workflow envelope]")
    from engine.chat.workflow import (
        build_workflow_envelope_schema, build_workflow_envelope_note,
        parse_workflow_envelope, validate_workflow,
    )

    from pathlib import Path as _P
    from engine.loader import NodeRegistry

    reg = NodeRegistry()
    reg.load_all(_P(ROOT) / "nodes")
    sch = build_workflow_envelope_schema(reg)
    wf_obj = sch["properties"]["워크플로우"]["anyOf"][0]
    node_items = wf_obj["properties"]["nodes"]["items"]
    check("노드 type enum = 레지스트리 id", node_items["properties"]["type"]["enum"] == reg.list_ids())
    check("출력 포트 enum", "텍스트" in wf_obj["properties"]["edges"]["items"]
          ["properties"]["from_port"]["enum"])
    check("입력 포트 enum(환각 영어명 배제)",
          "입력텍스트" in wf_obj["properties"]["edges"]["items"]["properties"]["to_port"]["enum"]
          and "input_text" not in wf_obj["properties"]["edges"]["items"]["properties"]["to_port"]["enum"])
    check("워크플로우 null 허용", sch["properties"]["워크플로우"]["anyOf"][1] == {"type": "null"})
    check("응답·워크플로우 필수", sch["required"] == ["응답", "워크플로우"])
    check("엣지 포트 필수", set(sch["properties"]["워크플로우"]["anyOf"][0]
          ["properties"]["edges"]["items"]["required"]) == {"from", "from_port", "to", "to_port"})
    check("형식 노트에 null 예시", "null" in build_workflow_envelope_note())

    ok = parse_workflow_envelope(
        '{"응답":"PDF 요약 워크플로우입니다","워크플로우":{"name":"요약","nodes":'
        '[{"id":"f1","type":"file_input","params":{}},{"id":"s1","type":"llm_summarize","params":{}}],'
        '"edges":[{"from":"f1","from_port":"텍스트","to":"s1","to_port":"텍스트"}]}}')
    check("envelope 파싱(워크플로우)", ok is not None and ok[1] is not None
          and ok[0] == "PDF 요약 워크플로우입니다" and len(ok[1]["nodes"]) == 2)
    check("position 자동 배치", ok[1]["nodes"][0].get("position", {}).get("x") == 100
          and ok[1]["nodes"][1]["position"]["x"] == 350)

    q = parse_workflow_envelope('{"응답":"그건 pdf_to_md를 쓰세요","워크플로우":null}')
    check("envelope 파싱(일반질문→None)", q is not None and q[1] is None and q[0].startswith("그건"))
    check("비envelope→None", parse_workflow_envelope("그냥 텍스트") is None)
    check("코드펜스 허용", parse_workflow_envelope(
        '```json\n{"응답":"a","워크플로우":null}\n```') == ("a", None))

    # 스키마 강제를 못 쓰는 API 경로라도 validate_workflow가 환각 type을 잡는다
    errs = validate_workflow({"nodes": [{"id": "x", "type": "환각노드"}], "edges": []}, reg)
    check("환각 노드 type 검증", any("환각노드" in e for e in errs))


# ── 11. 엣지 포트 코드 보정 (소형모델 포트명 환각) ──
def t_port_repair():
    print("[repair_workflow_ports]")
    from pathlib import Path as _P
    from engine.loader import NodeRegistry
    from engine.chat.workflow import repair_workflow_ports, validate_workflow

    reg = NodeRegistry()
    reg.load_all(_P(ROOT) / "nodes")
    if len(reg) == 0:
        check("노드 카탈로그 로드", False)
        return

    # 실측 실패 사례 재현: 노드 type은 맞지만 포트명을 영어로 지어냄
    data = {
        "nodes": [
            {"id": "f1", "type": "file_input", "params": {"auto_convert": True}},
            {"id": "s1", "type": "llm_summarize", "params": {}},
            {"id": "h1", "type": "md_to_hwpx", "params": {}},
        ],
        "edges": [
            {"from": "f1", "from_port": "text", "to": "s1", "to_port": "input_text"},
            {"from": "s1", "from_port": "output", "to": "h1", "to_port": "markdown"},
        ],
    }
    fixes = repair_workflow_ports(data, reg)
    e0, e1 = data["edges"]
    check("file_input→llm_summarize 포트 보정",
          e0["from_port"] == "텍스트" and e0["to_port"] == "입력텍스트")
    check("llm_summarize→md_to_hwpx 포트 보정",
          e1["from_port"] == "출력텍스트" and e1["to_port"] == "텍스트")
    check(f"보정 내역 기록({len(fixes)}건)", len(fixes) == 4)
    check("보정 후 검증 통과", validate_workflow(data, reg) == [])

    # 이미 올바른 포트는 건드리지 않는다
    ok = {"nodes": [{"id": "f1", "type": "file_input", "params": {}},
                    {"id": "s1", "type": "llm_summarize", "params": {}}],
          "edges": [{"from": "f1", "from_port": "텍스트", "to": "s1", "to_port": "입력텍스트"}]}
    check("정상 엣지는 무변경", repair_workflow_ports(ok, reg) == []
          and ok["edges"][0]["from_port"] == "텍스트")

    # 후보가 둘 이상이면 손대지 않고 검증이 사유를 알린다 (무음 오배선 방지)
    amb = {"nodes": [{"id": "t1", "type": "text_input", "params": {}},
                     {"id": "m1", "type": "data_merge", "params": {}}],
           "edges": [{"from": "t1", "from_port": "텍스트", "to": "m1", "to_port": "in"}]}
    repair_workflow_ports(amb, reg)
    check("애매하면 미보정 + 검증 오류",
          amb["edges"][0]["to_port"] == "in" and validate_workflow(amb, reg) != [])

    # 실측 실패 2: 포트명은 실재하지만 타입이 어긋난 연결(텍스트 출력 → 파일 입력)
    mism = {"nodes": [{"id": "f1", "type": "file_input", "params": {}},
                      {"id": "p1", "type": "pdf_to_md", "params": {}}],
            "edges": [{"from": "f1", "from_port": "텍스트", "to": "p1", "to_port": "파일"}]}
    repair_workflow_ports(mism, reg)
    check("타입 불일치 연결 보정(텍스트→파일)", mism["edges"][0]["from_port"] == "파일")
    check("보정 후 검증 통과", validate_workflow(mism, reg) == [])

    bad = {"nodes": [{"id": "f1", "type": "file_input", "params": {}},
                     {"id": "s1", "type": "llm_summarize", "params": {}}],
           "edges": [{"from": "f1", "from_port": "파일", "to": "s1", "to_port": "입력텍스트"}]}
    # 보정 불가능한 경우가 아니라 보정 가능 — 파일→입력텍스트는 텍스트 출력으로 유일 보정
    repair_workflow_ports(bad, reg)
    check("파일 출력→텍스트 입력도 보정", bad["edges"][0]["from_port"] == "텍스트")

    # 실측 실패 3: 자기 자신 연결(단일 노드 워크플로우에서 소형모델 상습)
    loop = {"nodes": [{"id": "x1", "type": "xlsx_to_md", "params": {}}],
            "edges": [{"from": "x1", "from_port": "파일", "to": "x1", "to_port": "텍스트"}]}
    repair_workflow_ports(loop, reg)
    errs2 = validate_workflow(loop, reg)
    check("자기 연결은 사유 명시", any("자기 자신" in e for e in errs2))
    check("자기 연결은 보정하지 않음", loop["edges"][0]["to_port"] == "텍스트")

    # 포트 오류 메시지에 가능한 포트명을 함께 안내
    e3 = validate_workflow({"nodes": [{"id": "s1", "type": "llm_summarize", "params": {}},
                                      {"id": "s2", "type": "llm_summarize", "params": {}}],
                            "edges": [{"from": "s1", "from_port": "없는포트",
                                       "to": "s2", "to_port": "입력텍스트"}]}, reg)
    check("오류에 가능한 포트 안내", any("가능:" in e and "출력" in e for e in e3))


def main():
    for fn in (t_placeholder, t_parse_fill, t_envelope, t_calibrate, t_body_blanks,
               t_grid_roundtrip, t_verify_retry, t_chunking, t_cancel, t_workflow_envelope, t_port_repair):
        fn()
    print(f"\n=== 오프라인: {len(PASS)} PASS, {len(FAIL)} FAIL ===")
    if FAIL:
        print("실패:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
