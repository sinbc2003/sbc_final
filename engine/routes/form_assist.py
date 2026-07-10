"""공문 양식 채우기."""

from __future__ import annotations
import os
import asyncio
import concurrent.futures
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form as FormField
from engine import deps

router = APIRouter()


@router.post("/api/form-open-template")
async def form_assist_open_template(file: UploadFile = File(...)):
    upload_dir = deps.ROOT / "data" / "uploads"
    upload_dir.mkdir(exist_ok=True)
    dest = upload_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)

    ext = dest.suffix.lower()
    if ext not in (".hwp", ".hwpx"):
        return {"ok": True, "message": "HWP 파일만 미리 열기 지원"}

    def _open_hwp():
        import pythoncom
        pythoncom.CoInitialize()
        from pyhwpx import Hwp
        hwp = Hwp(visible=True)
        hwp.Open(str(dest.resolve()))

    await deps.run_on_com(_open_hwp)
    return {"ok": True, "path": str(dest)}


@router.post("/api/form-assist")
async def form_assist(
    files: list[UploadFile] = File(default=[]),
    instruction: str = FormField(default=""),
    output_idx: int = FormField(default=-1),
    page_range: str = FormField(default=""),
    provider: str = FormField(default="auto"),
    model: str = FormField(default=""),
):
    from engine.form_assist import run_form_assist, scan_hwp_structure, fill_hwp_by_cells

    upload_dir = deps.ROOT / "data" / "uploads"
    upload_dir.mkdir(exist_ok=True)
    file_infos = []
    for uf in files:
        dest = upload_dir / uf.filename
        content = await uf.read()
        if not dest.exists():
            dest.write_bytes(content)
        file_infos.append({"path": str(dest), "name": uf.filename})

    logs = []
    def log_cb(msg): logs.append(msg)

    out_dir = deps.settings_mgr.get("general", "output_dir", "")

    hwp_elements = None
    template_path = None
    if 0 <= output_idx < len(file_infos):
        tp = file_infos[output_idx]["path"]
        # .hwpx는 그리드(COM-free)로 run_form_assist가 직접 채운다 → COM 스캔은 레거시 .hwp만.
        if Path(tp).suffix.lower() == ".hwp":
            template_path = tp
            hwp_elements = await deps.run_on_com(lambda: scan_hwp_structure(tp, log_cb))

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool, lambda: run_form_assist(
                files=file_infos, instruction=instruction, output_file_idx=output_idx,
                page_range=page_range, llm_provider=provider, llm_model=model,
                log_cb=log_cb, output_dir=out_dir, hwp_elements=hwp_elements,
            )
        )

    fill_data = result.get("fill_data")
    if not template_path:
        template_path = result.get("template_path")
    save_dir = result.get("save_dir", out_dir)
    if fill_data and template_path and hwp_elements:
        output_file = await deps.run_on_com(lambda: fill_hwp_by_cells(template_path, fill_data, hwp_elements, log_cb, output_dir=save_dir))
        result["file"] = output_file
        if output_file:
            logs.append(f"완성 파일: {output_file}")

    output_file = result.get("file")
    if output_file and os.path.exists(output_file):
        if Path(output_file).suffix.lower() not in (".hwp", ".hwpx"):
            try:
                os.startfile(output_file)
            except Exception:
                pass

    return {"text": result.get("text", ""), "file": output_file, "logs": logs}
