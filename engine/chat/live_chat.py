"""라이브 문서 제어 채팅 — 자연어→액션 JSON→COM 실행."""

from __future__ import annotations

import json
import logging
import re
import math
from pathlib import Path
from typing import Any

_log = logging.getLogger("chat_handler")


# 라이브 편집 액션 카탈로그 (skills/hwp.md와 동일 계약) — 로컬 모델의
# 액션명 오타·환각을 GBNF enum으로 원천 차단하기 위한 목록.
LIVE_HWP_ACTIONS = [
    "replace_cell_content", "delete_cell_content", "replace_paragraph",
    "append_paragraph", "replace_table_row", "append_table_row",
    "apply_para_style", "insert_text", "find_and_replace_all", "set_field",
    "create_table", "style_table_row", "style_table_cell", "set_table_widths",
    "format_text", "style_cell", "style_row", "merge_cells",
    "set_table_col_width", "move_to_start", "move_to_end", "save", "save_as",
]


def build_live_envelope_schema(app_type: str = "hwp") -> dict | None:
    """로컬 모델용 라이브 응답 스키마 — {응답, 액션[]}.

    질문엔 액션 빈 배열 + 응답만, 편집엔 액션 배열. llama-server가 GBNF로
    강제하므로 형식·액션명을 못 틀린다 (파일채움 495/495와 같은 메커니즘).
    params는 액션별 구조가 달라 자유 객체로 두고 few-shot이 담당.
    """
    if app_type != "hwp":
        return None  # excel/ppt는 액션 카탈로그 상이 — 추후 확장
    return {
        "type": "object",
        "properties": {
            "응답": {"type": "string"},
            "액션": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": LIVE_HWP_ACTIONS},
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            },
        },
        "required": ["응답", "액션"],
    }


_LOCAL_ENVELOPE_NOTE = """

## 응답 형식 (반드시 준수)
반드시 아래 형태의 JSON 하나로만 답하라:
{"응답": "사용자에게 보여줄 한 줄 설명 또는 질문에 대한 답", "액션": [{"action": "...", "params": {...}}]}
- 문서 편집이 필요 없는 질문이면 "액션"은 빈 배열 []로 두고 "응답"에 답만 적어라.
- 예(편집): {"응답": "제목을 바꿉니다.", "액션": [{"action": "replace_paragraph", "params": {"block_id": "1", "new_text": "새 제목"}}]}
- 예(질문): {"응답": "이 문서의 제목은 OO입니다.", "액션": []}
"""


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
                doc_text += f"\n\n=== 블록 ID 매핑 (block_id 기반 편집용) ===\n{cvd_text}"

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
    skill_prompt = template.replace("{document_content}", doc_content)

    if design_skill and design_skill != "default":
        design_path = Path(__file__).parent.parent / "skills" / "design" / f"{design_skill}.md"
        if design_path.exists():
            design_content = design_path.read_text(encoding="utf-8")
            skill_prompt += f"\n\n---\n\n{design_content}\n\n위 디자인 스타일을 반드시 적용하라. 표, 서식, 색상 등 모든 디자인 액션에 이 스타일 규칙을 따라라."

    # 로컬 모델: envelope 형식 노트 (실제 강제는 GBNF json_schema가 담당)
    if provider == "local" and app_type == "hwp":
        skill_prompt += _LOCAL_ENVELOPE_NOTE

    messages = [{"role": "system", "content": skill_prompt}]
    for h in history[-10:]:
        if "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": h["content"]})
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
    skill_prompt = template.replace("{document_content}", doc_content)

    # 2.5 디자인 스킬 프롬프트 주입
    if design_skill and design_skill != "default":
        design_path = Path(__file__).parent.parent / "skills" / "design" / f"{design_skill}.md"
        if design_path.exists():
            design_content = design_path.read_text(encoding="utf-8")
            skill_prompt += f"\n\n---\n\n{design_content}\n\n위 디자인 스타일을 반드시 적용하라. 표, 서식, 색상 등 모든 디자인 액션에 이 스타일 규칙을 따라라."

    # 2.6 로컬 모델: envelope 형식 노트 + GBNF 스키마 강제 (액션명 오타 원천 차단)
    envelope_schema = None
    if provider == "local":
        envelope_schema = build_live_envelope_schema(app_type)
        if envelope_schema:
            skill_prompt += _LOCAL_ENVELOPE_NOTE

    # 3. LLM 호출
    messages = [{"role": "system", "content": skill_prompt}]
    for h in history[-10:]:
        if "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": h["content"]})
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
