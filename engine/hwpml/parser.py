"""
HWPML/HWPX XML 파서 — 문서 구조를 DocNode 트리로 변환.

HWPML2X (COM GetTextFile/SaveAs 출력)와 HWPX (ZIP 내부 XML) 양쪽 지원.
차이점: HWPML2X는 태그 이름이 대문자 (P, TEXT, CHAR, TABLE, ROW, CELL),
HWPX는 네임스페이스 접두사 사용 (hp:p, hp:run, hp:t, hp:tbl 등).

핵심:
  - 10개 Node 클래스: 문서 구조의 완전한 표현
  - StyleLookup: charshape/parashape/fontid 매핑
  - 셀 병합(colspan/rowspan) 정확한 처리 ← 최우선 요구사항

참조: Inline AI v0.3.1 helpers.py (442 식별자, Nuitka 바이너리 추출)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from .font_aliases import canonicalize_font_family_name


# ============================================================================
# Node 클래스 — __slots__ 사용, 메모리 효율 + 필드 명시
# ============================================================================

class DocNode:
    """파싱 결과 루트."""
    __slots__ = ('node_type', 'style_lookup', 'children')

    def __init__(self):
        self.node_type = "doc"
        self.style_lookup: Optional[StyleLookup] = None
        self.children: List[BodyNode] = []


class BodyNode:
    __slots__ = ('node_type', 'children')

    def __init__(self):
        self.node_type = "body"
        self.children: List[SectionNode] = []


class SectionNode:
    __slots__ = ('node_type', 'section_def', 'children')

    def __init__(self):
        self.node_type = "section"
        self.section_def: Optional[Dict[str, str]] = None  # 페이지 설정 속성
        self.children: list = []  # ParagraphNode | TableNode 등


class ParagraphNode:
    __slots__ = ('node_type', 'charshape_id', 'parashape_id', 'style_id',
                 'outline_level', 'text_runs', 'inline_nodes', 'header_footer')

    def __init__(self):
        self.node_type = "paragraph"
        self.charshape_id: int = 0
        self.parashape_id: int = 0
        self.style_id: int = 0
        self.outline_level: int = 0
        self.text_runs: List[Tuple[str, int]] = []        # [(text, charshape_id)]
        self.inline_nodes: list = []                        # TableNode | ImageNode | ...
        self.header_footer: Optional[Any] = None

    @property
    def full_text(self) -> str:
        return ''.join(t for t, _ in self.text_runs)


class TableNode:
    """표 — 셀 병합 구조를 정확히 보존."""
    __slots__ = ('node_type', 'col_count', 'row_count', 'rows',
                 'table_anchor', 'caption_side', 'shape_object',
                 'cell_spacing', 'border_fill')

    def __init__(self):
        self.node_type = "table"
        self.col_count: int = 0
        self.row_count: int = 0
        self.rows: List[RowNode] = []
        self.table_anchor: Optional[str] = None
        self.caption_side: Optional[str] = None
        self.shape_object: Optional[Any] = None
        self.cell_spacing: int = 0
        self.border_fill: Optional[str] = None

    def get_merged_cell_map(self) -> Dict[Tuple[int, int], 'CellNode']:
        """(row, col) → CellNode 매핑. 병합된 셀은 원본 셀을 가리킴.

        확장성: 외부 모듈(HWPX 빌더, CVD 빌더)에서 병합 구조 조회 시 사용.
        """
        cell_map: Dict[Tuple[int, int], CellNode] = {}
        for row in self.rows:
            for cell in row.cells:
                for dr in range(cell.row_span):
                    for dc in range(cell.col_span):
                        r = cell.row_addr + dr
                        c = cell.col_addr + dc
                        cell_map[(r, c)] = cell
        return cell_map

    def iter_cells(self):
        """모든 셀을 행 순서대로 순회."""
        for row in self.rows:
            yield from row.cells


class RowNode:
    __slots__ = ('node_type', 'cells')

    def __init__(self):
        self.node_type = "row"
        self.cells: List[CellNode] = []


class CellNode:
    """표 셀 — colspan/rowspan 병합 정보를 완전 보존.

    col_addr, row_addr: 셀의 논리적 위치 (0-based)
    col_span, row_span: 병합 범위 (1=병합 없음)
    """
    __slots__ = ('node_type', 'col_addr', 'row_addr', 'col_span', 'row_span',
                 'width', 'height', 'paragraph_charshape_id', 'paragraphs',
                 'border_fill', 'vert_align')

    def __init__(self):
        self.node_type = "cell"
        self.col_addr: int = 0
        self.row_addr: int = 0
        self.col_span: int = 1
        self.row_span: int = 1
        self.width: int = 0       # 1/100mm
        self.height: int = 0      # 1/100mm
        self.paragraph_charshape_id: int = 0
        self.paragraphs: List[ParagraphNode] = []
        self.border_fill: Optional[str] = None
        self.vert_align: Optional[str] = None

    @property
    def is_merged(self) -> bool:
        return self.col_span > 1 or self.row_span > 1

    @property
    def full_text(self) -> str:
        parts = []
        for p in self.paragraphs:
            parts.append(p.full_text)
        return '\n'.join(parts)


class FootnoteNode:
    __slots__ = ('node_type', 'series_num', 'is_endnote', 'paragraphs')

    def __init__(self):
        self.node_type = "footnote"
        self.series_num: int = 0
        self.is_endnote: bool = False
        self.paragraphs: List[ParagraphNode] = []


class ImageNode:
    __slots__ = ('node_type', 'image_anchor', 'shape_object',
                 'bin_data_id', 'width', 'height')

    def __init__(self):
        self.node_type = "image"
        self.image_anchor: Optional[str] = None
        self.shape_object: Optional[Any] = None
        self.bin_data_id: Optional[str] = None
        self.width: int = 0
        self.height: int = 0


class TextboxNode:
    __slots__ = ('node_type', 'paragraphs', 'width', 'height')

    def __init__(self):
        self.node_type = "textbox"
        self.paragraphs: List[ParagraphNode] = []
        self.width: int = 0
        self.height: int = 0


class EquationNode:
    """수식 노드 — HWP 수식 편집기 스크립트를 보존."""
    __slots__ = ('node_type', 'script', 'version')

    def __init__(self):
        self.node_type = "equation"
        self.script: str = ""
        self.version: str = "2.0"


# ============================================================================
# StyleLookup — 서식 속성 매핑
# ============================================================================

class StyleLookup:
    """charshape_id/parashape_id → 서식 속성 조회.

    HWPML2X HEAD의 CHARSHAPELIST, PARASHAPELIST, FONTFACE에서 구축.
    """

    def __init__(self):
        self.charshapes: Dict[int, dict] = {}
        self.parashapes: Dict[int, dict] = {}
        self.fontid_map: Dict[Tuple[str, int], str] = {}  # (lang, font_id) → name
        self.styles: Dict[int, dict] = {}
        self.border_fills: Dict[int, dict] = {}

    # ── charshape 조회 ──

    def get_font_size_pt(self, charshape_id: int) -> Optional[float]:
        cs = self.charshapes.get(charshape_id)
        return cs['height'] / 100.0 if cs else None

    def get_font_family(self, charshape_id: int) -> Optional[str]:
        cs = self.charshapes.get(charshape_id)
        if not cs:
            return None
        hangul_id = cs.get('fontid_hangul', 0)
        raw = self.fontid_map.get(('Hangul', hangul_id))
        return canonicalize_font_family_name(raw) if raw else raw

    def get_font_family_by_lang(self, charshape_id: int, lang: str = 'Hangul') -> Optional[str]:
        """언어별 폰트 조회 (Hangul, Latin, Hanja, Symbol 등)."""
        cs = self.charshapes.get(charshape_id)
        if not cs:
            return None
        font_ids = cs.get('font_ids', {})
        font_id = font_ids.get(lang, 0)
        raw = self.fontid_map.get((lang, font_id))
        return canonicalize_font_family_name(raw) if raw else raw

    def get_bold(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('bold', False)

    def get_italic(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('italic', False)

    def get_underline(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('underline', False)

    def get_text_color(self, charshape_id: int) -> Optional[str]:
        color_int = self.charshapes.get(charshape_id, {}).get('text_color')
        return _bgr_to_hex(color_int) if color_int is not None else None

    def get_strikeout(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('strikeout', False)

    def get_superscript(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('superscript', False)

    def get_subscript(self, charshape_id: int) -> bool:
        return self.charshapes.get(charshape_id, {}).get('subscript', False)

    # ── parashape 조회 ──

    def get_align(self, parashape_id: int) -> Optional[str]:
        ps = self.parashapes.get(parashape_id)
        return ps.get('align', 'Justify') if ps else None

    def get_line_spacing(self, parashape_id: int) -> Optional[int]:
        ps = self.parashapes.get(parashape_id)
        return ps.get('line_spacing') if ps else None

    def get_indent(self, parashape_id: int) -> Optional[int]:
        ps = self.parashapes.get(parashape_id)
        return ps.get('indent') if ps else None

    # ── 스타일에서 조회 (charshape/parashape 미지정 시 fallback) ──

    def resolve_charshape_id(self, para: 'ParagraphNode') -> int:
        if para.charshape_id:
            return para.charshape_id
        style = self.styles.get(para.style_id)
        return style.get('charshape', 0) if style else 0

    def resolve_parashape_id(self, para: 'ParagraphNode') -> int:
        if para.parashape_id:
            return para.parashape_id
        style = self.styles.get(para.style_id)
        return style.get('parashape', 0) if style else 0


# ============================================================================
# 내부 헬퍼
# ============================================================================

def _bgr_to_hex(color_value: int) -> Optional[str]:
    """BGR 정수 → #rrggbb (HWP는 BGR 순서)."""
    if color_value is None:
        return None
    b = (color_value >> 16) & 0xFF
    g = (color_value >> 8) & 0xFF
    r = color_value & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_truthy_attr(el: ET.Element, attr: str) -> bool:
    """XML 속성이 참인지 ("1", "true" 등)."""
    val = el.get(attr)
    if val is None:
        return False
    return val.lower() in ('1', 'true', 'yes')


