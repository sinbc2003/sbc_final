"""
데이터 타입 시스템.

노드 간 연결은 타입이 일치해야 한다.
타입이 안 맞으면 연결 불가.

타입 목록:
  file   — 파일 경로 (accept로 확장자 세분화)
  text   — 문자열
  table  — 표 데이터 (pandas DataFrame JSON)
  image  — 이미지 파일 경로
  list   — 위 타입의 배열
  any    — 모든 타입 허용
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# 기본 타입 이름
VALID_TYPES = {"file", "text", "table", "image", "list", "any"}


@dataclass
class PortSpec:
    """노드의 입출력 포트 명세."""

    name: str
    type: str
    accept: list[str] = field(default_factory=list)  # file 타입일 때 허용 확장자
    description: str = ""

    def __post_init__(self):
        if self.type not in VALID_TYPES:
            raise ValueError(f"알 수 없는 타입: {self.type!r} (허용: {VALID_TYPES})")


def types_compatible(output_port: PortSpec, input_port: PortSpec) -> bool:
    """출력 포트와 입력 포트의 타입이 호환되는지 검사."""
    # any는 모든 타입과 호환
    if output_port.type == "any" or input_port.type == "any":
        return True

    # 기본 타입 일치
    if output_port.type != input_port.type:
        return False

    # file 타입이면 accept 확장자 검사
    if output_port.type == "file" and input_port.accept:
        # 출력 쪽에 accept가 없으면 (범용 파일) → 입력 쪽 accept 있으면 경고만
        # 출력 쪽에 accept가 있으면 교집합이 있어야 함
        if output_port.accept:
            overlap = set(output_port.accept) & set(input_port.accept)
            if not overlap:
                return False

    return True


def validate_value(value: Any, port: PortSpec) -> bool:
    """실행 시점에 실제 값이 포트 타입에 맞는지 검증."""
    if value is None:
        return False

    if port.type == "any":
        return True

    if port.type == "file":
        if not isinstance(value, (str, Path)):
            return False
        if port.accept:
            ext = Path(str(value)).suffix.lower()
            if ext not in port.accept:
                return False
        return True

    if port.type == "text":
        return isinstance(value, str)

    if port.type == "table":
        # JSON 직렬화된 DataFrame 또는 dict/list
        return isinstance(value, (dict, list, str))

    if port.type == "image":
        return isinstance(value, (str, Path))

    if port.type == "list":
        return isinstance(value, list)

    return False
