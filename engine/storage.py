"""
데이터 저장소 — 워크플로우, 실행 히스토리, 자동저장 관리.

data/
├── workflows/          # 저장된 워크플로우 (개별 JSON)
├── history/            # 실행 히스토리 (실행 결과 로그)
├── autosave/           # 자동저장 (최근 작업 복구용)
└── presets/            # 프리셋 (자주 쓰는 워크플로우 템플릿)
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class WorkflowMeta:
    """워크플로우 메타데이터 (index에 저장)."""

    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    thumbnail_nodes: list[str] = field(default_factory=list)  # 노드 타입 목록 (미리보기용)
    thumbnail_data: dict | None = None  # {nodes: [{id,type,x,y}], edges: [{from,to}]}


@dataclass
class ExecutionRecord:
    """실행 히스토리 레코드."""

    id: str
    workflow_id: str
    workflow_name: str
    started_at: str
    finished_at: str
    success: bool
    elapsed_seconds: float
    errors: list[str] = field(default_factory=list)
    node_timings: dict[str, float] = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gen_id() -> str:
    return f"wf_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _build_thumbnail_data(wf_data: dict) -> dict:
    """워크플로우 데이터에서 미니 플로우차트용 thumbnail_data 생성."""
    nodes = []
    for n in wf_data.get("nodes", []):
        pos = n.get("position", {})
        nodes.append({
            "id": n.get("id", ""),
            "type": n.get("type", ""),
            "x": pos.get("x", 0),
            "y": pos.get("y", 0),
        })
    edges = []
    for e in wf_data.get("edges", []):
        # 양쪽 포맷 지원
        fr = e.get("from") or e.get("source", "")
        to = e.get("to") or e.get("target", "")
        if fr and to:
            edges.append({"from": fr, "to": to})
    return {"nodes": nodes, "edges": edges}


class DataStore:
    """파일 기반 데이터 저장소."""

    def __init__(self, data_dir: Path):
        self._root = data_dir
        self._wf_dir = data_dir / "workflows"
        self._history_dir = data_dir / "history"
        self._autosave_dir = data_dir / "autosave"
        self._presets_dir = data_dir / "presets"

        # 디렉토리 보장
        for d in [self._wf_dir, self._history_dir, self._autosave_dir, self._presets_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────
    #  워크플로우 CRUD
    # ──────────────────────────────────────────────

    def list_workflows(self) -> list[WorkflowMeta]:
        """저장된 워크플로우 메타 목록 (최신순)."""
        results = []
        for f in self._wf_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meta = data.get("_meta", {})
                td = meta.get("thumbnail_data") or _build_thumbnail_data(data)
                results.append(WorkflowMeta(
                    id=meta.get("id", f.stem),
                    name=meta.get("name", data.get("name", f.stem)),
                    description=meta.get("description", data.get("description", "")),
                    tags=meta.get("tags", []),
                    node_count=len(data.get("nodes", [])),
                    edge_count=len(data.get("edges", [])),
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    thumbnail_nodes=meta.get("thumbnail_nodes", []),
                    thumbnail_data=td,
                ))
            except Exception:
                pass
        results.sort(key=lambda m: m.updated_at or m.created_at, reverse=True)
        return results

    def save_workflow(self, workflow_data: dict, workflow_id: str | None = None) -> WorkflowMeta:
        """워크플로우 저장 (새로 만들기 또는 업데이트)."""
        now = _now_iso()

        if workflow_id and (self._wf_dir / f"{workflow_id}.json").exists():
            # 기존 업데이트
            existing = json.loads((self._wf_dir / f"{workflow_id}.json").read_text(encoding="utf-8"))
            created = existing.get("_meta", {}).get("created_at", now)
        else:
            workflow_id = workflow_id or _gen_id()
            created = now

        node_types = [n.get("type", "") for n in workflow_data.get("nodes", [])]
        td = _build_thumbnail_data(workflow_data)

        meta = {
            "id": workflow_id,
            "name": workflow_data.get("name", "이름 없음"),
            "description": workflow_data.get("description", ""),
            "tags": workflow_data.get("tags", []),
            "created_at": created,
            "updated_at": now,
            "thumbnail_nodes": node_types[:10],
            "thumbnail_data": td,
        }

        # 메타를 워크플로우 데이터에 임베드
        workflow_data["_meta"] = meta
        workflow_data["id"] = workflow_id

        path = self._wf_dir / f"{workflow_id}.json"
        path.write_text(json.dumps(workflow_data, ensure_ascii=False, indent=2), encoding="utf-8")

        return WorkflowMeta(
            id=workflow_id,
            name=meta["name"],
            description=meta["description"],
            tags=meta.get("tags", []),
            node_count=len(workflow_data.get("nodes", [])),
            edge_count=len(workflow_data.get("edges", [])),
            created_at=created,
            updated_at=now,
            thumbnail_nodes=node_types[:10],
        )

    def load_workflow(self, workflow_id: str) -> dict | None:
        """워크플로우 JSON 로드 (워크플로우 → 프리셋 순으로 탐색)."""
        path = self._wf_dir / f"{workflow_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        # 프리셋에서도 검색
        path = self._presets_dir / f"{workflow_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def delete_workflow(self, workflow_id: str) -> bool:
        """워크플로우 삭제."""
        path = self._wf_dir / f"{workflow_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def duplicate_workflow(self, workflow_id: str) -> WorkflowMeta | None:
        """워크플로우 복제."""
        data = self.load_workflow(workflow_id)
        if not data:
            return None
        data["name"] = data.get("name", "") + " (복사본)"
        data.pop("_meta", None)
        return self.save_workflow(data)

    def rename_workflow(self, workflow_id: str, name: str, description: str = "") -> WorkflowMeta | None:
        """워크플로우 이름/설명 변경."""
        data = self.load_workflow(workflow_id)
        if not data:
            return None
        data["name"] = name
        if description:
            data["description"] = description
        return self.save_workflow(data, workflow_id)

    def update_tags(self, workflow_id: str, tags: list[str]) -> WorkflowMeta | None:
        """태그 업데이트."""
        data = self.load_workflow(workflow_id)
        if not data:
            return None
        data["tags"] = tags
        return self.save_workflow(data, workflow_id)

    # ──────────────────────────────────────────────
    #  자동저장
    # ──────────────────────────────────────────────

    def autosave(self, workflow_data: dict) -> str:
        """현재 작업을 자동저장. 최근 5개만 유지."""
        ts = int(time.time())
        path = self._autosave_dir / f"autosave_{ts}.json"
        path.write_text(json.dumps(workflow_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 오래된 자동저장 정리 (최근 5개만)
        saves = sorted(self._autosave_dir.glob("autosave_*.json"), reverse=True)
        for old in saves[5:]:
            old.unlink()

        return str(path)

    def load_autosave(self) -> dict | None:
        """가장 최근 자동저장 로드."""
        saves = sorted(self._autosave_dir.glob("autosave_*.json"), reverse=True)
        if not saves:
            return None
        return json.loads(saves[0].read_text(encoding="utf-8"))

    def list_autosaves(self) -> list[dict]:
        """자동저장 목록."""
        results = []
        for f in sorted(self._autosave_dir.glob("autosave_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts_str = f.stem.replace("autosave_", "")
                results.append({
                    "filename": f.name,
                    "timestamp": int(ts_str),
                    "datetime": datetime.fromtimestamp(int(ts_str)).isoformat(timespec="seconds"),
                    "name": data.get("name", ""),
                    "node_count": len(data.get("nodes", [])),
                })
            except Exception:
                pass
        return results

    # ──────────────────────────────────────────────
    #  실행 히스토리
    # ──────────────────────────────────────────────

    def add_history(self, record: ExecutionRecord):
        """실행 기록 추가."""
        path = self._history_dir / f"{record.id}.json"
        path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")

        # 히스토리 최대 100개 유지
        files = sorted(self._history_dir.glob("*.json"), reverse=True)
        for old in files[100:]:
            old.unlink()

    def list_history(self, limit: int = 30) -> list[dict]:
        """실행 히스토리 목록 (최신순)."""
        results = []
        files = sorted(self._history_dir.glob("*.json"), reverse=True)
        for f in files[:limit]:
            try:
                results.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return results

    def get_history(self, record_id: str) -> dict | None:
        """특정 실행 기록 상세."""
        path = self._history_dir / f"{record_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def clear_history(self):
        """히스토리 전체 삭제."""
        for f in self._history_dir.glob("*.json"):
            f.unlink()

    # ──────────────────────────────────────────────
    #  프리셋
    # ──────────────────────────────────────────────

    def list_presets(self) -> list[WorkflowMeta]:
        """프리셋 목록."""
        results = []
        for f in self._presets_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meta = data.get("_meta", {})
                td = meta.get("thumbnail_data") or _build_thumbnail_data(data)
                results.append(WorkflowMeta(
                    id=meta.get("id", f.stem),
                    name=meta.get("name", f.stem),
                    description=meta.get("description", ""),
                    tags=meta.get("tags", ["프리셋"]),
                    node_count=len(data.get("nodes", [])),
                    edge_count=len(data.get("edges", [])),
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    thumbnail_nodes=meta.get("thumbnail_nodes", []),
                    thumbnail_data=td,
                ))
            except Exception:
                pass
        return results

    def save_as_preset(self, workflow_id: str) -> bool:
        """워크플로우를 프리셋으로 저장."""
        data = self.load_workflow(workflow_id)
        if not data:
            return False
        meta = data.get("_meta", {})
        meta["tags"] = list(set(meta.get("tags", []) + ["프리셋"]))
        data["_meta"] = meta
        dest = self._presets_dir / f"{workflow_id}.json"
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    # ──────────────────────────────────────────────
    #  통계
    # ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        """데이터 저장소 통계."""
        return {
            "workflow_count": len(list(self._wf_dir.glob("*.json"))),
            "history_count": len(list(self._history_dir.glob("*.json"))),
            "autosave_count": len(list(self._autosave_dir.glob("*.json"))),
            "preset_count": len(list(self._presets_dir.glob("*.json"))),
        }