def _strip_ns(tag: str) -> str:
    """XML 네임스페이스 제거: {http://...}TagName → TagName, hp:TagName → TagName."""
    if tag.startswith('{'):
        return tag.split('}', 1)[1]
    if ':' in tag:
        return tag.split(':', 1)[1]
    return tag


def _find_all(el: ET.Element, local_name: str) -> List[ET.Element]:
    """네임스페이스 무관하게 태그명으로 자식 검색."""
    results = []
    for child in el:
        if _strip_ns(child.tag) == local_name:
            results.append(child)
    return results


def _find_first(el: ET.Element, local_name: str) -> Optional[ET.Element]:
    """네임스페이스 무관하게 첫 번째 매칭 자식."""
    for child in el:
        if _strip_ns(child.tag) == local_name:
            return child
    return None


def _find_recursive(el: ET.Element, local_name: str) -> List[ET.Element]:
    """네임스페이스 무관하게 재귀 검색."""
    results = []
    for child in el.iter():
        if _strip_ns(child.tag) == local_name:
            results.append(child)
    return results


def _get_attr(el: ET.Element, *names: str, default: str = '0') -> str:
    """여러 속성명 시도 (HWPML2X vs HWPX 호환)."""
    for name in names:
        val = el.get(name)
        if val is not None:
            return val
    return default


