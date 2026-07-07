"""HWP 데이터 모델 — Block, DocumentInfo."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from engine.hwpml import (
        parse_hwpml2x,
        PositionEngine,
        build_cvd,
        extract_table_merge_map,
        StyleLookup,
    )
    from engine.hwpml.com_retry import com_retry, is_transient_com_error
    _HWPML_AVAILABLE = True
except ImportError:
    _HWPML_AVAILABLE = False


@dataclass
class Block:
    """개별 블록 정보."""
    id: str
    position: Tuple[int, int, int]  # (list_pos, para_pos, char_pos)
    text: str = ""
    block_type: str = "text"  # text | list | td | footnote | equation | image
    table_group_id: Optional[int] = None
    table_idx: Optional[int] = None   # get_into_nth_table용 인덱스
    cell_seq: Optional[int] = None    # 테이블 내 셀 순서 (0-based)
    # 셀 병합 정보 (HWPML 스캔 시 보존)
    col_addr: Optional[int] = None
    row_addr: Optional[int] = None
    col_span: int = 1
    row_span: int = 1
    # 스타일 참조 (HWPML 스캔 시 보존)
    charshape_id: int = 0
    parashape_id: int = 0
    outline_level: int = 0

    @property
    def list_pos(self) -> int:
        return self.position[0]

    @property
    def para_pos(self) -> int:
        return self.position[1]

    @property
    def char_pos(self) -> int:
        return self.position[2]


@dataclass
class DocumentInfo:
    """문서 실시간 상태."""
    document_path: str = ""
    document_name: str = ""
    caret_position: Tuple[int, int, int] = (0, 0, 0)
    caret_page: int = 0
    total_pages: int = 0
    selected_text: str = ""
    ctrl_type: Optional[str] = None  # 표, 그림 등
    document_mode: str = "EDIT"
    modified: bool = False

    def to_dict(self) -> dict:
        return {
            "document_path": self.document_path,
            "document_name": self.document_name,
            "caret_position": list(self.caret_position),
            "caret_page": self.caret_page,
            "total_pages": self.total_pages,
            "selected_text": self.selected_text,
            "ctrl_type": self.ctrl_type,
            "document_mode": self.document_mode,
            "modified": self.modified,
        }
