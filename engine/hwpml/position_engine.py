"""
DocNode → 블록 트리 + blockId 할당 엔진.

핵심 개념:
  - blockId: 각 문서 요소의 고유 정수 ID
  - list_id: 셀/각주/텍스트박스 컨테이너의 고유 ID (0=본문)
  - id_to_pos: {blockId: (list_pos, para_pos, char_pos)}

셀 병합 처리:
  각 CellNode의 col_span/row_span을 블록 메타데이터에 보존하여
  CVD 빌더와 HWPX 빌더에서 정확한 병합 구조를 재현할 수 있게 함.

참조: Inline AI v0.3.1 position_engine.py (317 식별자)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .parser import (
    DocNode, BodyNode, SectionNode, ParagraphNode,
    TableNode, RowNode, CellNode, FootnoteNode,
    ImageNode, TextboxNode, EquationNode,
    StyleLookup,
)


class PositionEngine:
    """HWPML DocNode → (블록 리스트, id_to_pos 매핑).

    블록 리스트의 각 항목:
    {
        'block_id': int,
        'block_type': 'text' | 'td' | 'footnote_anchor' | 'footnote_content' |
                      'image' | 'equation' | 'textbox' | 'header_footer',
        'text': str,
        'list_id': int,
        'para_pos': int,
        'charshape_id': int,
        'parashape_id': int,
        'outline_level': int,
        'text_runs': [(text, charshape_id), ...],
        # td 전용:
        'col_addr': int, 'row_addr': int,
        'col_span': int, 'row_span': int,
        'cell_width': int, 'cell_height': int,
        'table_col_count': int, 'table_row_count': int,
    }
    """

    def __init__(self, start_id: int = 1):
        self.global_id: int = start_id
        self.next_list_id: int = 1
        self.global_para_id: int = 0
        self.id_to_pos: Dict[int, Tuple[int, int, int]] = {}

    def assign_id(self) -> int:
        bid = self.global_id
        self.global_id += 1
        return bid

    def allocate_list_id(self) -> int:
        lid = self.next_list_id
        self.next_list_id += 1
        return lid

    # ── 스타일 해결 ──

    def _resolve_paragraph_style_ids(
        self, para: ParagraphNode, style_lookup: StyleLookup
    ):
        """스타일에서 charshape/parashape ID fallback."""
        if para.style_id and style_lookup and para.style_id in style_lookup.styles:
            style = style_lookup.styles[para.style_id]
            if not para.charshape_id:
                para.charshape_id = style.get('charshape', 0)
            if not para.parashape_id:
                para.parashape_id = style.get('parashape', 0)

    # ── 문단 처리 ──

    def _process_paragraph(
        self, para: ParagraphNode, list_id: int, style_lookup: StyleLookup
    ) -> List[dict]:
        """ParagraphNode → 블록 리스트."""
        blocks = []
        self._resolve_paragraph_style_ids(para, style_lookup)

        # 텍스트 블록
        full_text = para.full_text
        if full_text or not para.inline_nodes:
            bid = self.assign_id()
            pos = (list_id, self.global_para_id, 0)
            self.id_to_pos[bid] = pos
            blocks.append({
                'block_id': bid,
                'block_type': 'text',
                'text': full_text,
                'list_id': list_id,
                'para_pos': self.global_para_id,
                'charshape_id': para.charshape_id,
                'parashape_id': para.parashape_id,
                'outline_level': para.outline_level,
                'text_runs': list(para.text_runs),
            })
            self.global_para_id += 1

        # 인라인 노드
        for inline_node in para.inline_nodes:
            if isinstance(inline_node, TableNode):
                blocks.extend(self._process_table(inline_node, style_lookup))
            elif isinstance(inline_node, ImageNode):
                bid = self.assign_id()
                self.id_to_pos[bid] = (list_id, self.global_para_id, 0)
                blocks.append({
                    'block_id': bid,
                    'block_type': 'image',
                    'list_id': list_id,
                    'bin_data_id': inline_node.bin_data_id,
                    'width': inline_node.width,
                    'height': inline_node.height,
                })
                self.global_para_id += 1
            elif isinstance(inline_node, EquationNode):
                bid = self.assign_id()
                self.id_to_pos[bid] = (list_id, self.global_para_id, 0)
                blocks.append({
                    'block_id': bid,
                    'block_type': 'equation',
                    'text': inline_node.script,
                    'list_id': list_id,
                    'equation_version': inline_node.version,
                })
                self.global_para_id += 1
            elif isinstance(inline_node, TextboxNode):
                bid = self.assign_id()
                tb_list_id = self.allocate_list_id()
                self.id_to_pos[bid] = (list_id, self.global_para_id, 0)
                tb_block = {
                    'block_id': bid,
                    'block_type': 'textbox',
                    'list_id': list_id,
                    'content_list_id': tb_list_id,
                }
                blocks.append(tb_block)
                for tb_para in inline_node.paragraphs:
                    blocks.extend(self._process_paragraph(
                        tb_para, tb_list_id, style_lookup
                    ))
                self.global_para_id += 1
            elif isinstance(inline_node, FootnoteNode):
                blocks.extend(self._process_footnote(inline_node, style_lookup))

        # 머리글/바닥글
        if para.header_footer is not None:
            if not any(b.get('block_type') == 'header_footer' for b in blocks):
                bid = self.assign_id()
                blocks.append({
                    'block_id': bid,
                    'block_type': 'header_footer',
                    'header_footer': para.header_footer,
                })

        return blocks

    # ── 표 처리 (병합 핵심) ──

    def _process_table(
        self, table: TableNode, style_lookup: StyleLookup
    ) -> List[dict]:
        """TableNode → 블록 리스트.

        셀 병합 정보(col_span, row_span)를 각 td 블록에 보존.
        표 전체 메타(col_count, row_count)도 포함하여
        CVD/HWPX 빌더에서 정확한 표 구조 재현 가능.
        """
        blocks = []
        table_group_id = self.allocate_list_id()

        for row_idx, row_node in enumerate(table.rows):
            for cell_node in row_node.cells:
                cell_list_id = self.allocate_list_id()
                td_id = self.assign_id()
                self.id_to_pos[td_id] = (cell_list_id, 0, 0)

                blocks.append({
                    'block_id': td_id,
                    'block_type': 'td',
                    'list_id': cell_list_id,
                    'table_group_id': table_group_id,
                    # 병합 정보 (최우선 요구사항)
                    'col_addr': cell_node.col_addr,
                    'row_addr': cell_node.row_addr,
                    'col_span': cell_node.col_span,
                    'row_span': cell_node.row_span,
                    'is_merged': cell_node.is_merged,
                    # 셀 크기
                    'cell_width': cell_node.width,
                    'cell_height': cell_node.height,
                    # 셀 서식
                    'border_fill': cell_node.border_fill,
                    'vert_align': cell_node.vert_align,
                    # 표 메타
                    'table_col_count': table.col_count,
                    'table_row_count': table.row_count,
                })

                # 셀 내 문단
                for para in cell_node.paragraphs:
                    cell_blocks = self._process_paragraph(
                        para, cell_list_id, style_lookup
                    )
                    blocks.extend(cell_blocks)

                # 빈 셀 최소 블록 보장
                cell_content = [b for b in blocks
                                if b.get('list_id') == cell_list_id
                                and b.get('block_type') != 'td']
                if not cell_content:
                    bid = self.assign_id()
                    self.id_to_pos[bid] = (cell_list_id, 0, 0)
                    blocks.append({
                        'block_id': bid,
                        'block_type': 'text',
                        'text': '',
                        'list_id': cell_list_id,
                        'para_pos': 0,
                    })

        return blocks

    # ── 각주 처리 ──

    def _process_footnote(
        self, fn: FootnoteNode, style_lookup: StyleLookup
    ) -> List[dict]:
        """FootnoteNode → 앵커 블록 + 콘텐츠 블록."""
        blocks = []
        anchor_id = self.assign_id()
        self.id_to_pos[anchor_id] = (0, self.global_para_id, 0)

        fn_list_id = self.allocate_list_id()
        fn_blocks = []
        for para in fn.paragraphs:
            fn_blocks.extend(self._process_paragraph(
                para, fn_list_id, style_lookup
            ))

        blocks.append({
            'block_id': anchor_id,
            'block_type': 'footnote_anchor',
            'footnote_num': fn.series_num,
            'is_endnote': fn.is_endnote,
            'anchor_id': anchor_id,
        })

        for fb in fn_blocks:
            fb['block_type'] = 'footnote_content'
            fb['footnote_num'] = fn.series_num
            fb['anchor_id'] = anchor_id
            blocks.append(fb)

        return blocks

    # ── 메인 진입점 ──

    def process_body(self, doc: DocNode) -> Tuple[List[dict], Dict[int, Tuple[int, int, int]]]:
        """DocNode → (블록 리스트, id_to_pos).

        모든 섹션의 모든 자식 노드를 순회하여 블록으로 변환.
        """
        all_blocks = []
        style_lookup = doc.style_lookup or StyleLookup()

        for body in doc.children:
            if not hasattr(body, 'children'):
                continue
            for section in body.children:
                if not hasattr(section, 'children'):
                    continue
                for child in section.children:
                    if isinstance(child, ParagraphNode):
                        all_blocks.extend(
                            self._process_paragraph(child, 0, style_lookup)
                        )
                    elif isinstance(child, TableNode):
                        all_blocks.extend(
                            self._process_table(child, style_lookup)
                        )

        return (all_blocks, dict(self.id_to_pos))


# ── 유틸리티 함수 ──

def extract_blocks_and_positions(
    doc: DocNode, start_id: int = 1
) -> Tuple[List[dict], Dict[int, Tuple[int, int, int]]]:
    """편의 함수: DocNode → (블록 리스트, id_to_pos)."""
    engine = PositionEngine(start_id=start_id)
    return engine.process_body(doc)


def extract_table_merge_map(blocks: List[dict]) -> Dict[int, Dict[Tuple[int, int], dict]]:
    """블록 리스트에서 표별 병합 맵 추출.

    Returns: {table_group_id: {(row, col): td_block}}

    확장성: HWPX 빌더에서 표 구조 재현 시 사용.
    """
    table_map: Dict[int, Dict[Tuple[int, int], dict]] = {}
    for block in blocks:
        if block.get('block_type') != 'td':
            continue
        tg = block.get('table_group_id')
        if tg is None:
            continue
        row = block.get('row_addr', 0)
        col = block.get('col_addr', 0)
        table_map.setdefault(tg, {})[(row, col)] = block
    return table_map