# ============================================================================
# 파싱 함수 — 태그 이름은 _strip_ns로 정규화, 네임스페이스 무관
# ============================================================================

def _extract_paragraph_text_and_runs(
    text_elements: list,
    style_lookup: StyleLookup
) -> Tuple[str, List[Tuple[str, int]]]:
    """TEXT/run 태그들 → (full_text, [(text_segment, charshape_id)])

    HWPML2X: TEXT > CHAR
    HWPX:    run > t
    """
    full_text_parts = []
    text_runs = []
    for text_el in text_elements:
        tag = _strip_ns(text_el.tag)

        # charshape ID 추출
        charshape_id = int(_get_attr(text_el, 'CharShape', 'charPrIDRef'))

        # 텍스트 수집: CHAR (HWPML2X) 또는 t (HWPX)
        segment_parts = []
        for child in text_el:
            child_tag = _strip_ns(child.tag)
            if child_tag in ('CHAR', 't'):
                if child.text:
                    segment_parts.append(child.text)
                # tail text (XML mixed content)
                if child.tail:
                    segment_parts.append(child.tail)

        # 직접 텍스트 (run 태그에 직접 텍스트가 있는 경우)
        if not segment_parts and text_el.text:
            segment_parts.append(text_el.text)

        segment_text = ''.join(segment_parts)
        if segment_text:
            full_text_parts.append(segment_text)
            text_runs.append((segment_text, charshape_id))

    return (''.join(full_text_parts), text_runs)


