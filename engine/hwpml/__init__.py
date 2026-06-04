"""
engine.hwpml — HWPML/HWPX 문서 처리 패키지.

모듈 구조:
  parser.py          — HWPML2X/HWPX XML → DocNode 트리
  font_aliases.py    — 폰트 패밀리 별칭 정규화
  com_retry.py       — COM 호출 재시도 데코레이터
  position_engine.py — DocNode → 블록 리스트 + 위치 매핑 (Phase 2)
  cvd_builder.py     — 블록 → CVD 텍스트 (Phase 2)
  equation.py        — LaTeX → HWP 수식 변환 (Phase 3)
"""

# ── Phase 1: Foundation ────────────────────────────────

# parser
from .parser import (
    DocNode,
    BodyNode,
    SectionNode,
    ParagraphNode,
    TableNode,
    RowNode,
    CellNode,
    FootnoteNode,
    ImageNode,
    TextboxNode,
    EquationNode,
    StyleLookup,
    parse_hwpml2x,
    parse_hwpx_section,
)

# font
from .font_aliases import (
    canonicalize_font_family_name,
    font_alias_key,
    is_same_font,
    register_alias_group,
    FONT_FAMILY_ALIAS_GROUPS,
)

# com retry
from .com_retry import (
    com_retry,
    com_retry_simple,
    is_transient_com_error,
    COM_RETRY_HRESULTS,
    COM_RETRY_MESSAGES,
)

# ── Phase 2: Document Scanning ────────────────────────

# position engine
from .position_engine import (
    PositionEngine,
    extract_blocks_and_positions,
    extract_table_merge_map,
)

# cvd builder
from .cvd_builder import (
    build_cvd,
    build_cvd_from_doc,
)

# ── Phase 3: Equation ─────────────────────────────────

from .equation import (
    latex_to_hwp,
    extract_equations_from_markdown,
    markdown_to_hwp_equations,
    hwp_equation_to_xml,
)

__all__ = [
    # Node 클래스
    'DocNode', 'BodyNode', 'SectionNode', 'ParagraphNode',
    'TableNode', 'RowNode', 'CellNode', 'FootnoteNode',
    'ImageNode', 'TextboxNode', 'EquationNode',
    # 파서
    'StyleLookup', 'parse_hwpml2x', 'parse_hwpx_section',
    # 폰트
    'canonicalize_font_family_name', 'font_alias_key',
    'is_same_font', 'register_alias_group', 'FONT_FAMILY_ALIAS_GROUPS',
    # COM
    'com_retry', 'com_retry_simple', 'is_transient_com_error',
    'COM_RETRY_HRESULTS', 'COM_RETRY_MESSAGES',
    # Position Engine
    'PositionEngine', 'extract_blocks_and_positions', 'extract_table_merge_map',
    # CVD Builder
    'build_cvd', 'build_cvd_from_doc',
    # Equation
    'latex_to_hwp', 'extract_equations_from_markdown',
    'markdown_to_hwp_equations', 'hwp_equation_to_xml',
]
