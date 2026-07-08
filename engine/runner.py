"""
파이프라인 실행기 — 워크플로우 JSON을 읽고 DAG 순서로 노드 실행.

워크플로우 JSON → DAG 구성 → 위상 정렬 → 순서대로 execute() 호출.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .loader import NodeRegistry
from .llm_manager import LLMManager
from .types import PortSpec, types_compatible


@dataclass
class WorkflowNode:
    """워크플로우 내 노드 인스턴스."""

    id: str
    type: str  # NodeDefinition.id
    position: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    """노드 간 연결."""

    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass
class Workflow:
    """워크플로우 정의."""

    id: str
    name: str
    version: str
    description: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    user_inputs: list[dict] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict) -> Workflow:
        """JSON dict에서 Workflow 생성."""
        nodes = [
            WorkflowNode(
                id=n["id"],
                type=n["type"],
                position=n.get("position", {}),
                params=n.get("params", {}),
            )
            for n in data.get("nodes", [])
        ]
        edges = [
            WorkflowEdge(
                from_node=e["from"],
                from_port=e["from_port"],
                to_node=e["to"],
                to_port=e["to_port"],
            )
            for e in data.get("edges", [])
        ]
        return cls(
            id=data.get("id", "unnamed"),
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            nodes=nodes,
            edges=edges,
            user_inputs=data.get("user_inputs", []),
        )

    @classmethod
    def from_file(cls, path: Path) -> Workflow:
        """JSON 파일에서 Workflow 로드."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_json(data)


