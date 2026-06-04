"""설정, 노드 마켓플레이스."""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException
from engine import deps

router = APIRouter()


@router.get("/api/settings")
async def get_settings():
    return deps.settings_mgr.get_all()


@router.put("/api/settings/{section}")
async def update_settings(section: str, values: dict[str, Any]):
    try:
        result = deps.settings_mgr.update(section, values)
        if section in ("api_keys", "llm"):
            deps.reinit_llm()
        return result
    except KeyError as e:
        raise HTTPException(400, str(e))


@router.get("/api/nodes/check-updates")
async def check_node_updates():
    return deps.marketplace.check_updates()


@router.post("/api/nodes/install/{node_id}")
async def install_node(node_id: str):
    result = deps.marketplace.install_node(node_id)
    if result["success"]:
        deps.registry.load_all(deps.ROOT / "nodes")
    return result


@router.delete("/api/nodes/{node_id}")
async def uninstall_node(node_id: str):
    result = deps.marketplace.uninstall_node(node_id)
    if result["success"]:
        deps.registry.load_all(deps.ROOT / "nodes")
    return result
