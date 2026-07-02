"""라이브 문서 제어 — 감지, 연결, 읽기, 실행, 스킬."""

from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from engine import deps

router = APIRouter()


@router.get("/api/live/detect")
async def live_detect():
    import asyncio

    running = set()
    for exe, key in [("Hwp.exe", "hwp"), ("EXCEL.EXE", "excel"), ("POWERPNT.EXE", "ppt"), ("WINWORD.EXE", "word")]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            output = stdout.decode("utf-8", errors="ignore").lower()
            if exe.lower().split(".")[0] in output:
                running.add(key)
        except Exception:
            pass

    live = deps.get_live()
    from engine.live_controller import _get_hwp_ctrl
    hwp_ctrl = _get_hwp_ctrl()

    # 프로세스 없으면 죽은 연결 정리 (COM 스레드에서 실행)
    dead_keys = [k for k in list(live._connections.keys()) if k not in running]
    if dead_keys:
        def _cleanup():
            for k in dead_keys:
                live._connections.pop(k, None)
        await deps.run_on_com(_cleanup)

    result = {}
    for key, name in [("hwp", "한/글"), ("excel", "Excel"), ("ppt", "PowerPoint"), ("word", "Word")]:
        connected = hwp_ctrl.connected if key == "hwp" else key in live._connections
        doc_name = ""
        if key in running:
            doc_name = "연결됨" if connected else "(실행 중)"
        result[key] = {"name": name, "connected": connected, "doc_name": doc_name, "doc_path": ""}

    if result["hwp"]["connected"]:
        try:
            docs = await deps.run_on_com(hwp_ctrl.list_documents)
            result["hwp"]["documents"] = docs
        except Exception:
            result["hwp"]["documents"] = []

    # Excel/PPT/Word 문서 목록도 포함
    for key in ("excel", "ppt", "word"):
        if result[key]["connected"]:
            try:
                docs = await deps.run_on_com(live.list_documents, key)
                result[key]["documents"] = docs
            except Exception:
                # COM 일시적 오류 — 연결은 유지, 문서 목록만 비움
                result[key]["documents"] = []

    return result


@router.post("/api/live/connect/{app_type}")
async def live_connect(app_type: str):
    result = await deps.run_on_com(deps.get_live().connect, app_type)
    return {"success": result.success, "message": result.message}


@router.get("/api/live/documents/{app_type}")
async def live_documents(app_type: str):
    """연결된 앱의 열린 문서 목록."""
    if app_type == "hwp":
        from engine.live_controller import _get_hwp_ctrl
        docs = await deps.run_on_com(_get_hwp_ctrl().list_documents)
    else:
        docs = await deps.run_on_com(deps.get_live().list_documents, app_type)
    return {"documents": docs}


class ActivateDocRequest(BaseModel):
    index: int

@router.post("/api/live/documents/{app_type}/activate")
async def live_activate_document(app_type: str, req: ActivateDocRequest):
    """열린 문서 중 하나를 활성화."""
    if app_type == "hwp":
        from engine.live_controller import _get_hwp_ctrl
        hwp_ctrl = _get_hwp_ctrl()
        result = await deps.run_on_com(hwp_ctrl.switch_document, req.index)
        return {"success": True, "message": f"문서 전환: {req.index}"}
    else:
        result = await deps.run_on_com(deps.get_live().activate_document, app_type, req.index)
        return {"success": result.success, "message": result.message}


@router.get("/api/live/read/{app_type}")
async def live_read(app_type: str):
    if app_type == "hwp":
        def _read_hwp():
            ctrl = deps.get_hwp()
            if not ctrl._hwp or not ctrl._connected:
                import pythoncom
                pythoncom.CoInitialize()
                from pyhwpx import Hwp
                hwp = Hwp(visible=True)
                ctrl._hwp = hwp
                ctrl._connected = True
            return ctrl.read_text()
        content = await deps.run_on_com(_read_hwp)
    else:
        content = await deps.run_on_com(deps.get_live().read, app_type)
    return {"app": app_type, "content": content}


class LiveExecRequest(BaseModel):
    action: str
    params: dict = {}

@router.post("/api/live/execute/{app_type}")
async def live_execute(app_type: str, req: LiveExecRequest):
    result = await deps.run_on_com(deps.get_live().execute, app_type, req.action, req.params)
    return {"success": result.success, "message": result.message, "data": result.data}


