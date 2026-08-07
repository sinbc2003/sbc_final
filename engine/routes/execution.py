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
from engine.storage import ExecutionRecord, timings_to_list

router = APIRouter()


# ── 실행 레지스트리 (취소용) ───────────────────────────────
# run_id → threading.Event. 실행 시작 시 등록, 종료 시 반드시 해제.
_ACTIVE_RUNS: dict[str, threading.Event] = {}
_RUNS_LOCK = threading.Lock()


def _register_run() -> tuple[str, threading.Event]:
    run_id = f"exec_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    ev = threading.Event()
    with _RUNS_LOCK:
        _ACTIVE_RUNS[run_id] = ev
    return run_id, ev


def _unregister_run(run_id: str) -> None:
    with _RUNS_LOCK:
        _ACTIVE_RUNS.pop(run_id, None)


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


# 출력 텍스트 전송 한도. SSE로 한 번 보내는 값이라 1000자는 지나치게 짧았다 —
# 1000자 넘는 공문 초안을 복사하면 문장 중간에서 잘린 텍스트를 받으면서도
# 어디에도 잘렸다는 표시가 없었다. 넉넉히 올리고, 그래도 넘으면 알린다.
OUTPUT_TEXT_LIMIT = 20000


def _pack_outputs(result) -> tuple[dict, bool]:
    """노드 출력을 전송용으로 직렬화. (packed, 절단 발생 여부)"""
    truncated = False
    packed: dict[str, dict[str, str]] = {}
    for nid, outputs in result.outputs.items():
        packed[nid] = {}
        for port, val in outputs.items():
            s = str(val)
            if len(s) > OUTPUT_TEXT_LIMIT:
                s = s[:OUTPUT_TEXT_LIMIT]
                truncated = True
            packed[nid][port] = s
    return packed, truncated


def _node_name_map(req: "RunRequest") -> dict[str, str]:
    """node_id → 사람이 읽는 노드 이름 (이력 표시용)."""
    names = {}
    for n in req.nodes:
        nd = deps.registry.get(n.get("type", ""))
        names[n.get("id", "")] = nd.name if nd else n.get("type", "")
    return names


def _snapshot(req: "RunRequest", wf_data: dict) -> dict:
    """이력에서 그대로 다시 실행할 수 있는 최소 스냅샷."""
    return {
        "id": req.id, "name": req.name, "version": req.version,
        "description": req.description,
        "nodes": wf_data["nodes"], "edges": wf_data["edges"],
        "user_inputs": req.user_inputs, "initial_inputs": req.initial_inputs or {},
    }


def _collect_output_files(result) -> list[dict]:
    """실행 결과 중 실제 파일 경로인 출력만 추려 메타 반환 (양 경로 공용)."""
    files = []
    for outputs in result.outputs.values():
        for val in outputs.values():
            try:
                if isinstance(val, str) and Path(val).is_file():
                    p = Path(val)
                    files.append({"name": p.name, "path": str(p),
                                  "size": p.stat().st_size, "ext": p.suffix.lower()})
            except (OSError, ValueError):
                continue
    return files


@router.post("/api/run/{run_id}/cancel")
async def cancel_run(run_id: str):
    """실행 중단 요청 — 러너가 다음 노드 경계에서 멈춘다(협조적 취소)."""
    with _RUNS_LOCK:
        ev = _ACTIVE_RUNS.get(run_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="이미 끝났거나 없는 실행입니다")
    ev.set()
    return {"ok": True, "run_id": run_id}


@router.get("/api/runs")
async def list_runs():
    """진행 중인 실행 목록 (디버그·복구용)."""
    with _RUNS_LOCK:
        return {"running": list(_ACTIVE_RUNS.keys())}


