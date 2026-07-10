"""HWP 전용 API — pyhwpx / blockId 기반."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from engine import deps

router = APIRouter()


@router.post("/api/hwp/connect")
async def hwp_connect():
    result = await deps.run_on_com(deps.get_hwp().connect)
    return result


@router.get("/api/hwp/info")
async def hwp_info():
    return await deps.run_on_com(deps.get_hwp().get_document_info)


@router.get("/api/hwp/cvd")
async def hwp_cvd(mode: str = "auto"):
    """문서 CVD 추출. mode: auto(HWPML우선) | hwpml | cursor"""
    def _do_cvd():
        import traceback as _tb
        ctrl = deps.get_hwp()
        if ctrl._hwp and ctrl._connected:
            try:
                ctrl._hwp.get_pos()
            except Exception:
                import pythoncom
                pythoncom.CoInitialize()
                hwp = deps.create_fresh_hwp()
                ctrl._hwp = hwp
                ctrl._connected = True
        else:
            import pythoncom
            pythoncom.CoInitialize()
            hwp = deps.create_fresh_hwp()
            ctrl._hwp = hwp
            ctrl._connected = True

        from engine.hwp_controller import DocumentScanner, BlockManager, HwpEditor

        # HWPML 모드 시도
        scan_mode = "cursor"
        hwp = ctrl._hwp
        scanner = DocumentScanner(hwp)

        try:
            from engine.hwpml import parse_hwpml2x, PositionEngine, build_cvd as _build_cvd
            _hwpml_ok = True
        except ImportError:
            _hwpml_ok = False

        if mode in ("auto", "hwpml") and _hwpml_ok:
            hwpml_result = scanner.scan_hwpml()
            if hwpml_result:
                blocks = hwpml_result["blocks"]
                id_to_pos = hwpml_result["id_to_pos"]
                style_lookup = hwpml_result["style_lookup"]
                bm = BlockManager()
                bm.initialize_from_blocks(blocks, id_to_pos)
                file_name = ""
                try:
                    file_name = hwp.FileName or ""
                except Exception:
                    pass
                cvd_text = _build_cvd(
                    blocks=blocks, id_to_pos=id_to_pos,
                    style_lookup=style_lookup, file_name=file_name,
                )
                ctrl._scanner = scanner
                ctrl._block_manager = bm
                ctrl._editor = HwpEditor(hwp, bm)
                return {
                    "cvd": cvd_text, "blocks": blocks,
                    "block_count": len(blocks), "scan_mode": "hwpml",
                }

            if mode == "hwpml":
                return {"error": "HWPML scan failed", "scan_mode": "hwpml"}

        # 커서 폴백
        bm = BlockManager()
        elements = scanner.scan()
        bm.initialize_from_scan(elements)
        ctrl._scanner = scanner
        ctrl._block_manager = bm
        ctrl._editor = HwpEditor(hwp, bm)
        return {
            "cvd": bm.to_cvd_text(), "blocks": elements,
            "block_count": len(elements), "scan_mode": "cursor",
        }
    return await deps.run_on_com(_do_cvd)


@router.get("/api/hwp/scan-debug")
async def hwp_scan_debug():
    def _do():
        import pythoncom, time
        pythoncom.CoInitialize()
        hwp = deps.create_fresh_hwp()
        hwp.MoveDocBegin()
        hwp.init_scan(option=4, range=0x0077)
        elements = []
        start = time.monotonic()
        for i in range(500):
            if time.monotonic() - start > 10:
                break
            state, text = hwp.get_text()
            if state == 0:
                break
            if state == 1:
                continue
            hwp.move_pos(201)
            pos = hwp.get_pos()
            t = (text or "").replace("\r\n", "").strip()
            elements.append({"id": str(i), "type": "td" if pos[0] > 0 else "text", "pos": list(pos), "text": t[:80]})
        hwp.release_scan()
        return {"count": len(elements), "elements": elements[:30], "elapsed": round(time.monotonic() - start, 2)}
    return await deps.run_on_com(_do)


@router.get("/api/hwp/tables")
async def hwp_tables():
    return await deps.run_on_com(deps.get_hwp().scan_tables)


class HwpExecRequest(BaseModel):
    operation: str
    params: dict = {}

@router.post("/api/hwp/execute")
async def hwp_execute(req: HwpExecRequest):
    hwp = deps.get_hwp()
    def _run():
        return hwp.execute(req.operation, **req.params)
    return await deps.run_on_com(_run)


@router.get("/api/hwp/actions")
async def hwp_actions():
    from engine.hwp_controller import HWP_ACTIONS_SCHEMA
    return HWP_ACTIONS_SCHEMA


class FillLiveRequest(BaseModel):
    instruction: str
    path: str = ""        # 비우면 한/글 활성 문서 사용 (.hwpx만 지원)
    context: str = ""     # 참고 텍스트 (선택)
    provider: str = "local"
    model: str = ""
    scan_timeout: int = 30  # 초 (5~120) — 단일 COM 스레드 점유 상한


@router.post("/api/hwp/fill-live")
async def hwp_fill_live(req: FillLiveRequest):
    """gemma 실시간 문서 채우기 — 열린 한/글 문서에 캐럿으로 라이브 기록.

    흐름: [COM] 문서 확보+InitScan → [스레드풀] gemma 배치 결정(라벨그리드+enum)
    → [COM] 그리드↔스캔 정렬(텍스트 검산)→set_pos 라이브 기록→'_완성' 저장.
    """
    import asyncio, concurrent.futures
    from pathlib import Path as _P

    logs: list[str] = []
    log = logs.append

    # ── 1a) COM(짧게): 대상 문서 경로만 확보 — 스캔 전에 확장자 검증 ──
    def _resolve_path():
        import pythoncom
        pythoncom.CoInitialize()
        if req.path:
            return req.path
        from pyhwpx import Hwp
        hwp = Hwp(visible=True)
        try:
            return hwp.XHwpDocuments.Active_XHwpDocument.FullName or ""
        except Exception:
            return ""

    path = await deps.run_on_com(_resolve_path)
    if not path:
        return {"ok": False, "error": "대상 문서 없음 — 한/글에서 문서를 열거나 path를 지정하세요", "logs": logs}
    if _P(path).suffix.lower() != ".hwpx":
        return {"ok": False, "error": f"라이브 채우기는 .hwpx만 지원 (.hwp는 form-assist 사용): {_P(path).name}", "logs": logs}

    # ── 1b) COM: 스캔 (단일 COM 스레드 점유를 제한 — 기본 30초) ──
    def _scan():
        from engine.form_assist import scan_hwp_structure
        return scan_hwp_structure(path, log, timeout=min(max(req.scan_timeout, 5), 120))

    elements = await deps.run_on_com(_scan)
    if not elements:
        return {"ok": False, "error": "문서 스캔 실패", "logs": logs}

    # ── 2) 스레드풀: gemma 배치 결정 (COM 무관) ──
    from engine.form_assist import plan_hwpx_grid_fill
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        plan = await loop.run_in_executor(
            pool, lambda: plan_hwpx_grid_fill(
                path, instruction=req.instruction, context_text=req.context,
                llm_provider=req.provider, llm_model=req.model, log=log,
            )
        )
    fill_data = plan.get("fill_data") or {}
    if not fill_data:
        return {"ok": False, "error": "채울 항목 없음 (빈칸 미검출 또는 LLM 미결정)", "logs": logs}

    # ── 3) COM: 정렬 + 라이브 기록 + 저장 ──
    out_dir = deps.settings_mgr.get("general", "output_dir", "")
    from engine.hwp.grid_live import fill_grid_live
    result = await deps.run_on_com(
        lambda: fill_grid_live(path, fill_data, elements, log=log, output_dir=out_dir)
    )
    return {
        "ok": result["filled"] > 0,
        "file": result["output"],
        "filled": result["filled"],
        "skipped": result["skipped"],
        "align_stats": result["stats"],
        "plan": fill_data,
        "logs": logs,
    }


@router.get("/api/hwp/documents")
async def hwp_documents():
    result = await deps.run_on_com(deps.get_hwp().list_documents)
    return {"documents": result}


@router.post("/api/hwp/switch/{doc_index}")
async def hwp_switch(doc_index: int):
    return await deps.run_on_com(deps.get_hwp().switch_document, doc_index)
