"""파일 업로드, 다운로드, 열기."""

from __future__ import annotations
import re
import uuid
import subprocess
import platform
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from engine import deps

router = APIRouter()


@router.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)):
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', file.filename or "upload")
    target = deps.UPLOADS_DIR / safe_name
    if target.exists():
        stem, ext = target.stem, target.suffix
        target = deps.UPLOADS_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    content = await file.read()
    target.write_bytes(content)
    return {"path": str(target), "name": target.name, "size": len(content), "relative": f"data/uploads/{target.name}"}


@router.get("/api/files/list")
async def list_files():
    files = []
    for f in sorted(deps.UPLOADS_DIR.iterdir()):
        if f.is_file():
            files.append({"name": f.name, "path": str(f), "size": f.stat().st_size, "ext": f.suffix.lower()})
    return files


@router.get("/api/files/download/{filename}")
async def download_file(filename: str, dir: str = ""):
    target = Path(dir) / filename if dir else deps.UPLOADS_DIR / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "파일 없음")
    return FileResponse(target, filename=filename)


@router.get("/api/files/download-path")
async def download_file_by_path(path: str):
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"파일 없음: {path}")
    return FileResponse(target, filename=target.name)


@router.post("/api/files/open")
async def open_file(body: dict[str, Any]):
    import os
    file_path = body.get("path", "")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(404, f"파일 없음: {file_path}")
    try:
        if platform.system() == "Windows":
            os.startfile(file_path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
        return {"opened": file_path}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/files/open-folder")
async def open_folder(body: dict[str, Any]):
    file_path = body.get("path", "")
    p = Path(file_path)
    folder = str(p.parent) if p.is_file() else str(p)
    if not Path(folder).exists():
        raise HTTPException(404, f"폴더 없음: {folder}")
    try:
        if platform.system() == "Windows":
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                subprocess.Popen(["explorer", folder])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return {"opened": folder}
    except Exception as e:
        raise HTTPException(500, str(e))
