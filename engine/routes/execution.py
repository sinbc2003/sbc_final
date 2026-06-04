"""워크플로우 실행 (단발 + 스트리밍)."""

from __future__ import annotations
import json
import time
import uuid
import asyncio
import threading
import queue as thread_queue
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from engine import deps
from engine.runner import PipelineRunner, Workflow
from engine.storage import ExecutionRecord

router = APIRouter()


class RunRequest(BaseModel):
    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    created_at: str = ""
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    user_inputs: list[dict[str, Any]] = []
    initial_inputs: dict[str, dict[str, Any]] = {}


def _normalize_edges(edges: list[dict]) -> list[dict]:
    result = []
    for e in edges:
        if "from" in e:
            result.append(e)
        elif "source" in e:
            result.append({
                "from": e["source"], "from_port": e.get("sourceHandle", ""),
                "to": e["target"], "to_port": e.get("targetHandle", ""),
            })
        else:
            result.append(e)
    return result


@router.post("/api/run")
async def run_workflow(req: RunRequest):
    started = datetime.now().isoformat(timespec="seconds")
    try:
        wf_data = {
            "id": req.id, "name": req.name, "version": req.version,
            "description": req.description,
            "nodes": req.nodes, "edges": _normalize_edges(req.edges), "user_inputs": req.user_inputs,
        }
        workflow = Workflow.from_json(wf_data)
        run_config = {"output_dir": deps.settings_mgr.get("general.output_dir", "")}
        runner = PipelineRunner(registry=deps.registry, llm_manager=deps.llm_manager, config=run_config)
        result = runner.run(workflow, req.initial_inputs or None)

        record = ExecutionRecord(
            id=f"run_{int(time.time())}_{uuid.uuid4().hex[:4]}",
            workflow_id=req.id or "unnamed", workflow_name=req.name or "이름 없음",
            started_at=started, finished_at=datetime.now().isoformat(timespec="seconds"),
            success=result.success, elapsed_seconds=round(result.elapsed_seconds, 2),
            errors=result.errors, node_timings=result.node_timings,
        )
        deps.store.add_history(record)

        output_files = []
        for nid, outputs in result.outputs.items():
            for port, val in outputs.items():
                if isinstance(val, str) and Path(val).is_file():
                    output_files.append({"name": Path(val).name, "path": str(val), "size": Path(val).stat().st_size, "ext": Path(val).suffix.lower()})

        if result.success and output_files:
            import os, platform as _pf
            for f in output_files:
                try:
                    if _pf.system() == "Windows":
                        os.startfile(f["path"])
                    elif _pf.system() == "Darwin":
                        import subprocess; subprocess.Popen(["open", f["path"]])
                except Exception:
                    pass

        return {
            "success": result.success, "errors": result.errors,
            "elapsed_seconds": result.elapsed_seconds, "node_timings": result.node_timings,
            "history_id": record.id, "output_files": output_files,
            "outputs": {nid: {port: str(val)[:1000] for port, val in outputs.items()} for nid, outputs in result.outputs.items()},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/run-stream")
async def run_workflow_stream(req: RunRequest):
    started = datetime.now().isoformat(timespec="seconds")
    q: thread_queue.Queue = thread_queue.Queue()

    node_name_map = {}
    for n in req.nodes:
        nd = deps.registry.get(n["type"])
        node_name_map[n["id"]] = nd.name if nd else n["type"]

    def on_progress(node_id, value):
        q.put({"event": "node_progress", "node_id": node_id, "node_name": node_name_map.get(node_id, node_id), "progress": value})

    def on_log(node_id, message):
        q.put({"event": "node_log", "node_id": node_id, "node_name": node_name_map.get(node_id, node_id), "message": message})

    def run_in_thread():
        try:
            wf_data = {
                "id": req.id, "name": req.name, "version": req.version, "description": req.description,
                "nodes": req.nodes, "edges": _normalize_edges(req.edges), "user_inputs": req.user_inputs,
            }
            workflow = Workflow.from_json(wf_data)
            runner = PipelineRunner(
                registry=deps.registry, llm_manager=deps.llm_manager,
                config={"output_dir": deps.settings_mgr.get("general.output_dir", "")},
                on_progress=on_progress, on_log=on_log,
            )
            result = runner.run(workflow, req.initial_inputs or None)
            record = ExecutionRecord(
                id=f"run_{int(time.time())}_{uuid.uuid4().hex[:4]}",
                workflow_id=req.id or "unnamed", workflow_name=req.name or "이름 없음",
                started_at=started, finished_at=datetime.now().isoformat(timespec="seconds"),
                success=result.success, elapsed_seconds=round(result.elapsed_seconds, 2),
                errors=result.errors, node_timings=result.node_timings,
            )
            deps.store.add_history(record)
            q.put({"event": "done", "success": result.success, "errors": result.errors,
                   "elapsed_seconds": result.elapsed_seconds, "node_timings": result.node_timings,
                   "history_id": record.id,
                   "outputs": {nid: {port: str(val)[:1000] for port, val in outputs.items()} for nid, outputs in result.outputs.items()}})
        except Exception as e:
            q.put({"event": "error", "message": str(e)})

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def event_stream():
        while True:
            try:
                item = q.get(timeout=0.1)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item["event"] in ("done", "error"):
                    break
            except thread_queue.Empty:
                await asyncio.sleep(0.05)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