def _topological_sort(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> list[str]:
    """DAG 위상 정렬. 실행 순서 반환."""
    node_ids = {n.id for n in nodes}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        adjacency[edge.from_node].append(edge.to_node)
        in_degree[edge.to_node] += 1

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order = []

    while queue:
        nid = queue.popleft()
        order.append(nid)
        for neighbor in adjacency[nid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(node_ids):
        raise ValueError("워크플로우에 순환(cycle)이 있습니다")

    return order


def _validate_connections(
    workflow: Workflow, registry: NodeRegistry
) -> list[str]:
    """연결 타입 호환성 검증. 경고 메시지 목록 반환."""
    warnings = []
    node_map = {n.id: n for n in workflow.nodes}

    for edge in workflow.edges:
        from_wf_node = node_map.get(edge.from_node)
        to_wf_node = node_map.get(edge.to_node)
        if not from_wf_node or not to_wf_node:
            warnings.append(f"존재하지 않는 노드 참조: {edge.from_node} → {edge.to_node}")
            continue

        from_def = registry.get(from_wf_node.type)
        to_def = registry.get(to_wf_node.type)
        if not from_def:
            warnings.append(f"미등록 노드 타입: {from_wf_node.type}")
            continue
        if not to_def:
            warnings.append(f"미등록 노드 타입: {to_wf_node.type}")
            continue

        out_port = from_def.get_output_port(edge.from_port)
        in_port = to_def.get_input_port(edge.to_port)

        if not out_port:
            warnings.append(
                f"출력 포트 없음: {from_wf_node.type}.{edge.from_port}"
            )
            continue
        if not in_port:
            warnings.append(
                f"입력 포트 없음: {to_wf_node.type}.{edge.to_port}"
            )
            continue

        if not types_compatible(out_port, in_port):
            warnings.append(
                f"타입 불일치: {from_wf_node.type}.{edge.from_port}"
                f"({out_port.type}) → {to_wf_node.type}.{edge.to_port}"
                f"({in_port.type})"
            )

    return warnings


@dataclass
class ExecutionResult:
    """파이프라인 실행 결과."""

    success: bool
    outputs: dict[str, dict]  # node_id → {port_name: value}
    errors: list[str]
    elapsed_seconds: float
    node_timings: dict[str, float]  # node_id → 실행 시간(초)


class PipelineRunner:
    """파이프라인 실행기."""

    def __init__(
        self,
        registry: NodeRegistry,
        llm_manager: LLMManager | None = None,
        config: dict | None = None,
        on_progress: Callable[[str, float], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
    ):
        self._registry = registry
        self._llm = llm_manager
        self._config = config or {}
        self._on_progress = on_progress  # (node_id, 0.0~1.0)
        self._on_log = on_log  # (node_id, message)

    def run(
        self,
        workflow: Workflow,
        initial_inputs: dict[str, dict] | None = None,
    ) -> ExecutionResult:
        """워크플로우 실행.

        Args:
            workflow: 실행할 워크플로우
            initial_inputs: 시작 노드에 주입할 입력값
                            {node_id: {port_name: value}}
        """
        start_time = time.time()
        errors = []
        node_outputs: dict[str, dict] = {}
        node_timings: dict[str, float] = {}
        initial_inputs = initial_inputs or {}

        # 연결 검증
        warnings = _validate_connections(workflow, self._registry)
        for w in warnings:
            self._log("SYSTEM", f"[WARN] {w}")

        # 위상 정렬
        try:
            execution_order = _topological_sort(workflow.nodes, workflow.edges)
        except ValueError as e:
            return ExecutionResult(
                success=False,
                outputs={},
                errors=[str(e)],
                elapsed_seconds=time.time() - start_time,
                node_timings={},
            )

        # 노드 맵
        wf_node_map = {n.id: n for n in workflow.nodes}

        # 엣지 → 입력 노드별로 그룹핑
        incoming_edges: dict[str, list[WorkflowEdge]] = defaultdict(list)
        for edge in workflow.edges:
            incoming_edges[edge.to_node].append(edge)

        # 순서대로 실행
        for node_id in execution_order:
            wf_node = wf_node_map[node_id]
            node_def = self._registry.get(wf_node.type)

            if not node_def:
                errors.append(f"노드 타입 '{wf_node.type}' 을 찾을 수 없습니다")
                continue

            self._log(node_id, f"실행 시작: {node_def.name}")
            self._progress(node_id, 0.0)

            # 입력 조립: 엣지에서 온 데이터 + initial_inputs
            inputs = {}
            if node_id in initial_inputs:
                inputs.update(initial_inputs[node_id])

            for edge in incoming_edges.get(node_id, []):
                src_outputs = node_outputs.get(edge.from_node, {})
                if edge.from_port in src_outputs:
                    inputs[edge.to_port] = src_outputs[edge.from_port]

            # 파라미터 (node.yaml defaults + workflow overrides)
            params = {}
            for p_def in node_def.params:
                params[p_def["id"]] = p_def.get("default")
            params.update(wf_node.params)

            # file_input 같은 소스 노드: initial_inputs를 params로 전달
            if not node_def.inputs and node_id in initial_inputs:
                for port_name, value in initial_inputs[node_id].items():
                    # 파일 입력 → path 파라미터에 매핑
                    if port_name in ("파일", "file") and "path" in params:
                        params["path"] = value
                    else:
                        params[port_name] = value

            # 필수 입력 사전 검증: 미연결/상류 실패로 값이 없으면 명확한 한국어
            # 메시지로 건너뛴다. (raw KeyError: '파일' 노출 방지)
            missing = [
                port.name for port in node_def.inputs
                if not port.optional and (
                    port.name not in inputs or inputs.get(port.name) is None
                )
            ]
            if missing:
                port_list = ", ".join(f"'{m}'" for m in missing)
                err_msg = (
                    f"노드 '{node_id}' ({node_def.name}): "
                    f"필수 입력 {port_list}이(가) 연결되지 않았거나 "
                    f"이전 노드에서 값이 오지 않았습니다"
                )
                errors.append(err_msg)
                self._log(node_id, f"[ERROR] {err_msg}")
                node_outputs[node_id] = {}
                node_timings[node_id] = 0.0
                continue

            # context 구성
            temp_dir = tempfile.mkdtemp(prefix=f"tf_{node_id}_")
            context = {
                "temp_dir": temp_dir,
                "progress": lambda v, _nid=node_id: self._progress(_nid, v),
                "log": lambda msg, _nid=node_id: self._log(_nid, msg),
                "llm": self._llm,
                "config": self._config,
            }

            # 실행
            node_start = time.time()
            try:
                result = node_def.execute_fn(inputs, params, context)
                node_outputs[node_id] = result or {}
                node_timings[node_id] = time.time() - node_start
                self._progress(node_id, 1.0)
                self._log(
                    node_id,
                    f"완료 ({node_timings[node_id]:.1f}초)"
                )
            except Exception as e:
                node_timings[node_id] = time.time() - node_start
                err_msg = f"노드 '{node_id}' ({node_def.name}) 실행 실패: {e}"
                errors.append(err_msg)
                self._log(node_id, f"[ERROR] {e}")
                # 실패해도 다음 노드 시도 (의존성 없는 경우)
                node_outputs[node_id] = {}

        elapsed = time.time() - start_time

        # 출력 파일을 저장 경로로 복사
        output_dir = self._config.get("output_dir", "")
        if not output_dir:
            output_dir = str(Path.home() / "Desktop")
        if output_dir and Path(output_dir).is_dir():
            import shutil
            for nid, outputs in node_outputs.items():
                for port, val in outputs.items():
                    if isinstance(val, str) and Path(val).is_file():
                        try:
                            dest = Path(output_dir) / Path(val).name
                            if str(Path(val).parent) != output_dir:
                                shutil.copy2(val, dest)
                                node_outputs[nid][port] = str(dest)
                                self._log(nid, f"저장: {dest}")
                        except Exception:
                            pass

        return ExecutionResult(
            success=len(errors) == 0,
            outputs=node_outputs,
            errors=errors,
            elapsed_seconds=elapsed,
            node_timings=node_timings,
        )

    def _progress(self, node_id: str, value: float):
        if self._on_progress:
            self._on_progress(node_id, value)

    def _log(self, node_id: str, message: str):
        if self._on_log:
            self._on_log(node_id, message)
        else:
            print(f"[{node_id}] {message}")
