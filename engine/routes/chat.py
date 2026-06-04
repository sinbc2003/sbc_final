"""채팅 엔드포인트 — 일반 채팅, 라이브 문서 제어, 스트리밍."""

from __future__ import annotations
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from engine import deps

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    model: str | None = None


class LiveChatRequest(BaseModel):
    message: str
    app_type: str = "hwp"
    history: list[dict[str, str]] = []
    doc_index: int | None = None
    preview: bool = True
    model: str | None = None
    design_skill: str | None = None


class BatchExecuteRequest(BaseModel):
    app_type: str
    actions: list[dict[str, Any]]


class StreamChatRequest(BaseModel):
    message: str
    app_type: str = "hwp"
    history: list[dict[str, str]] = []
    doc_index: int | None = None
    model: str | None = None
    design_skill: str | None = None


# ── 일반 채팅 ──

@router.post("/api/chat")
async def chat(req: ChatRequest):
    from engine.chat_handler import handle_chat, detect_form_intent, extract_file_paths
    import asyncio, concurrent.futures, os

    # FormAssist 자동 라우팅: 양식 파일 + 수정 의도 감지 시 COM 스레드에서 처리
    file_paths = extract_file_paths(req.message)
    if detect_form_intent(req.message, file_paths):
        result = await _handle_form_assist_async(req.message, file_paths, req.model)
        return result

    return handle_chat(req.message, req.history, deps.registry, deps.llm_manager, deps.store, model=req.model)


async def _handle_form_assist_async(message: str, file_paths: list[str], model: str | None) -> dict:
    """FormAssist를 async 컨텍스트에서 실행 (HWP COM은 run_on_com으로)."""
    import asyncio, concurrent.futures, os
    from pathlib import Path
    from engine.chat_handler import extract_user_instruction, FORM_EXTENSIONS
    from engine.form_assist import run_form_assist

    instruction = extract_user_instruction(message)
    files = [{"path": p, "name": Path(p).name} for p in file_paths]

    output_idx = -1
    for i, f in enumerate(files):
        if Path(f["path"]).suffix.lower() in FORM_EXTENSIONS:
            output_idx = i

    logs: list[str] = []

    # HWP InitScan (COM 스레드 필요)
    hwp_elements = None
    if output_idx >= 0:
        tp = files[output_idx]["path"]
        ext = Path(tp).suffix.lower()
        if ext in (".hwp", ".hwpx"):
            try:
                from engine.form_assist import scan_hwp_structure
                hwp_elements = await deps.run_on_com(lambda: scan_hwp_structure(tp, lambda m: logs.append(m)))
            except Exception as e:
                logs.append(f"HWP 스캔 실패: {e}")

    out_dir = deps.settings_mgr.get("general", "output_dir", "")

    # run_form_assist (CPU-bound → 스레드풀)
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool, lambda: run_form_assist(
                files=files, instruction=instruction, output_file_idx=output_idx,
                llm_provider="auto", llm_model=model or "",
                log_cb=lambda m: logs.append(m), output_dir=out_dir,
                hwp_elements=hwp_elements,
            )
        )

    # HWP COM 채우기
    output_file = result.get("file")
    fill_data = result.get("fill_data")
    template_path = result.get("template_path")
    save_dir = result.get("save_dir", out_dir)

    if fill_data and template_path and hwp_elements:
        try:
            from engine.form_assist import fill_hwp_by_cells
            output_file = await deps.run_on_com(
                lambda: fill_hwp_by_cells(template_path, fill_data, hwp_elements, lambda m: logs.append(m), output_dir=save_dir)
            )
            result["file"] = output_file
        except Exception as e:
            logs.append(f"HWP 채우기 실패: {e}")

    if not output_file:
        output_file = result.get("file")

    # 완성 파일 자동 열기 (비-HWP)
    if output_file and os.path.exists(output_file):
        ext = Path(output_file).suffix.lower()
        if ext not in (".hwp", ".hwpx"):
            try:
                os.startfile(output_file)
            except Exception:
                pass

    # 응답 구성
    form_name = files[output_idx]["name"] if output_idx >= 0 else "양식"
    reply_parts = [f"**{form_name}** 양식을 분석하여 채웠습니다."]
    if output_file:
        reply_parts.append(f"\n완성 파일: `{Path(output_file).name}`")
    summary_logs = [l for l in logs if "빈칸" in l or "완료" in l or "완성" in l or "항목" in l]
    if summary_logs:
        reply_parts.append("\n" + "\n".join(f"- {l}" for l in summary_logs[-5:]))

    return {
        "reply": "\n".join(reply_parts),
        "workflow_id": None,
        "workflow_json": None,
        "form_assist": True,
        "file": output_file,
        "logs": logs,
    }


# ── 라이브 문서 제어 ──

async def _ensure_hwp_connection(doc_index: int | None = None):
    """HWP 연결 확인/자동 연결."""
    from engine.live_controller import _get_hwp_ctrl
    def _ensure():
        hwp_ctrl = _get_hwp_ctrl()
        if not hwp_ctrl.connected:
            hwp_ctrl.connect()
            if hwp_ctrl.connected:
                deps.get_live()._connections["hwp"] = True
        if doc_index is not None and hwp_ctrl.connected:
            hwp_ctrl.switch_document(doc_index)
    await deps.run_on_com(_ensure)


