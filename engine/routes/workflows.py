"""워크플로우 CRUD, 자동저장, 히스토리, 프리셋."""

from __future__ import annotations
import json as _json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from engine import deps

router = APIRouter()


class SaveWorkflowRequest(BaseModel):
    workflow: dict[str, Any]
    workflow_id: str | None = None

class RenameRequest(BaseModel):
    name: str
    description: str = ""

class TagsRequest(BaseModel):
    tags: list[str]


# ── CRUD ──

@router.get("/api/workflows")
async def list_workflows():
    return [m.__dict__ for m in deps.store.list_workflows()]

@router.post("/api/workflows")
async def save_workflow(req: SaveWorkflowRequest):
    meta = deps.store.save_workflow(req.workflow, req.workflow_id)
    return meta.__dict__

@router.get("/api/workflows/{wf_id}")
async def load_workflow(wf_id: str):
    data = deps.store.load_workflow(wf_id)
    if not data:
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return data

@router.delete("/api/workflows/{wf_id}")
async def delete_workflow(wf_id: str):
    if not deps.store.delete_workflow(wf_id):
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return {"deleted": wf_id}

@router.post("/api/workflows/{wf_id}/duplicate")
async def duplicate_workflow(wf_id: str):
    meta = deps.store.duplicate_workflow(wf_id)
    if not meta:
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return meta.__dict__

@router.put("/api/workflows/{wf_id}/rename")
async def rename_workflow(wf_id: str, req: RenameRequest):
    meta = deps.store.rename_workflow(wf_id, req.name, req.description)
    if not meta:
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return meta.__dict__

@router.put("/api/workflows/{wf_id}/tags")
async def update_tags(wf_id: str, req: TagsRequest):
    meta = deps.store.update_tags(wf_id, req.tags)
    if not meta:
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return meta.__dict__

@router.post("/api/workflows/{wf_id}/preset")
async def save_as_preset(wf_id: str):
    if not deps.store.save_as_preset(wf_id):
        raise HTTPException(404, f"워크플로우 '{wf_id}' 없음")
    return {"preset": wf_id}


# ── 자동저장 ──

@router.post("/api/autosave")
async def autosave(req: SaveWorkflowRequest):
    path = deps.store.autosave(req.workflow)
    return {"saved": path}

@router.get("/api/autosave")
async def load_autosave():
    data = deps.store.load_autosave()
    return {"data": data} if data else {"data": None}

@router.get("/api/autosaves")
async def list_autosaves():
    return deps.store.list_autosaves()


# ── 히스토리 ──

@router.get("/api/history")
async def list_history(limit: int = 30):
    return deps.store.list_history(limit)

@router.get("/api/history/{record_id}")
async def get_history(record_id: str):
    rec = deps.store.get_history(record_id)
    if not rec:
        raise HTTPException(404, f"기록 '{record_id}' 없음")
    return rec

@router.delete("/api/history")
async def clear_history():
    deps.store.clear_history()
    return {"cleared": True}


# ── 프리셋 ──

@router.get("/api/presets")
async def list_presets():
    return [m.__dict__ for m in deps.store.list_presets()]

@router.get("/api/presets/{preset_id}")
async def get_preset(preset_id: str):
    path = deps.store._presets_dir / f"{preset_id}.json"
    if not path.exists():
        raise HTTPException(404, f"프리셋 '{preset_id}' 없음")
    return _json.loads(path.read_text(encoding="utf-8"))


# ── 통계 ──

@router.get("/api/stats")
async def stats():
    return deps.store.get_stats()
