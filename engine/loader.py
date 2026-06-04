"""
노드 로더 — nodes/ 폴더 스캔, node.yaml 파싱, 자동 등록.

nodes/ 하위의 각 폴더가 하나의 노드.
각 폴더에는 node.yaml(메타데이터) + main.py(실행 코드)가 있어야 한다.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .types import PortSpec


@dataclass
class NodeDefinition:
    """로드된 노드 정의."""

    id: str
    name: str
    version: str
    category: str
    icon: str
    author: str
    description: str
    inputs: list[PortSpec]
    outputs: list[PortSpec]
    params: list[dict]
    resource: dict
    dependencies: list[str]
    use_when: list[str]
    execute_fn: Callable  # main.py의 execute 함수

    def get_input_port(self, name: str) -> PortSpec | None:
        for port in self.inputs:
            if port.name == name:
                return port
        return None

    def get_output_port(self, name: str) -> PortSpec | None:
        for port in self.outputs:
            if port.name == name:
                return port
        return None


def _parse_ports(port_list: list[dict]) -> list[PortSpec]:
    """YAML의 포트 목록을 PortSpec 리스트로 변환."""
    ports = []
    for p in port_list or []:
        ports.append(PortSpec(
            name=p["name"],
            type=p["type"],
            accept=p.get("accept", []),
            description=p.get("description", ""),
        ))
    return ports


def _load_execute_fn(node_dir: Path) -> Callable:
    """main.py에서 execute 함수를 동적 로드."""
    main_py = node_dir / "main.py"
    if not main_py.exists():
        raise FileNotFoundError(f"main.py 없음: {main_py}")

    spec = importlib.util.spec_from_file_location(
        f"nodes.{node_dir.name}.main", main_py
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "execute"):
        raise AttributeError(f"execute() 함수 없음: {main_py}")

    return module.execute


def load_node(node_dir: Path) -> NodeDefinition:
    """단일 노드 폴더에서 NodeDefinition을 로드."""
    yaml_path = node_dir / "node.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"node.yaml 없음: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        meta = yaml.safe_load(f)

    execute_fn = _load_execute_fn(node_dir)

    return NodeDefinition(
        id=meta["id"],
        name=meta.get("name", meta["id"]),
        version=meta.get("version", "0.0.1"),
        category=meta.get("category", "기타"),
        icon=meta.get("icon", "box"),
        author=meta.get("author", ""),
        description=meta.get("description", ""),
        inputs=_parse_ports(meta.get("inputs")),
        outputs=_parse_ports(meta.get("outputs")),
        params=meta.get("params", []),
        resource=meta.get("resource", {}),
        dependencies=meta.get("dependencies", []),
        use_when=meta.get("use_when", []),
        execute_fn=execute_fn,
    )


class NodeRegistry:
    """노드 레지스트리 — 모든 로드된 노드를 관리."""

    def __init__(self):
        self._nodes: dict[str, NodeDefinition] = {}

    def load_all(self, nodes_dir: Path) -> list[str]:
        """nodes/ 폴더를 스캔하여 모든 노드를 로드. 로드된 노드 ID 목록 반환."""
        loaded = []
        if not nodes_dir.exists():
            return loaded

        for child in sorted(nodes_dir.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "node.yaml").exists():
                continue
            try:
                node_def = load_node(child)
                self._nodes[node_def.id] = node_def
                loaded.append(node_def.id)
            except Exception as e:
                print(f"[WARN] 노드 로드 실패 ({child.name}): {e}")

        return loaded

    def get(self, node_id: str) -> NodeDefinition | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[NodeDefinition]:
        return list(self._nodes.values())

    def list_ids(self) -> list[str]:
        return list(self._nodes.keys())

    def __len__(self) -> int:
        return len(self._nodes)