@router.post("/api/chat/live")
async def chat_live(req: LiveChatRequest):
    from engine.chat_handler import handle_live_chat

    if req.app_type == "hwp":
        await _ensure_hwp_connection(req.doc_index)

    live = deps.get_live()
    if req.app_type not in live._connections:
        await deps.run_on_com(live.connect, req.app_type)

    result = await deps.run_on_com(
        handle_live_chat,
        req.message, req.app_type, req.history, deps.llm_manager, live,
        req.preview, req.model, req.design_skill,
    )
    return result


@router.post("/api/live/execute-batch")
async def live_execute_batch(req: BatchExecuteRequest):
    live = deps.get_live()
    # PPT: add_slide를 먼저 실행
    actions_list = req.actions
    if req.app_type == "ppt":
        from engine.live_controller import LiveController
        actions_list = LiveController.reorder_ppt_actions(actions_list)
    elif req.app_type == "hwp":
        from engine.live_controller import LiveController
        actions_list = LiveController.reorder_hwp_block_actions(actions_list)
    results = []
    for act in actions_list:
        action_name = act.get("action", "")
        params = act.get("params", {})
        try:
            result = await deps.run_on_com(live.execute, req.app_type, action_name, params)
            results.append({"action": action_name, "success": result.success, "message": result.message})
        except Exception as e:
            results.append({"action": action_name, "success": False, "message": str(e)})
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    return {"results": results, "summary": f"{ok}개 성공" + (f", {fail}개 실패" if fail else "")}


# ── 스트리밍 라이브 제어 ──

@router.post("/api/chat/live/stream")
async def chat_live_stream(req: StreamChatRequest):
    import asyncio
    from engine.chat_handler import prepare_live_chat_messages, parse_actions_response

    if req.app_type == "hwp":
        await _ensure_hwp_connection(req.doc_index)

    live = deps.get_live()
    if req.app_type not in live._connections:
        await deps.run_on_com(live.connect, req.app_type)

    # 1단계: COM 스레드에서 메시지 준비 (문서 읽기 포함)
    messages, provider, model_name = await deps.run_on_com(
        prepare_live_chat_messages,
        req.message, req.app_type, req.history, live,
        req.model, req.design_skill,
    )

    async def stream():
        if not messages:
            yield f"data: {json.dumps({'type': 'reply', 'content': '스킬 없음'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'summary': '오류'}, ensure_ascii=False)}\n\n"
            return

        # 2단계: "생각 중" 알림
        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        # 3단계: LLM 스트리밍 — 동기 제너레이터를 async로 브릿지
        full_reply = ""
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _run_llm():
            try:
                for chunk in deps.llm_manager.generate_chat_stream(
                    messages, max_tokens=4096, temperature=0.1,
                    provider=provider, model=model_name,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, ("token", chunk))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
            loop.call_soon_threadsafe(q.put_nowait, ("end", None))

        loop.run_in_executor(None, _run_llm)

        while True:
            msg_type, data = await q.get()
            if msg_type == "end":
                break
            if msg_type == "error":
                yield f"data: {json.dumps({'type': 'reply', 'content': f'LLM 호출 실패: {data}'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'summary': '오류'}, ensure_ascii=False)}\n\n"
                return
            full_reply += data
            yield f"data: {json.dumps({'type': 'token', 'content': data}, ensure_ascii=False)}\n\n"

        # 4단계: 완성된 응답에서 액션 파싱
        import re
        friendly_reply = full_reply
        json_match = re.search(r"```(?:json)?\s*\n?", full_reply)
        if json_match:
            before = full_reply[:json_match.start()].strip()
            if before:
                friendly_reply = before

        yield f"data: {json.dumps({'type': 'reply_done', 'content': friendly_reply}, ensure_ascii=False)}\n\n"

        actions = parse_actions_response(full_reply)
        if not actions:
            yield f"data: {json.dumps({'type': 'done', 'summary': '실행할 작업 없음'}, ensure_ascii=False)}\n\n"
            return

        # PPT: add_slide 먼저 / HWP: block_id 역순 (좌표 밀림 방지)
        if req.app_type == "ppt":
            from engine.live_controller import LiveController
            actions = LiveController.reorder_ppt_actions(actions)
        elif req.app_type == "hwp":
            from engine.live_controller import LiveController
            actions = LiveController.reorder_hwp_block_actions(actions)

        yield f"data: {json.dumps({'type': 'actions', 'count': len(actions)}, ensure_ascii=False)}\n\n"

        # 5단계: 액션 실행 스트리밍
        ok, fail = 0, 0
        for i, act in enumerate(actions):
            action_name = act.get("action", "")
            params = act.get("params", {})
            try:
                r = await deps.run_on_com(live.execute, req.app_type, action_name, params)
                success, msg = r.success, r.message
            except Exception as e:
                success, msg = False, str(e)

            if success:
                ok += 1
            else:
                fail += 1
            yield f"data: {json.dumps({'type': 'result', 'index': i, 'action': action_name, 'success': success, 'message': msg}, ensure_ascii=False)}\n\n"

        summary = f"{ok}개 성공" + (f", {fail}개 실패" if fail else "")
        yield f"data: {json.dumps({'type': 'done', 'summary': summary}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
