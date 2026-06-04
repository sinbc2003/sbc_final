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


@router.get("/api/hwp/documents")
async def hwp_documents():
    result = await deps.run_on_com(deps.get_hwp().list_documents)
    return {"documents": result}


@router.post("/api/hwp/switch/{doc_index}")
async def hwp_switch(doc_index: int):
    return await deps.run_on_com(deps.get_hwp().switch_document, doc_index)