def _parse_paragraph(
    p_node: ET.Element,
    style_lookup: StyleLookup
) -> ParagraphNode:
    """P/p 태그 → ParagraphNode."""
    para = ParagraphNode()
    para.style_id = int(_get_attr(p_node, 'Style', 'styleIDRef'))
    para.parashape_id = int(_get_attr(p_node, 'ParaShape', 'paraPrIDRef'))
    para.charshape_id = int(_get_attr(p_node, 'CharShape', 'charPrIDRef'))

    # 개요 수준
    heading_type = p_node.get('HeadingType', '')
    if heading_type == 'Outline':
        para.outline_level = int(p_node.get('Level', '0')) + 1

    # 텍스트 런 수집 (TEXT/run)
    text_elements = _find_all(p_node, 'TEXT') + _find_all(p_node, 'run')
    _, text_runs = _extract_paragraph_text_and_runs(text_elements, style_lookup)
    para.text_runs = text_runs

    # 인라인 노드 (표, 이미지, 수식, 텍스트박스)
    para.inline_nodes = []

    for table_el in _find_recursive(p_node, 'TABLE') + _find_recursive(p_node, 'tbl'):
        if table_el in p_node.iter():
            para.inline_nodes.append(_parse_table(table_el, style_lookup))

    for shape_el in _find_all(p_node, 'SHAPEOBJECT') + _find_all(p_node, 'shapeObject'):
        img = ImageNode()
        img.shape_object = shape_el
        para.inline_nodes.append(img)

    # 수식
    for eq_el in _find_recursive(p_node, 'EQUATION') + _find_recursive(p_node, 'equation'):
        eq = EquationNode()
        eq.version = eq_el.get('Version', eq_el.get('version', '2.0'))
        script_el = _find_first(eq_el, 'SCRIPT') or _find_first(eq_el, 'script')
        if script_el is not None and script_el.text:
            eq.script = script_el.text.strip()
        elif eq_el.text:
            eq.script = eq_el.text.strip()
        para.inline_nodes.append(eq)

    # 머리글/바닥글
    hf_el = (_find_first(p_node, 'HEADER') or _find_first(p_node, 'FOOTER')
             or _find_first(p_node, 'header') or _find_first(p_node, 'footer'))
    if hf_el is not None:
        para.header_footer = hf_el

    return para


def _parse_cell(
    cell_el: ET.Element,
    style_lookup: StyleLookup
) -> CellNode:
    """CELL/tc 태그 → CellNode.

    **병합 처리 핵심**:
    - HWPML2X: ColAddr, RowAddr, ColSpan, RowSpan 속성
    - HWPX: cellAddr 자식 태그의 colAddr/rowAddr + 직접 colSpan/rowSpan
    """
    cell = CellNode()

    # HWPML2X 직접 속성
    cell.col_addr = int(_get_attr(cell_el, 'ColAddr', default='0'))
    cell.row_addr = int(_get_attr(cell_el, 'RowAddr', default='0'))
    cell.col_span = int(_get_attr(cell_el, 'ColSpan', default='1'))
    cell.row_span = int(_get_attr(cell_el, 'RowSpan', default='1'))

    # HWPX: cellAddr 자식 태그
    addr_el = _find_first(cell_el, 'cellAddr')
    if addr_el is not None:
        cell.col_addr = int(addr_el.get('colAddr', cell.col_addr))
        cell.row_addr = int(addr_el.get('rowAddr', cell.row_addr))

    # HWPX: cellSz 자식 태그
    sz_el = _find_first(cell_el, 'cellSz') or _find_first(cell_el, 'CELLSZ')
    if sz_el is not None:
        cell.width = int(_get_attr(sz_el, 'width', 'Width', default='0'))
        cell.height = int(_get_attr(sz_el, 'height', 'Height', default='0'))

    # borderFill
    bf_el = _find_first(cell_el, 'cellBorderFill') or _find_first(cell_el, 'CELLBORDERFILL')
    if bf_el is not None:
        cell.border_fill = bf_el.get('borderFillIDRef', bf_el.get('BorderFill'))

    # vertAlign
    va_el = _find_first(cell_el, 'vertAlign')
    if va_el is not None:
        cell.vert_align = va_el.get('val')

    # 문단 파싱
    cell.paragraphs = []
    paralist_el = _find_first(cell_el, 'PARALIST') or _find_first(cell_el, 'subList')
    target = paralist_el if paralist_el is not None else cell_el
    for p_node in _find_all(target, 'P') + _find_all(target, 'p'):
        cell.paragraphs.append(_parse_paragraph(p_node, style_lookup))

    if cell.paragraphs:
        cell.paragraph_charshape_id = cell.paragraphs[0].charshape_id

    return cell


