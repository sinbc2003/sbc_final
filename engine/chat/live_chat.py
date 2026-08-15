"""라이브 문서 제어 채팅 — 자연어→액션 JSON→COM 실행."""

from __future__ import annotations

import json
import logging
import re
import math
from pathlib import Path
from typing import Any

_log = logging.getLogger("chat_handler")


# 라이브 편집 액션 카탈로그 (skills/*.md와 동일 계약) — 로컬 모델의
# 액션명 오타·환각을 GBNF enum으로 원천 차단하기 위한 목록.
LIVE_HWP_ACTIONS = [
    "replace_cell_content", "delete_cell_content", "replace_paragraph",
    "append_paragraph", "replace_table_row", "append_table_row",
    "apply_para_style", "insert_text", "find_and_replace_all", "set_field",
    "create_table", "clear_document", "style_table_row", "style_table_cell",
    "set_table_widths", "format_text", "style_cell", "style_row", "merge_cells",
    "set_table_col_width", "move_to_start", "move_to_end", "save", "save_as",
]

LIVE_EXCEL_ACTIONS = [
    "set_cell", "set_cells", "get_cell", "get_range", "set_formula",
    "format_range", "border", "merge_range", "auto_fit", "set_col_width",
    "set_row_height", "insert_row", "delete_row", "add_sheet", "active_sheet",
    "confirm", "save",
]

LIVE_PPT_ACTIONS = [
    "add_slide", "delete_slide", "set_text", "add_shape", "format_text",
    "set_slide_bg", "set_table_cell", "set_note", "save",
]

_LIVE_ACTION_CATALOG = {
    "hwp": LIVE_HWP_ACTIONS,
    "excel": LIVE_EXCEL_ACTIONS,
    "ppt": LIVE_PPT_ACTIONS,
}

# 앱별 few-shot 예시 (envelope 형식)
_ENVELOPE_EXAMPLES = {
    "hwp": '{"응답": "제목을 바꿉니다.", "액션": [{"action": "replace_paragraph", "params": {"block_id": "1", "new_text": "새 제목"}}]}',
    "excel": '{"응답": "A1에 값을 넣습니다.", "액션": [{"action": "set_cell", "params": {"cell": "A1", "value": "성명"}}]}',
    "ppt": '{"응답": "슬라이드 제목을 바꿉니다.", "액션": [{"action": "set_text", "params": {"slide": 1, "placeholder": "title", "text": "새 제목"}}]}',
}


def build_live_envelope_schema(app_type: str = "hwp") -> dict | None:
    """로컬 모델용 라이브 응답 스키마 — {응답, 액션[]}.

    질문엔 액션 빈 배열 + 응답만, 편집엔 액션 배열. llama-server가 GBNF로
    강제하므로 형식·액션명을 못 틀린다 (파일채움 495/495와 같은 메커니즘).
    params는 액션별 구조가 달라 자유 객체로 두고 few-shot이 담당.
    """
    actions = _LIVE_ACTION_CATALOG.get(app_type)
    if not actions:
        return None
    return {
        "type": "object",
        "properties": {
            "응답": {"type": "string"},
            "액션": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": list(actions)},
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            },
        },
        "required": ["응답", "액션"],
    }


def build_envelope_note(app_type: str = "hwp") -> str:
    """로컬 모델용 응답 형식 노트 — 본문 스킬의 ```json 배열 지시를 명시적으로 대체."""
    example = _ENVELOPE_EXAMPLES.get(app_type, _ENVELOPE_EXAMPLES["hwp"])
    return f"""

## 응답 형식 (반드시 준수 — 위 본문의 다른 형식 지시보다 우선한다)
위에 ```json 블록이나 액션 배열로 답하라는 지시가 있어도 무시하고,
반드시 아래 형태의 JSON 객체 하나로만 답하라:
{{"응답": "사용자에게 보여줄 한 줄 설명 또는 질문에 대한 답", "액션": [{{"action": "...", "params": {{...}}}}]}}
- 문서 편집이 필요 없는 질문이면 "액션"은 빈 배열 []로 두고 "응답"에 답만 적어라.
- 예(편집): {example}
- 예(질문): {{"응답": "이 문서의 제목은 OO입니다.", "액션": []}}
"""