@router.get("/api/live/actions")
async def live_actions():
    from engine.live_controller import ACTIONS_SCHEMA
    return ACTIONS_SCHEMA


@router.get("/api/live/skill/{app_type}")
async def live_skill(app_type: str):
    skill_path = deps.ROOT / "engine" / "skills" / f"{app_type}.md"
    if not skill_path.exists():
        raise HTTPException(404, f"스킬 없음: {app_type}")
    template = skill_path.read_text(encoding="utf-8")

    if app_type == "hwp":
        def _hwp_read_and_scan():
            import pythoncom
            pythoncom.CoInitialize()
            hwp = deps.create_fresh_hwp()
            ctrl = deps.get_hwp()

            # 페이지 설정 정보 수집
            page_info = ""
            try:
                pd = hwp.get_pagedef_as_dict("eng")
                paper_w = pd.get("PaperWidth", 210)
                paper_h = pd.get("PaperHeight", 297)
                left_m = pd.get("LeftMargin", 30)
                right_m = pd.get("RightMargin", 30)
                top_m = pd.get("TopMargin", 25)
                bottom_m = pd.get("BottomMargin", 25)
                gutter = pd.get("GutterLen", 0)
                usable_w = round(paper_w - left_m - right_m - gutter, 1)
                page_info = (
                    f"[용지] {paper_w}x{paper_h}mm, "
                    f"여백 좌{left_m} 우{right_m} 상{top_m} 하{bottom_m}mm, "
                    f"가용폭 {usable_w}mm"
                )
            except Exception:
                page_info = "[용지] 정보 없음 (기본 A4 가정: 가용폭 약150mm)"

            parts = []
            hwp.MoveDocBegin()
            hwp.init_scan(option=4, range=0x0077)
            for _ in range(10000):
                state, text = hwp.get_text()
                if state == 0: break
                if state == 1: continue
                if text and text.strip():
                    parts.append(text.strip())
            hwp.release_scan()
            doc_text = page_info + "\n\n" + "\n".join(parts)
            from engine.hwp_controller import DocumentScanner, BlockManager, HwpEditor
            import logging
            _logger = logging.getLogger("live")

            # HwpController 싱글턴에 연결 공유 → extract_cvd가 이 연결을 재사용,
            # 이후 편집(execute)도 같은 상태 사용. scanner/editor는 현재 hwp로 재바인딩.
            ctrl._hwp = hwp
            ctrl._connected = True
            ctrl._scanner = DocumentScanner(hwp)
            ctrl._editor = HwpEditor(hwp, ctrl._block_manager)

            # CVD 스캔 — HWPML 우선(병합/스타일 보존), 실패 시 커서 스캔 폴백.
            # extract_cvd(mode="auto")가 내부에서 BlockManager 초기화까지 수행.
            cvd_text = ""
            try:
                result = ctrl.extract_cvd(mode="auto")
                if result.get("cvd") and not result.get("error"):
                    cvd_text = result["cvd"]
                else:
                    _logger.warning(f"live_skill: extract_cvd 결과 없음 — 커서 스캔 폴백: {result.get('error')}")
            except Exception as e_cvd:
                _logger.warning(f"live_skill: extract_cvd 예외 — 커서 스캔 폴백: {e_cvd}")
            if not cvd_text:
                # 폴백: 기존 커서 스캔 경로 (BlockManager 상태도 함께 갱신)
                scanner = DocumentScanner(hwp)
                elements = scanner.scan()
                bm = BlockManager()
                bm.initialize_from_scan(elements)
                cvd_text = bm.to_cvd_text()
                ctrl._scanner = scanner
                ctrl._block_manager = bm
                ctrl._editor = HwpEditor(hwp, bm)
            if cvd_text:
                doc_text += f"\n\n=== 블록 ID 매핑 (block_id 기반 편집용) ===\n{cvd_text}"
            return doc_text
        try:
            content = await deps.run_on_com(_hwp_read_and_scan)
        except Exception as e:
            content = f"[HWP 읽기/스캔 오류] {e}"
    else:
        content = await deps.run_on_com(deps.get_live().read, app_type)

    prompt = template.replace("{document_content}", content)
    return {"app": app_type, "skill": prompt}