def _parse_table(
    table_el: ET.Element,
    style_lookup: StyleLookup
) -> TableNode:
    """TABLE/tbl 태그 → TableNode.

    병합된 셀 구조를 완전히 보존.
    """
    table = TableNode()
    table.col_count = int(_get_attr(table_el, 'ColCount', 'cols', default='0'))
    table.row_count = int(_get_attr(table_el, 'RowCount', 'rows', default='0'))

    # 캡션
    caption_el = _find_first(table_el, 'CAPTION') or _find_first(table_el, 'caption')
    if caption_el is not None:
        table.caption_side = caption_el.get('Side', caption_el.get('side', 'Bottom'))

    # SHAPEOBJECT
    shape_el = _find_first(table_el, 'SHAPEOBJECT') or _find_first(table_el, 'shapeObject')
    if shape_el is not None:
        table.shape_object = shape_el

    # tblPr (HWPX)
    tblpr_el = _find_first(table_el, 'tblPr')
    if tblpr_el is not None:
        table.col_count = int(tblpr_el.get('cols', table.col_count))
        table.border_fill = tblpr_el.get('borderFillIDRef')
        margin_el = _find_first(tblpr_el, 'cellMargin')
        if margin_el is not None:
            table.cell_spacing = int(margin_el.get('spacing', '0'))

    # 행/셀 파싱
    table.rows = []
    for row_el in _find_all(table_el, 'ROW') + _find_all(table_el, 'tr'):
        row = RowNode()
        for cell_el in _find_all(row_el, 'CELL') + _find_all(row_el, 'tc'):
            row.cells.append(_parse_cell(cell_el, style_lookup))
        table.rows.append(row)

    # 행 수가 명시되지 않았으면 실제 행 수로 설정
    if table.row_count == 0:
        table.row_count = len(table.rows)

    # 열 수가 명시되지 않았으면 첫 행 기반 추정
    if table.col_count == 0 and table.rows:
        table.col_count = sum(c.col_span for c in table.rows[0].cells)

    return table


def _parse_footnote(
    fn_node: ET.Element,
    style_lookup: StyleLookup,
    is_endnote: bool = False
) -> FootnoteNode:
    """각주/미주 태그 → FootnoteNode."""
    fn = FootnoteNode()
    fn.series_num = int(_get_attr(fn_node, 'SeriesNum', default='0'))
    fn.is_endnote = is_endnote

    fn.paragraphs = []
    paralist_el = _find_first(fn_node, 'PARALIST') or _find_first(fn_node, 'subList')
    target = paralist_el if paralist_el is not None else fn_node
    for p_node in _find_all(target, 'P') + _find_all(target, 'p'):
        fn.paragraphs.append(_parse_paragraph(p_node, style_lookup))

    return fn


def _renumber_footnotes(doc: DocNode):
    """각주 번호 전역 재정렬."""
    counter = [0]

    def _visit(node):
        if isinstance(node, FootnoteNode) and not node.is_endnote:
            counter[0] += 1
            node.series_num = counter[0]
        for child in getattr(node, 'children', []):
            _visit(child)
        for child in getattr(node, 'paragraphs', []):
            _visit(child)
        for child in getattr(node, 'inline_nodes', []):
            _visit(child)
        if hasattr(node, 'rows'):
            for row in node.rows:
                for cell in row.cells:
                    _visit(cell)

    _visit(doc)


# ============================================================================
# HEAD 파싱 — StyleLookup 구축
# ============================================================================