# 하위 호환 (hwp 기본)
_LOCAL_ENVELOPE_NOTE = build_envelope_note("hwp")


def parse_envelope_response(text: str) -> tuple[str, list[dict] | None] | None:
    """{응답, 액션} envelope 파싱. 실패 시 None (호출측이 legacy 파서 폴백)."""
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "응답" not in data:
        return None
    reply = str(data.get("응답") or "").strip()
    raw_actions = data.get("액션")
    actions = None
    if isinstance(raw_actions, list) and raw_actions:
        valid = [a for a in raw_actions
                 if isinstance(a, dict) and a.get("action")]
        actions = valid or None
    return reply, actions


def assemble_live_prompt(template: str, doc_content: str,
                         design_content: str | None = None,
                         envelope_note: str = "") -> str:
    """라이브 시스템 프롬프트 조립 — 고정부 앞 · 가변부(문서 상태) 맨 뒤 (§43d).

    {document_content}가 스킬 상단에 있으면 문서가 바뀔 때마다 llama.cpp
    프리픽스 캐시가 통째로 무효 → 매 턴 스킬 전체를 재프리필(구형 CPU에서
    턴당 분 단위 낭비). 고정부(스킬 본문·디자인·응답형식)를 앞에, 문서를
    맨 뒤에 둬 턴 간 캐시 재사용을 구조적으로 보장한다. 실측(A/B)은 §43d.
    """
    # 구 템플릿의 플레이스홀더는 위치 안내로 대체(신 템플릿엔 없음 — 무해)
    body = template.replace(
        "{document_content}",
        "(문서 상태는 이 프롬프트 맨 아래 '## 현재 문서 상태' 참조)")
    if design_content:
        body += (f"\n\n---\n\n{design_content}\n\n"
                 "위 디자인 스타일을 반드시 적용하라. 표, 서식, 색상 등 "
                 "모든 디자인 액션에 이 스타일 규칙을 따라라.")
    if envelope_note:
        body += envelope_note
    body += f"\n\n## 현재 문서 상태\n\n{doc_content}"
    return body


def trim_live_history(history: list[dict], max_msgs: int = 10,
                      max_chars: int = 1200) -> list[dict]:
    """라이브 채팅 히스토리 다이어트 — 컨텍스트 폭주 방지.

    UI가 실행 결과 로그(✓/✗ 줄 수십 개)를 assistant 메시지에 누적하고 그걸
    그대로 히스토리로 재전송 → 문서 CVD가 커진 상태에서 8K 컨텍스트 초과
    (실측 15.7K 토큰, "오류" 연발). 결과 로그는 대화 맥락이 아니므로 제거하고
    메시지당 길이도 캡. (2차 방어는 llm_manager의 컨텍스트 초과 축소 재시도.)
    """
    out = []
    for h in history[-max_msgs:]:
        if "role" not in h or "content" not in h:
            continue
        c = "\n".join(l for l in str(h["content"]).splitlines()
                      if not re.match(r"^[✓✗⏳]\s", l)).strip()
        if len(c) > max_chars:
            c = c[:max_chars] + " …(생략)"
        out.append({"role": h["role"], "content": c})
    return out


