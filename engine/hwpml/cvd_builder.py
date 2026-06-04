"""
블록 트리 → CVD (Compact Visual Document) 텍스트 변환.

CVD는 LLM이 문서 구조를 이해할 수 있는 텍스트 포맷:
  <scanned_page_range>1 ~ 5 페이지</scanned_page_range>
  <style_info>
    <font_size_info>16pt: 1, 5\nThe rest blocks are 10pt.</font_size_info>
  </style_info>
  <main_content>
    <1>첫 문단
    <table><tr><td 3 colspan="2"><4>셀 내용</td></tr></table>
    <equation 7>x^2 + y^2 = r^2
  </main_content>

핵심 특징:
  - "Dominant + Exception" 스타일 인코딩: 가장 흔한 스타일을 기본값으로,
    나머지만 블록 ID 범위와 함께 표시
  - 셀 병합 정보(colspan/rowspan)를 HTML 속성으로 표현
  - 수식 스크립트 원문 보존

참조: Inline AI v0.3.1 cvd_builder.py (362 식별자)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .parser import StyleLookup


# ── 내부 헬퍼 ──────────────────────────────────────────

def _compress_id_ranges(ids: list) -> str:
    """블록 ID 리스트 → 범위 압축 ("1, 3 ~ 5, 8")."""
    if not ids:
        return ""
    sorted_ids = sorted(int(i) for i in ids if i is not None)
    if not sorted_ids:
        return ""
    ranges = []
    start = end = sorted_ids[0]
    for i in sorted_ids[1:]:
        if i == end + 1:
            end = i
        else:
            ranges.append(str(start) if start == end else f"{start} ~ {end}")
            start = end = i
    ranges.append(str(start) if start == end else f"{start} ~ {end}")
    return ', '.join(ranges)


def _page_label(page: int) -> str:
    return f"[{page}페이지]"


# ── 스타일 수집 ────────────────────────────────────────

def _collect_style_stats(
    blocks: List[dict], style_lookup: Optional[StyleLookup]
) -> Tuple[dict, dict, dict, dict]:
    """블록별 스타일 통계 수집.

    Returns: (font_sizes, font_families, align_types, bold_blocks)
    """
    font_sizes: Dict[float, list] = {}
    font_families: Dict[str, list] = {}
    align_types: Dict[str, list] = {}
    bold_blocks: List[int] = []

    if not style_lookup:
        return font_sizes, font_families, align_types, bold_blocks

    for block in blocks:
        bid = block.get('block_id')
        if block.get('block_type') in ('td', 'header_footer', 'footnote_anchor'):
            continue

        cs_id = block.get('charshape_id', 0)
        ps_id = block.get('parashape_id', 0)

        size_pt = style_lookup.get_font_size_pt(cs_id)
        if size_pt and size_pt > 0:
            font_sizes.setdefault(size_pt, []).append(bid)

        family = style_lookup.get_font_family(cs_id)
        if family:
            font_families.setdefault(family, []).append(bid)

        align = style_lookup.get_align(ps_id)
        if align:
            align_types.setdefault(align, []).append(bid)

        if style_lookup.get_bold(cs_id):
            bold_blocks.append(bid)

    return font_sizes, font_families, align_types, bold_blocks


# ── 표 렌더링 (병합 핵심) ──────────────────────────────

def _render_table(
    blocks: List[dict],
    start_idx: int,
    id_to_page: dict,
    all_blocks_map: Dict[int, dict],
) -> Tuple[List[str], int]:
    """연속 td 블록 → <table> HTML.

    병합 처리: colspan/rowspan 속성을 정확히 표현.
    """
    lines = ["<table>"]
    i = start_idx
    current_row = None
    first_table_group = blocks[start_idx].get('table_group_id')

    while i < len(blocks):
        block = blocks[i]

        # 다른 표이거나 td가 아니면 종료
        if block.get('block_type') != 'td':
            break
        if block.get('table_group_id') != first_table_group:
            break

        row_addr = block.get('row_addr', 0)
        if current_row != row_addr:
            if current_row is not None:
                lines.append("</tr>")
            lines.append("<tr>")
            current_row = row_addr

        bid = block['block_id']
        col_span = block.get('col_span', 1)
        row_span = block.get('row_span', 1)

        # td 속성 구성
        td_attrs = str(bid)
        if col_span > 1:
            td_attrs += f' colspan="{col_span}"'
        if row_span > 1:
            td_attrs += f' rowspan="{row_span}"'

        # 셀 내 콘텐츠 수집
        cell_list_id = block.get('list_id')
        cell_content_parts = []
        j = i + 1
        while j < len(blocks):
            nb = blocks[j]
            if nb.get('list_id') == cell_list_id and nb.get('block_type') != 'td':
                nb_bid = nb.get('block_id', '')
                nb_text = nb.get('text', '')
                nb_type = nb.get('block_type', 'text')
                if nb_type == 'equation':
                    cell_content_parts.append(f"<eq {nb_bid}>{nb_text}")
                else:
                    cell_content_parts.append(f"<{nb_bid}>{nb_text}")
                j += 1
            else:
                break

        content = ''.join(cell_content_parts)
        lines.append(f"  <td {td_attrs}>{content}</td>")
        i = j
        continue

    if current_row is not None:
        lines.append("</tr>")
    lines.append("</table>")

    consumed = i - start_idx
    return lines, consumed


# ── 메인 빌드 함수 ────────────────────────────────────

def build_cvd(
    blocks: List[dict],
    id_to_pos: Optional[Dict] = None,
    style_lookup: Optional[StyleLookup] = None,
    id_to_page: Optional[Dict] = None,
    page_range: Optional[Tuple[int, int]] = None,
    file_name: str = "",
    **kwargs,
) -> str:
    """블록 리스트 → CVD 텍스트.

    Args:
        blocks: PositionEngine.process_body()의 출력
        id_to_pos: blockId → (list_pos, para_pos, char_pos)
        style_lookup: StyleLookup 인스턴스
        id_to_page: blockId → 페이지 번호 (COM 캘리브레이션 결과)
        page_range: (min_page, max_page)
        file_name: 문서 파일명
    """
    if id_to_pos is None:
        id_to_pos = {}
    if id_to_page is None:
        id_to_page = {}

    min_page = page_range[0] if page_range else 1
    max_page = page_range[1] if page_range else max(id_to_page.values(), default=1)
    current_page = min_page

    lines: List[str] = []

    # ── 1. 페이지 범위 헤더 ──
    lines.append(f"<scanned_page_range>{min_page} ~ {max_page} 페이지</scanned_page_range>")
    lines.append("")

    # ── 2. 스타일 정보 (Dominant + Exception) ──
    font_sizes, font_families, align_types, bold_blocks = _collect_style_stats(
        blocks, style_lookup
    )

    lines.append("<style_info>")

    if font_sizes:
        lines.append("<font_size_info>")
        dominant_size = max(font_sizes.items(), key=lambda x: len(x[1]))
        for size, bids in sorted(font_sizes.items()):
            if size != dominant_size[0]:
                lines.append(f"{size}pt: {_compress_id_ranges(bids)}")
        lines.append(f"The rest blocks are {dominant_size[0]}pt.")
        lines.append("</font_size_info>")

    if font_families and len(font_families) > 1:
        lines.append("<font_family_info>")
        dominant_family = max(font_families.items(), key=lambda x: len(x[1]))
        for family, bids in sorted(font_families.items()):
            if family != dominant_family[0]:
                lines.append(f"{family}: {_compress_id_ranges(bids)}")
        lines.append(f'The rest blocks use "{dominant_family[0]}".')
        lines.append("</font_family_info>")

    if align_types:
        lines.append("<para_align_info>")
        dominant_align = max(align_types.items(), key=lambda x: len(x[1]))
        for align, bids in sorted(align_types.items()):
            if align != dominant_align[0]:
                lines.append(f"{align}: {_compress_id_ranges(bids)}")
        lines.append(f'The rest blocks are "{dominant_align[0]}".')
        lines.append("</para_align_info>")

    if bold_blocks:
        lines.append(f"<bold_info>Bold: {_compress_id_ranges(bold_blocks)}</bold_info>")

    lines.append("</style_info>")
    lines.append("")

    # ── 3. 블록 분류 ──
    main_blocks = [b for b in blocks if b.get('block_type') != 'header_footer']
    hf_blocks = [b for b in blocks if b.get('block_type') == 'header_footer']

    # ── 4. 메인 콘텐츠 렌더링 ──
    lines.append("<main_content>")
    all_blocks_map = {b.get('block_id'): b for b in blocks}

    i = 0
    while i < len(main_blocks):
        block = main_blocks[i]
        btype = block.get('block_type', 'text')
        bid = block.get('block_id', '')
        text = block.get('text', '')

        # 페이지 마커
        block_page = id_to_page.get(bid, current_page)
        if block_page > current_page:
            current_page = block_page
            lines.append(_page_label(block_page))

        if btype == 'text':
            outline = block.get('outline_level', 0)
            if outline > 0:
                lines.append(f"<h{outline} {bid}>{text}")
            else:
                lines.append(f"<{bid}>{text}")

        elif btype == 'td':
            table_lines, skip = _render_table(
                main_blocks, i, id_to_page, all_blocks_map
            )
            lines.extend(table_lines)
            i += skip
            continue

        elif btype == 'footnote_anchor':
            fn_num = block.get('footnote_num', 0)
            fn_type = "미주" if block.get('is_endnote') else "각주"
            content_parts = []
            j = i + 1
            while j < len(main_blocks):
                nb = main_blocks[j]
                if (nb.get('block_type') == 'footnote_content'
                        and nb.get('footnote_num') == fn_num):
                    content_parts.append(f"<{nb['block_id']}>{nb.get('text', '')}")
                    j += 1
                else:
                    break
            first_content = content_parts[0] if content_parts else ""
            lines.append(f"<{fn_type}{fn_num} {bid}>{first_content}")
            lines.extend(content_parts[1:])
            i = j
            continue

        elif btype == 'equation':
            lines.append(f"<equation {bid}>{text}")

        elif btype == 'image':
            lines.append(f"<image {bid}>")

        elif btype == 'textbox':
            content_list_id = block.get('content_list_id')
            tb_content = []
            j = i + 1
            while j < len(main_blocks):
                nb = main_blocks[j]
                if nb.get('list_id') == content_list_id:
                    tb_content.append(f"<{nb.get('block_id', '')}>{nb.get('text', '')}")
                    j += 1
                else:
                    break
            first = tb_content[0] if tb_content else ""
            lines.append(f"<textbox {bid}>{first}")
            lines.extend(tb_content[1:])
            i = j
            continue

        elif btype == 'footnote_content':
            pass  # footnote_anchor에서 처리됨

        i += 1

    lines.append("</main_content>")

    return '\n'.join(lines)


# ── 유틸리티 ──

def build_cvd_from_doc(
    doc: 'DocNode',
    id_to_page: Optional[Dict] = None,
    page_range: Optional[Tuple[int, int]] = None,
    file_name: str = "",
) -> str:
    """편의 함수: DocNode → CVD (파싱 + 포지션 + 빌드 한번에).

    확장성: 외부 모듈에서 단일 호출로 CVD 생성.
    """
    from .position_engine import PositionEngine

    engine = PositionEngine()
    blocks, id_to_pos = engine.process_body(doc)

    return build_cvd(
        blocks=blocks,
        id_to_pos=id_to_pos,
        style_lookup=doc.style_lookup,
        id_to_page=id_to_page,
        page_range=page_range,
        file_name=file_name,
    )