def _build_style_lookup(root: ET.Element) -> StyleLookup:
    """HEAD 영역에서 StyleLookup 구축.

    HWPML2X: FONTFACE/CHARSHAPE/PARASHAPE/STYLE 대문자
    HWPX: fontface/charPr/paraPr/style 또는 hh: 접두사
    """
    sl = StyleLookup()

    # --- FONTFACE → fontid_map ---
    for fontface in _find_recursive(root, 'FONTFACE') + _find_recursive(root, 'fontface'):
        lang = fontface.get('Lang', fontface.get('lang', ''))
        for font in _find_all(fontface, 'FONT') + _find_all(fontface, 'font'):
            font_id = int(_get_attr(font, 'Id', 'id'))
            font_name = font.get('Name', font.get('name', font.get('face', '')))
            if lang and font_name:
                sl.fontid_map[(lang, font_id)] = font_name
            # HWPX에서 lang이 대문자 (HANGUL, LATIN 등)
            lang_upper = lang.upper() if lang else ''
            lang_mapped = {
                'HANGUL': 'Hangul', 'LATIN': 'Latin', 'HANJA': 'Hanja',
                'JAPANESE': 'Japanese', 'OTHER': 'Other', 'SYMBOL': 'Symbol',
            }.get(lang_upper)
            if lang_mapped and font_name:
                sl.fontid_map[(lang_mapped, font_id)] = font_name

    # --- CHARSHAPE → charshapes ---
    for cs in _find_recursive(root, 'CHARSHAPE') + _find_recursive(root, 'charPr'):
        cs_id = int(_get_attr(cs, 'Id', 'id'))
        height = int(_get_attr(cs, 'Height', default='0'))
        text_color = int(_get_attr(cs, 'TextColor', default='0'))

        # FONTID (HWPML2X) or fontRef (HWPX)
        fontid_el = _find_first(cs, 'FONTID') or _find_first(cs, 'fontRef')
        hangul_id = 0
        font_ids: Dict[str, int] = {}
        if fontid_el is not None:
            for lang_attr in ('Hangul', 'Hanja', 'Japanese', 'Latin', 'Other', 'Symbol', 'User',
                              'hangul', 'hanja', 'japanese', 'latin', 'other', 'symbol', 'user'):
                val = fontid_el.get(lang_attr)
                if val is not None:
                    canonical_lang = lang_attr.capitalize()
                    font_ids[canonical_lang] = int(val)
            hangul_id = font_ids.get('Hangul', 0)

        # HWPX fontSz
        fontsz_el = _find_first(cs, 'fontSz')
        if fontsz_el is not None and height == 0:
            height = int(fontsz_el.get('val', '0'))

        bold = (_find_first(cs, 'BOLD') is not None
                or _find_first(cs, 'bold') is not None
                or _is_truthy_attr(cs, 'bold'))
        italic = (_find_first(cs, 'ITALIC') is not None
                  or _find_first(cs, 'italic') is not None
                  or _is_truthy_attr(cs, 'italic'))
        underline = (_find_first(cs, 'UNDERLINE') is not None
                     or _find_first(cs, 'underline') is not None)
        strikeout = (_find_first(cs, 'STRIKEOUT') is not None
                     or _find_first(cs, 'strikeout') is not None)

        sl.charshapes[cs_id] = {
            'height': height,
            'text_color': text_color,
            'fontid_hangul': hangul_id,
            'font_ids': font_ids,
            'bold': bold,
            'italic': italic,
            'underline': underline,
            'strikeout': strikeout,
        }

    # --- PARASHAPE → parashapes ---
    for ps in _find_recursive(root, 'PARASHAPE') + _find_recursive(root, 'paraPr'):
        ps_id = int(_get_attr(ps, 'Id', 'id'))
        align = ps.get('Align', 'Justify')

        # HWPX: align 자식 태그
        align_el = _find_first(ps, 'align')
        if align_el is not None:
            align = align_el.get('val', align)

        # 줄간격
        margin_el = _find_first(ps, 'PARAMARGIN') or _find_first(ps, 'margin')
        line_spacing = 160
        indent = 0
        space_before = 0
        space_after = 0
        if margin_el is not None:
            line_spacing = int(_get_attr(margin_el, 'LineSpacing', 'lineSpacing', default='160'))
            indent = int(_get_attr(margin_el, 'Indent', 'indent', default='0'))
            space_before = int(_get_attr(margin_el, 'SpaceBefore', 'prev', default='0'))
            space_after = int(_get_attr(margin_el, 'SpaceAfter', 'next', default='0'))

        # HWPX: lineSpacing 자식 태그
        ls_el = _find_first(ps, 'lineSpacing')
        if ls_el is not None:
            ls_val = ls_el.get('val')
            if ls_val:
                line_spacing = int(ls_val)

        sl.parashapes[ps_id] = {
            'align': align,
            'line_spacing': line_spacing,
            'indent': indent,
            'space_before': space_before,
            'space_after': space_after,
        }

    # --- STYLE → styles ---
    for style in _find_recursive(root, 'STYLE') + _find_recursive(root, 'style'):
        s_id = int(_get_attr(style, 'Id', 'id'))
        sl.styles[s_id] = {
            'name': style.get('Name', style.get('name', '')),
            'charshape': int(_get_attr(style, 'CharShape', 'charPrIDRef')),
            'parashape': int(_get_attr(style, 'ParaShape', 'paraPrIDRef')),
        }

    return sl