def merge_new_table_fills(actions: list[dict] | None) -> list[dict] | None:
    """같은 배치에서 create_table 뒤의 '새 표 채움 시도'를 data 행으로 병합.

    소형모델은 '표 만들고 채워라'를 자주 쪼갠다: create_table(헤더만) 후
    replace_cell_content를 지어낸 block_id로 (E4B 실측 재현 — 빈 문서
    식단표에서 헤더행만 만든 뒤 block_id 1~4에 행 전체를 \\n으로 뭉쳐 주입).
    새 표의 블록 번호는 스캔 목록에 존재하지 않으므로 그 번호는 반드시
    허구고, 실행하면 엉뚱한 블록을 덮는다. 스킬 지시("data 한 방에")로는
    막히지 않음을 실측 — 하네스가 흡수한다:

    create_table 이후의 채움류 액션 중 block_id가 현재 스캔의 표 셀이
    아닌 것을 행 데이터로 해석(row_texts는 그대로, new_text는 \\n 분할)해
    create_table.data 뒤에 붙이고 배치에서 제거한다. 실존 셀 편집은 불변.
    치수 정합은 editor.normalize_table_spec이 마무리(선언·data 어긋남 흡수).
    """
    if not actions:
        return actions
    ct_idx = next((i for i, a in enumerate(actions)
                   if a.get("action") == "create_table"
                   and isinstance(a.get("params"), dict)), None)
    if ct_idx is None:
        return actions

    # 현재 스캔에 실존하는 표 셀 block_id — 이것만 정당한 셀 편집 대상
    known_cells: set[str] = set()
    try:
        from engine.live_controller import _get_hwp_ctrl
        bm = _get_hwp_ctrl()._block_manager
        if bm and bm.blocks:
            known_cells = {bid for bid, b in bm.blocks.items()
                           if getattr(b, "block_type", "") == "td"}
    except Exception:
        pass  # 스캔 없음(빈 문서 등) = 실존 셀 없음

    ct_params = actions[ct_idx]["params"]
    data = ct_params.get("data")
    rows: list = [list(r) if isinstance(r, (list, tuple)) else [r] for r in data] \
        if isinstance(data, (list, tuple)) else ([] if data is None else [[str(data)]])
    merged = 0
    out: list[dict] = []
    for i, a in enumerate(actions):
        if i <= ct_idx or a.get("action") not in (
                "replace_cell_content", "replace_table_row", "append_table_row"):
            out.append(a)
            continue
        p = a.get("params") or {}
        if str(p.get("block_id", "")) in known_cells:
            out.append(a)  # 실존 셀 편집 — 건드리지 않음
            continue
        row_texts = p.get("row_texts")
        if isinstance(row_texts, (list, tuple)) and row_texts:
            rows.append([str(c) for c in row_texts])
        else:
            txt = str(p.get("new_text") or "").strip()
            if not txt:
                continue  # 내용 없는 허구 id 액션은 그냥 버림
            rows.append(txt.split("\n"))
        merged += 1
    if merged:
        ct_params["data"] = rows
        _log.info(f"라이브 표 병합: 허구 block_id 채움 {merged}건 → create_table data {len(rows)}행")
    return out


def parse_actions_response(text: str) -> list[dict] | None:
    """LLM 응답에서 액션 JSON 배열 추출."""
    # ```json ... ``` 블록
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    candidate = match.group(1).strip() if match else text.strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # [ ... ] 직접 탐색
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start == -1 or bracket_end == -1:
            return None
        try:
            data = json.loads(text[bracket_start:bracket_end + 1])
        except json.JSONDecodeError:
            return None

    if isinstance(data, list) and len(data) > 0:
        if all(isinstance(a, dict) and "action" in a for a in data):
            return data
    return None