@router.post("/api/run")
async def run_workflow(req: RunRequest):
    started = datetime.now().isoformat(timespec="seconds")
    run_id, cancel_ev = _register_run()
    try:
        wf_data = {
            "id": req.id, "name": req.name, "version": req.version,
            "description": req.description,
            "nodes": req.nodes, "edges": _normalize_edges(req.edges), "user_inputs": req.user_inputs,
        }
        workflow = Workflow.from_json(wf_data)
        run_config = {"output_dir": deps.settings_mgr.get("general.output_dir", ""),
                      "school_name": deps.settings_mgr.get("general.school_name", "")}
        runner = PipelineRunner(registry=deps.registry, llm_manager=deps.llm_manager,
                                config=run_config, cancel_event=cancel_ev)
        # 동기 runner.run을 스레드로 — 이벤트 루프 블로킹 방지(실행 중 서버 정지 해소).
        result = await asyncio.to_thread(runner.run, workflow, req.initial_inputs or None)

        output_files = _collect_output_files(result)
        packed, truncated = _pack_outputs(result)
        record = ExecutionRecord(
            id=f"run_{int(time.time())}_{uuid.uuid4().hex[:4]}",
            workflow_id=req.id or "unnamed", workflow_name=req.name or "이름 없음",
            started_at=started, finished_at=datetime.now().isoformat(timespec="seconds"),
            success=result.success, elapsed_seconds=round(result.elapsed_seconds, 2),
            errors=result.errors,
            node_timings=timings_to_list(result.node_timings, _node_name_map(req)),
            cancelled=result.cancelled,
            outputs=packed, output_files=output_files,
            workflow_snapshot=_snapshot(req, wf_data),
        )
        deps.store.add_history(record)

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
            "history_id": record.id, "output_files": output_files, "run_id": run_id,
            "cancelled": result.cancelled,
            "outputs": packed, "outputs_truncated": truncated,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _unregister_run(run_id)


@router.post("/api/run-stream")
async def run_workflow_stream(req: RunRequest):
    started = datetime.now().isoformat(timespec="seconds")
    q: thread_queue.Queue = thread_queue.Queue()
    run_id, cancel_ev = _register_run()
    # 첫 이벤트로 run_id를 내려보내 클라이언트가 중단 요청을 걸 수 있게 한다.
    q.put({"event": "run_started", "run_id": run_id})

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
                config={"output_dir": deps.settings_mgr.get("general.output_dir", ""),
                        "school_name": deps.settings_mgr.get("general.school_name", "")},
                on_progress=on_progress, on_log=on_log, cancel_event=cancel_ev,
            )
            result = runner.run(workflow, req.initial_inputs or None)
            output_files = _collect_output_files(result)
            packed, truncated = _pack_outputs(result)
            record = ExecutionRecord(
                id=f"run_{int(time.time())}_{uuid.uuid4().hex[:4]}",
                workflow_id=req.id or "unnamed", workflow_name=req.name or "이름 없음",
                started_at=started, finished_at=datetime.now().isoformat(timespec="seconds"),
                success=result.success, elapsed_seconds=round(result.elapsed_seconds, 2),
                errors=result.errors,
                node_timings=timings_to_list(result.node_timings, node_name_map),
                cancelled=result.cancelled,
                outputs=packed, output_files=output_files,
                workflow_snapshot=_snapshot(req, wf_data),
            )
            deps.store.add_history(record)
            if result.success and output_files:
                import os as _os, platform as _pf
                for f in output_files:
                    try:
                        if _pf.system() == "Windows":
                            _os.startfile(f["path"])
                        elif _pf.system() == "Darwin":
                            import subprocess as _sp; _sp.Popen(["open", f["path"]])
                    except Exception:
                        pass
            packed, truncated = _pack_outputs(result)
            q.put({"event": "done", "success": result.success, "errors": result.errors,
                   "elapsed_seconds": result.elapsed_seconds, "node_timings": result.node_timings,
                   "history_id": record.id, "output_files": output_files,
                   "run_id": run_id, "cancelled": result.cancelled,
                   "outputs": packed, "outputs_truncated": truncated})
        except Exception as e:
            q.put({"event": "error", "message": str(e)})
        finally:
            _unregister_run(run_id)

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def event_stream():
        finished = False
        try:
            while True:
                try:
                    item = q.get(timeout=0.1)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    if item["event"] in ("done", "error"):
                        finished = True
                        break
                except thread_queue.Empty:
                    await asyncio.sleep(0.05)
        finally:
            # 클라이언트가 연결을 끊으면(탭 닫기·새로고침) 러너도 세운다 —
            # 기존엔 daemon 스레드가 계속 돌며 GPU/한글 COM을 붙잡고 있었다.
            if not finished:
                cancel_ev.set()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