# ============================================================================
# BODY 파싱
# ============================================================================

def _parse_body(root: ET.Element, style_lookup: StyleLookup) -> Optional[BodyNode]:
    """BODY 영역 파싱."""
    body_el = None
    for el in _find_recursive(root, 'BODY'):
        body_el = el
        break
    if body_el is None:
        for el in _find_recursive(root, 'sec'):
            # HWPX section0.xml은 <hs:sec>이 루트
            body = BodyNode()
            section = SectionNode()
            section.section_def = el.attrib

            # secPr (페이지 설정)
            secpr_el = _find_first(el, 'secPr') or _find_first(el, 'SECPR')
            if secpr_el is not None:
                section.section_def = secpr_el.attrib

            for p_node in _find_all(el, 'P') + _find_all(el, 'p'):
                section.children.append(_parse_paragraph(p_node, style_lookup))

            # 표도 section 직접 자식일 수 있음
            for tbl_el in _find_all(el, 'TABLE') + _find_all(el, 'tbl'):
                section.children.append(_parse_table(tbl_el, style_lookup))

            body.children.append(section)
            return body
        return None

    body = BodyNode()
    for section_el in _find_all(body_el, 'SECTION') + _find_all(body_el, 'sec'):
        section = SectionNode()
        section.section_def = section_el.attrib

        for p_node in _find_all(section_el, 'P') + _find_all(section_el, 'p'):
            section.children.append(_parse_paragraph(p_node, style_lookup))

        body.children.append(section)

    return body


# ============================================================================
# 메인 파싱 함수
# ============================================================================

def parse_hwpml2x(xml_text: str) -> DocNode:
    """HWPML2X 또는 HWPX XML → DocNode 트리.

    HWPML2X (COM GetTextFile/SaveAs): 대문자 태그 (P, TEXT, CHAR, TABLE)
    HWPX (section0.xml): 네임스페이스 접두사 (hp:p, hp:run, hp:t, hp:tbl)

    양쪽 모두 _strip_ns()로 태그를 정규화하여 동일 로직으로 처리.
    """
    root = ET.fromstring(xml_text)
    doc = DocNode()

    # HEAD → StyleLookup
    style_lookup = _build_style_lookup(root)
    doc.style_lookup = style_lookup

    # BODY → 노드 트리
    body = _parse_body(root, style_lookup)
    if body:
        doc.children.append(body)

    _renumber_footnotes(doc)
    return doc


def parse_hwpx_section(xml_text: str, header_xml: Optional[str] = None) -> DocNode:
    """HWPX section XML 파싱 (header.xml에서 스타일 정보 로드 가능).

    확장성: HWPX ZIP에서 header.xml + section0.xml을 별도로 읽어 합칠 때 사용.
    """
    doc = DocNode()

    # header.xml이 있으면 먼저 스타일 구축
    if header_xml:
        header_root = ET.fromstring(header_xml)
        doc.style_lookup = _build_style_lookup(header_root)
    else:
        doc.style_lookup = StyleLookup()

    # section XML 파싱
    section_root = ET.fromstring(xml_text)

    # section_root 자체에서 추가 스타일 추출 (있을 경우 병합)
    additional_sl = _build_style_lookup(section_root)
    if additional_sl.charshapes:
        doc.style_lookup.charshapes.update(additional_sl.charshapes)
    if additional_sl.parashapes:
        doc.style_lookup.parashapes.update(additional_sl.parashapes)
    if additional_sl.fontid_map:
        doc.style_lookup.fontid_map.update(additional_sl.fontid_map)

    body = _parse_body(section_root, doc.style_lookup)
    if body:
        doc.children.append(body)

    _renumber_footnotes(doc)
    return doc