def _read_with_cvd(app_type: str, live_controller) -> str:
    """HWP는 CVD 스캔(block_id 매핑 포함), 나머지는 plain read.

    기존 ctrl._hwp 연결을 재사용하여 이중 Hwp() 생성으로 인한
    빈 문서 연결 문제를 방지한다. 연결이 없을 때만 create_fresh_hwp().
    """
    if app_type == "hwp":
        import logging
        _logger = logging.getLogger("chat_handler")
        try:
            import pythoncom
            pythoncom.CoInitialize()

            from engine import deps
            from engine.live_controller import _get_hwp_ctrl
            from engine.hwp_controller import DocumentScanner, BlockManager, HwpEditor

            ctrl = _get_hwp_ctrl()

            # 기존 연결 재사용 — _ensure_hwp_connection()에서 이미 연결된 경우
            hwp = None
            if ctrl._hwp and ctrl._connected:
                try:
                    ctrl._hwp.get_pos()  # 연결 유효성 확인
                    hwp = ctrl._hwp
                    _logger.info("_read_with_cvd: 기존 HWP 연결 재사용")
                except Exception:
                    _logger.info("_read_with_cvd: 기존 연결 stale, 새로 생성")

            if not hwp:
                hwp = deps.create_fresh_hwp()
                _logger.info("_read_with_cvd: 새 HWP 연결 생성")

            # 문서 정보 로깅
            try:
                doc_name = hwp.Path or "(새 문서)"
                _logger.info(f"_read_with_cvd: 문서={doc_name}")
            except Exception:
                pass

            # 텍스트 읽기
            parts = []
            try:
                pd = hwp.get_pagedef_as_dict("eng")
                pw, ph = pd.get("PaperWidth", 210), pd.get("PaperHeight", 297)
                lm, rm = pd.get("LeftMargin", 30), pd.get("RightMargin", 30)
                tm, bm_ = pd.get("TopMargin", 25), pd.get("BottomMargin", 25)
                gt = pd.get("GutterLen", 0)
                uw = round(pw - lm - rm - gt, 1)
                parts.append(f"[용지] {pw}x{ph}mm, 여백 좌{lm} 우{rm} 상{tm} 하{bm_}mm, 가용폭 {uw}mm")
            except Exception:
                parts.append("[용지] 정보 없음 (A4 가정: 가용폭 약150mm)")

            hwp.MoveDocBegin()
            hwp.init_scan(option=4, range=0x0077)
            for _ in range(10000):
                state, text = hwp.get_text()
                if state == 0: break
                if state == 1: continue
                if text and text.strip():
                    parts.append(text.strip())
            hwp.release_scan()
            doc_text = "\n".join(parts)

            # HwpController 싱글턴에 연결 공유 → extract_cvd가 이 연결을 재사용,
            # 이후 편집(execute)도 같은 상태 사용. scanner/editor는 현재 hwp로 재바인딩(stale 참조 방지).
            ctrl._hwp = hwp
            ctrl._connected = True
            ctrl._scanner = DocumentScanner(hwp)
            ctrl._editor = HwpEditor(hwp, ctrl._block_manager)

            def _scan_cvd():
                """CVD 스캔 — HWPML 우선(병합/스타일 보존), 실패 시 커서 스캔 폴백.

                extract_cvd(mode="auto")가 내부에서 BlockManager 초기화까지 수행하므로
                이후 block_id 기반 편집이 그대로 동작한다.
                Returns: (cvd_text, block_count, scan_mode)
                """
                try:
                    result = ctrl.extract_cvd(mode="auto")
                    if result.get("cvd") and not result.get("error"):
                        return result["cvd"], result.get("block_count", 0), result.get("scan_mode", "?")
                    _logger.warning(f"_read_with_cvd: extract_cvd 결과 없음 — 커서 스캔 폴백: {result.get('error')}")
                except Exception as e_cvd:
                    _logger.warning(f"_read_with_cvd: extract_cvd 예외 — 커서 스캔 폴백: {e_cvd}")
                # 폴백: 기존 커서 스캔 경로 (BlockManager 상태도 함께 갱신)
                scanner = DocumentScanner(hwp)
                elements = scanner.scan()
                bm = BlockManager()
                bm.initialize_from_scan(elements)
                ctrl._scanner = scanner
                ctrl._block_manager = bm
                ctrl._editor = HwpEditor(hwp, bm)
                return bm.to_cvd_text(), len(elements), "cursor"

            # CVD 스캔
            cvd_text, block_count, scan_mode = _scan_cvd()

            # 빈 문서 감지: 블록 ≤2개이면 다른 문서로 전환 시도
            if block_count <= 2:
                _logger.warning(f"_read_with_cvd: 블록 {block_count}개 — 빈 문서 감지")
                switched = False
                try:
                    xdocs = hwp.XHwpDocuments
                    count = xdocs.Count
                    _logger.info(f"_read_with_cvd: XHwpDocuments.Count={count}")
                    if count > 1:
                        # 다른 문서(내용 있는)로 전환 시도
                        for i in range(count):
                            doc = xdocs.Item(i)
                            doc.SetActive_XHwpDocument()
                            hwp.MoveDocBegin()
                            hwp.init_scan(option=4, range=0x0077)
                            test_parts = []
                            for _ in range(100):
                                state, text = hwp.get_text()
                                if state == 0: break
                                if state == 1: continue
                                if text and text.strip():
                                    test_parts.append(text.strip())
                            hwp.release_scan()
                            if len(test_parts) > 1:
                                _logger.info(f"_read_with_cvd: 문서 {i}번으로 전환 ({len(test_parts)} 텍스트)")
                                # 이 문서로 재스캔
                                parts = parts[:1] + test_parts
                                doc_text = "\n".join(parts)
                                cvd_text, block_count, scan_mode = _scan_cvd()
                                switched = True
                                break
                except Exception as e2:
                    _logger.warning(f"_read_with_cvd: 문서 전환 실패: {e2}")
                if not switched:
                    _logger.warning("_read_with_cvd: 모든 문서가 비어있거나 전환 실패")

            _logger.info(f"_read_with_cvd: {block_count}개 블록 스캔({scan_mode}), CVD {len(cvd_text) if cvd_text else 0}자")

            if cvd_text:
                # §43d 프롬프트 다이어트: CVD에 전체 텍스트가 블록별로 이미 있어
                # 원문 스캔을 함께 실으면 문서가 2번 동봉된다(실측 — 프롬프트
                # 비만의 주범, 15.7K 초과 사건의 절반). 용지 정보만 유지(CVD에
                # 없는 레이아웃)하고 본문은 CVD로 일원화.
                return (parts[0] if parts else "") + \
                    f"\n\n=== 블록 ID 매핑 (block_id 기반 편집용) ===\n{cvd_text}"

            return doc_text
        except Exception as e:
            _logger.error(f"_read_with_cvd 실패: {e}", exc_info=True)
    return live_controller.read(app_type)



def prepare_live_chat_messages(
    message: str,
    app_type: str,
    history: list[dict],
    live_controller,
    model: str | None = None,
    design_skill: str | None = None,
) -> tuple[list[dict], str, str]:
    """LLM 호출용 메시지 배열 준비. Returns: (messages, provider, model_name)."""
    from pathlib import Path

    if model and "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        provider, model_name = "openai", "gpt-4.1"

    skill_path = Path(__file__).parent.parent / "skills" / f"{app_type}.md"
    if not skill_path.exists():
        return [], provider, model_name

    template = skill_path.read_text(encoding="utf-8")
    doc_content = _read_with_cvd(app_type, live_controller)

    design_content = None
    if design_skill and design_skill != "default":
        design_path = Path(__file__).parent.parent / "skills" / "design" / f"{design_skill}.md"
        if design_path.exists():
            design_content = design_path.read_text(encoding="utf-8")

    # 로컬 모델: envelope 형식 노트 (실제 강제는 GBNF json_schema가 담당)
    envelope_note = ""
    if provider == "local" and app_type in _LIVE_ACTION_CATALOG:
        envelope_note = build_envelope_note(app_type)

    skill_prompt = assemble_live_prompt(template, doc_content, design_content, envelope_note)

    messages = [{"role": "system", "content": skill_prompt}]
    messages.extend(trim_live_history(history))
    messages.append({"role": "user", "content": message})
    return messages, provider, model_name



def handle_live_chat(
    message: str,
    app_type: str,
    history: list[dict],
    llm_manager,
    live_controller,
    preview: bool = True,
    model: str | None = None,
    design_skill: str | None = None,
) -> dict[str, Any]:
    """라이브 문서 제어 채팅. 자연어 → 액션 JSON → COM 실행.

    preview=True: 액션만 반환 (실행 안 함), preview=False: 즉시 실행.
    Returns: {reply, actions, results}
    """
    from pathlib import Path

    # 모델 파싱
    if model and "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        provider, model_name = "openai", "gpt-4.1"

    # 1. 스킬 프롬프트 로드
    skill_path = Path(__file__).parent.parent / "skills" / f"{app_type}.md"
    if not skill_path.exists():
        return {"reply": f"스킬 없음: {app_type}", "actions": None, "results": None}

    template = skill_path.read_text(encoding="utf-8")

    # 2. 문서 내용 읽기
    doc_content = _read_with_cvd(app_type, live_controller)

    # 2.5 디자인 스킬 프롬프트
    design_content = None
    if design_skill and design_skill != "default":
        design_path = Path(__file__).parent.parent / "skills" / "design" / f"{design_skill}.md"
        if design_path.exists():
            design_content = design_path.read_text(encoding="utf-8")

    # 2.6 로컬 모델: envelope 형식 노트 + GBNF 스키마 강제 (액션명 오타 원천 차단)
    envelope_schema = None
    envelope_note = ""
    if provider == "local":
        envelope_schema = build_live_envelope_schema(app_type)
        if envelope_schema:
            envelope_note = build_envelope_note(app_type)

    # 고정부 앞·문서 뒤 조립 (§43d — 프리픽스 캐시)
    skill_prompt = assemble_live_prompt(template, doc_content, design_content, envelope_note)

    # 3. LLM 호출
    messages = [{"role": "system", "content": skill_prompt}]
    messages.extend(trim_live_history(history))
    messages.append({"role": "user", "content": message})

    try:
        reply = llm_manager.generate_chat(
            messages, max_tokens=4096, temperature=0.1,
            provider=provider, model=model_name,
            json_schema=envelope_schema,
        )
    except Exception as e:
        return {"reply": f"LLM 호출 실패: {e}", "actions": None, "results": None}

    # 4. 액션 파싱 — envelope(스키마 강제) 우선, legacy 텍스트 파싱 폴백
    envelope = parse_envelope_response(reply) if envelope_schema else None
    if envelope is not None:
        env_reply, actions = envelope
        if not actions:
            return {"reply": env_reply or reply, "actions": None, "results": None}
        reply = env_reply or reply
    else:
        actions = parse_actions_response(reply)
        if not actions:
            return {"reply": reply, "actions": None, "results": None}

    # 4.1 새 표 채움 병합 — 허구 block_id 실행을 원천 차단 (preview에도 병합안이 보이게)
    if app_type == "hwp":
        actions = merge_new_table_fills(actions)

    # 4.5 사용자 친화적 메시지 추출
    if envelope is not None:
        # envelope의 "응답"이 이미 사용자용 문장
        friendly_reply = reply or f"다음 작업을 실행합니다: {', '.join(a.get('action', '') for a in actions)}"
    else:
        friendly_reply = reply
        json_match = re.search(r"```(?:json)?\s*\n?", reply)
        if json_match:
            before = reply[:json_match.start()].strip()
            if before:
                friendly_reply = before
            else:
                # JSON만 있는 경우 액션으로부터 요약 생성
                action_names = [a.get("action", "") for a in actions]
                friendly_reply = f"다음 작업을 실행합니다: {', '.join(action_names)}"
        else:
            # ```json 없이 raw JSON인 경우
            action_names = [a.get("action", "") for a in actions]
            friendly_reply = f"다음 작업을 실행합니다: {', '.join(action_names)}"

    # 5. 미리보기 모드: 액션만 반환 (실행 안 함)
    if preview:
        return {
            "reply": friendly_reply,
            "actions": actions,
            "results": None,
            "summary": None,
            "preview": True,
        }

    # 5b. 즉시 실행 모드
    import logging as _logging
    _exec_logger = _logging.getLogger("chat_handler")
    # 편집기 상태 확인
    if app_type == "hwp":
        from engine.live_controller import _get_hwp_ctrl
        _hctrl = _get_hwp_ctrl()
        _exec_logger.debug(f"실행 시작: bm_blocks={len(_hctrl._block_manager.blocks) if _hctrl._block_manager else 0}")
    # PPT: add_slide를 먼저 실행해서 슬라이드 생성 후 서식/텍스트 적용
    # HWP: block_id 기반 액션을 뒤쪽부터 실행 (좌표 밀림 방지)
    if app_type == "ppt":
        actions = live_controller.reorder_ppt_actions(actions)
    elif app_type == "hwp":
        actions = live_controller.reorder_hwp_block_actions(actions)
    results = []
    for act in actions:
        action_name = act.get("action", "")
        params = act.get("params", {})
        try:
            result = live_controller.execute(app_type, action_name, params)
            results.append({
                "action": action_name,
                "success": result.success,
                "message": result.message,
            })
        except Exception as e:
            results.append({
                "action": action_name,
                "success": False,
                "message": str(e),
            })

    # 6. 실행 결과 요약
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    summary = f"{ok}개 성공" + (f", {fail}개 실패" if fail else "")

    return {
        "reply": friendly_reply,
        "actions": actions,
        "results": results,
        "summary": summary,
    }
