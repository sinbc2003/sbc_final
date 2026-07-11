"""HwpEditor — blockId 기반 편집 명령 실행."""

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

from engine.hwp.models import Block, DocumentInfo
from engine.hwp.blocks import BlockManager
from engine.hwp.scanner import DocumentScanner


class HwpEditor:
    """blockId 기반 HWP 문서 편집. Inline AI hwp_editor.py의 핵심 패턴 구현."""

    def __init__(self, hwp, block_manager: BlockManager):
        self.hwp = hwp
        self.bm = block_manager
        self._edited_blocks: set = set()
        self._needs_rescan = False

    def _rescan_if_needed(self):
        """구조 변경 후 블록맵 갱신. 좌표 밀림 방지.

        HWPML 모드 우선, 실패 시 커서 모드 폴백.
        """
        if not self._needs_rescan:
            return
        try:
            scanner = DocumentScanner(self.hwp)

            # HWPML 스캔 우선 시도
            if _HWPML_AVAILABLE:
                hwpml_result = scanner.scan_hwpml()
                if hwpml_result:
                    self.bm.initialize_from_blocks(
                        hwpml_result["blocks"], hwpml_result["id_to_pos"]
                    )
                    try:
                        self.bm.calibrate_with_scan(scanner.raw_scan())
                    except Exception as e:
                        logger.warning(f"리스캔 td 캘리브레이션 건너뜀: {e}")
                    self._needs_rescan = False
                    logger.info(f"HWPML 리스캔 완료: {len(hwpml_result['blocks'])}개 블록")
                    return

            # 커서 폴백
            elements = scanner.scan()
            self.bm.initialize_from_scan(elements)
            self._needs_rescan = False
            logger.info(f"커서 리스캔 완료: {len(elements)}개 블록")
        except Exception as e:
            logger.warning(f"리스캔 실패: {e}")

    def _move_to_block(self, block_id: str, expect_cell: bool = False) -> dict | None:
        """block_id 위치로 커서 이동. td는 테이블 탐색 우선, 실패 시 set_pos 폴백."""
        block = self.bm.blocks.get(str(block_id))
        if not block:
            logger.warning(f"_move_to_block({block_id}): NOT FOUND in bm ({len(self.bm.blocks)}개 블록)")
            return {"isSuccess": False, "message": f"blockId {block_id} not found"}

        logger.debug(f"_move_to_block({block_id}): type={block.block_type}, table={block.table_idx}, "
                     f"seq={block.cell_seq}, pos={block.position}, cal={block.calibrated}")

        # 캘리브레이션된 실좌표가 있으면 set_pos가 가장 정확 (InitScan 검산 통과)
        if block.calibrated:
            try:
                if self.hwp.set_pos(*block.position) and (
                        not expect_cell or self.hwp.is_cell()):
                    return None  # 성공
                logger.warning(f"_move_to_block({block_id}): 캘리브레이션 좌표 실패 — 우회 탐색")
            except Exception as e:
                logger.warning(f"_move_to_block({block_id}): 캘리브레이션 set_pos 예외: {e}")

        # td 블록이고 table_idx/cell_seq가 있으면 순서 기반 탐색
        if block.block_type == "td" and block.table_idx is not None and block.cell_seq is not None:
            try:
                result = self.hwp.get_into_nth_table(block.table_idx)
                in_cell = self.hwp.is_cell()
                if result or in_cell:
                    for i in range(block.cell_seq):
                        self.hwp.TableRightCell()
                    if self.hwp.is_cell():
                        return None  # 성공
                    logger.warning(f"_move_to_block({block_id}): TableRightCell {block.cell_seq}회 후 is_cell=False")
                else:
                    logger.warning(f"_move_to_block({block_id}): get_into_nth_table({block.table_idx}) 실패")
            except Exception as e:
                logger.warning(f"테이블 탐색 실패 (table={block.table_idx}, seq={block.cell_seq}): {e}")

        # 폴백: set_pos
        self.hwp.set_pos(*block.position)

        if expect_cell and not self.hwp.is_cell():
            logger.warning(f"_move_to_block({block_id}): 좌표 밀림 감지, 리스캔")
            self._needs_rescan = True
            self._rescan_if_needed()
            block = self.bm.blocks.get(str(block_id))
            if not block:
                return {"isSuccess": False, "message": f"blockId {block_id} 리스캔 후 미발견"}
            # 리스캔 후 테이블 탐색 재시도
            if block.table_idx is not None and block.cell_seq is not None:
                try:
                    self.hwp.get_into_nth_table(block.table_idx)
                    for _ in range(block.cell_seq):
                        self.hwp.TableRightCell()
                    if self.hwp.is_cell():
                        logger.info(f"_move_to_block({block_id}): 리스캔 후 성공")
                        return None
                except Exception as e:
                    logger.warning(f"리스캔 후 테이블 탐색 실패: {e}")
            self.hwp.set_pos(*block.position)
            if not self.hwp.is_cell():
                logger.error(f"_move_to_block({block_id}): 최종 실패 — 셀 위치 불일치")
                return {"isSuccess": False, "message": f"blockId {block_id} 셀 위치 불일치"}

        return None  # 성공

    # ── 핵심 편집 메서드 ──

    def replace_cell_content(self, block_id: str, new_text: str) -> dict:
        """표 셀 내용 교체."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err

        try:
            self.hwp.SelectAll()
            self.hwp.insert_text(new_text or " ")

            self.bm.update_text(block_id, new_text or "")
            self._edited_blocks.add(block_id)

            return {"isSuccess": True, "message": "셀 내용 교체 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def replace_paragraph(self, block_id: str, new_text: str) -> dict:
        """문단 내용 교체."""
        self._rescan_if_needed()
        pos = self.bm.get_position(block_id)
        if not pos:
            return {"isSuccess": False, "message": f"blockId {block_id} not found"}

        try:
            self.hwp.set_pos(*pos)
            old_text = self.bm.get_text(block_id) or ""

            if old_text:
                # 기존 텍스트 찾아 교체
                self.hwp.MoveParaBegin()
                self.hwp.MoveSelParaEnd()
                self.hwp.insert_text(new_text or " ")
            else:
                # 빈 문단에 삽입
                self.hwp.insert_text(new_text or " ")

            self.bm.update_text(block_id, new_text or "")
            self._edited_blocks.add(block_id)

            return {"isSuccess": True, "message": "문단 교체 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def append_paragraph(self, block_id: str, new_text: str) -> dict:
        """문단 뒤에 새 문단 삽입."""
        self._rescan_if_needed()
        adj_pos = self.bm.get_adjusted_position(block_id)
        pos = adj_pos or self.bm.get_position(block_id)
        if not pos:
            return {"isSuccess": False, "message": f"blockId {block_id} not found"}

        try:
            self.hwp.set_pos(*pos)
            self.hwp.MoveParaEnd()
            self.hwp.BreakPara()
            self.hwp.insert_text(new_text or " ")

            # 증분 오프셋 추적 (전체 리스캔 대신)
            self.bm.record_insertion(block_id, 1)
            return {"isSuccess": True, "message": "문단 추가 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def delete_cell_content(self, block_id: str) -> dict:
        """셀 내용 삭제 (셀 자체는 유지)."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err

        try:
            self.hwp.SelectAll()
            self.hwp.Delete()
            self.bm.update_text(block_id, "")

            return {"isSuccess": True, "message": "셀 내용 삭제 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def find_and_replace_all(self, old_text: str, new_text: str) -> dict:
        """전체 문서 찾아 바꾸기."""
        try:
            act = self.hwp.HAction
            pset = self.hwp.HParameterSet.HFindReplace

            act.GetDefault("AllReplace", pset.HSet)
            pset.FindString = old_text
            pset.ReplaceString = new_text
            pset.IgnoreMessage = 1
            pset.FindRegExp = 0
            act.Execute("AllReplace", pset.HSet)

            return {"isSuccess": True, "message": f"'{old_text}' → '{new_text}' 교체 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def insert_text_at_cursor(self, text: str) -> dict:
        """현재 커서 위치에 텍스트 삽입. \\n은 새 문단으로 처리."""
        try:
            parts = text.split("\n")
            for i, part in enumerate(parts):
                if part:
                    self.hwp.insert_text(part)
                if i < len(parts) - 1:
                    self.hwp.BreakPara()
            return {"isSuccess": True, "message": "텍스트 삽입 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def apply_para_style(self, block_id: str, **kwargs) -> dict:
        """문단 서식 적용.

        kwargs: font_size, font_family, align, spacing, indentation
        """
        self._rescan_if_needed()
        pos = self.bm.get_position(block_id)
        if not pos:
            return {"isSuccess": False, "message": f"blockId {block_id} not found"}

        try:
            self.hwp.set_pos(*pos)
            self.hwp.MoveParaBegin()
            self.hwp.MoveSelParaEnd()

            font_size = kwargs.get("font_size")
            font_family = kwargs.get("font_family")
            align = kwargs.get("align")

            if font_size or font_family:
                font_kwargs = {}
                if font_size:
                    font_kwargs["Height"] = float(font_size)
                if font_family:
                    font_kwargs["FaceNameHangul"] = font_family
                    font_kwargs["FaceNameLatin"] = font_family
                self.hwp.set_font(**font_kwargs)

            if align:
                align_map = {
                    "left": "Left", "center": "Center",
                    "right": "Right", "justify": "Justify",
                }
                hwp_align = align_map.get(align.lower(), align)
                self.hwp.set_para(AlignType=hwp_align)

            spacing = kwargs.get("spacing")
            if spacing is not None:
                self.hwp.set_para(LineSpacing=float(spacing))

            indentation = kwargs.get("indentation")
            if indentation is not None:
                self.hwp.set_para(Indentation=float(indentation))

            self.hwp.Cancel()
            return {"isSuccess": True, "message": "서식 적용 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def create_table(self, rows: int, cols: int, data: list = None) -> dict:
        """현재 커서 위치에 표 생성. data가 있으면 셀 내용도 채움.

        data: [[셀1, 셀2, ...], [셀1, 셀2, ...], ...]  (행 × 열)
        """
        try:
            self.hwp.create_table(rows, cols)
            if data:
                # 표 생성 후 첫 셀에 커서 위치 → Tab으로 이동하며 채움
                for r_idx, row in enumerate(data):
                    for c_idx, cell_text in enumerate(row):
                        if cell_text:
                            self.hwp.insert_text(str(cell_text))
                        # 마지막 셀이 아니면 다음 셀로 이동
                        if not (r_idx == len(data) - 1 and c_idx == len(row) - 1):
                            self.hwp.TableRightCell()
            filled = f", {sum(len(r) for r in data)}셀 채움" if data else ""
            return {"isSuccess": True, "message": f"{rows}x{cols} 표 생성 완료{filled}"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def style_cell(self, block_id: str, bg_color: str = None,
                   align: str = None, bold: bool = None,
                   font_size: float = None, text_color: str = None) -> dict:
        """표 셀 서식 적용 (배경색, 정렬, 볼드, 글자크기, 글자색)."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err
        try:

            # 배경색
            if bg_color:
                r, g, b = int(bg_color[1:3], 16), int(bg_color[3:5], 16), int(bg_color[5:7], 16)
                self.hwp.cell_fill(rgb=(r, g, b))

            # 셀 내 정렬
            if align:
                align_map = {
                    "left_top": "TableCellAlignLeftTop",
                    "left_center": "TableCellAlignLeftCenter",
                    "left_bottom": "TableCellAlignLeftBottom",
                    "center_top": "TableCellAlignCenterTop",
                    "center_center": "TableCellAlignCenterCenter",
                    "center_bottom": "TableCellAlignCenterBottom",
                    "right_top": "TableCellAlignRightTop",
                    "right_center": "TableCellAlignRightCenter",
                    "right_bottom": "TableCellAlignRightBottom",
                }
                method = align_map.get(align.lower())
                if method and hasattr(self.hwp, method):
                    getattr(self.hwp, method)()

            # 텍스트 서식 (셀 전체 선택 후 적용)
            if bold is not None or font_size or text_color:
                self.hwp.SelectAll()
                font_kwargs = {}
                if bold is not None:
                    font_kwargs["Bold"] = bold
                if font_size:
                    font_kwargs["Height"] = float(font_size)
                if text_color:
                    r, g, b = int(text_color[1:3], 16), int(text_color[3:5], 16), int(text_color[5:7], 16)
                    font_kwargs["TextColor"] = self.hwp.rgb_color(r, g, b)
                if font_kwargs:
                    self.hwp.set_font(**font_kwargs)
                self.hwp.Cancel()

            return {"isSuccess": True, "message": "셀 서식 적용 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def style_row(self, block_id: str, bg_color: str = None,
                  bold: bool = None, font_size: float = None,
                  text_color: str = None, align: str = None) -> dict:
        """표 행 전체에 서식 적용. block_id는 해당 행의 아무 셀."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err
        try:
            # 행 전체 선택
            self.hwp.TableCellBlockRow()

            if bg_color:
                r, g, b = int(bg_color[1:3], 16), int(bg_color[3:5], 16), int(bg_color[5:7], 16)
                self.hwp.cell_fill(rgb=(r, g, b))

            if align:
                align_map = {
                    "center_center": "TableCellAlignCenterCenter",
                    "center_top": "TableCellAlignCenterTop",
                    "left_center": "TableCellAlignLeftCenter",
                }
                method = align_map.get(align.lower(), "TableCellAlignCenterCenter")
                if hasattr(self.hwp, method):
                    getattr(self.hwp, method)()

            if bold is not None or font_size or text_color:
                font_kwargs = {}
                if bold is not None:
                    font_kwargs["Bold"] = bold
                if font_size:
                    font_kwargs["Height"] = float(font_size)
                if text_color:
                    r, g, b = int(text_color[1:3], 16), int(text_color[3:5], 16), int(text_color[5:7], 16)
                    font_kwargs["TextColor"] = self.hwp.rgb_color(r, g, b)
                if font_kwargs:
                    self.hwp.set_font(**font_kwargs)

            self.hwp.Cancel()
            return {"isSuccess": True, "message": "행 서식 적용 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def merge_cells(self, block_id: str, right: int = 0, down: int = 0) -> dict:
        """셀 병합. block_id 위치에서 오른쪽 right칸, 아래 down칸 선택 후 병합."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err
        try:
            self.hwp.TableCellBlock()
            for _ in range(right):
                self.hwp.TableCellBlockExtend()
                self.hwp.TableRightCell()
            # 아래쪽 확장은 별도 처리 필요
            for _ in range(down):
                self.hwp.TableCellBlockExtend()
                self.hwp.TableLowerCell()
            self.hwp.TableMergeCell()
            self.hwp.Cancel()
            self._needs_rescan = True  # 셀 병합 → 좌표 변경
            return {"isSuccess": True, "message": f"셀 병합 완료 (→{right}, ↓{down})"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def set_table_col_width(self, block_id: str, widths: list) -> dict:
        """표 열 너비 설정. block_id는 표 안 아무 셀. widths는 mm 단위 리스트."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err
        try:
            for i, w in enumerate(widths):
                self.hwp.set_col_width(i, w)
            return {"isSuccess": True, "message": f"{len(widths)}개 열 너비 설정 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    # ── 인덱스 기반 테이블 스타일링 (block_id 불필요) ──

    def _navigate_to_table(self, table: int, row: int = 0, col: int = 0) -> bool:
        """표/행/열로 커서 이동. table=1-based, row/col=0-based."""
        try:
            result = self.hwp.get_into_nth_table(table - 1)
            if not result and not self.hwp.is_cell():
                return False
            if row > 0 or col > 0:
                self.hwp.goto_addr(row + 1, col + 1)
            return True
        except Exception as e:
            logger.error(f"테이블 탐색 실패: {e}")
            return False

    def _parse_color(self, hex_color: str):
        """#RRGGBB → (r, g, b) 튜플."""
        return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)

    def style_table_row_idx(self, table: int, row: int,
                            bg_color: str = None, bold: bool = None,
                            font_size: float = None, text_color: str = None,
                            align: str = None) -> dict:
        """인덱스로 표 행 서식 적용. table=1-based, row=0-based."""
        if not self._navigate_to_table(table, row):
            return {"isSuccess": False, "message": f"표{table}의 {row}행을 찾을 수 없음"}
        try:
            # 1) 폰트/정렬 먼저 (행 선택 상태에서)
            if bold is not None or font_size or text_color or align:
                self.hwp.TableCellBlockRow()
                font_kwargs = {}
                if bold is not None:
                    font_kwargs["Bold"] = bold
                if font_size:
                    font_kwargs["Height"] = float(font_size)
                if text_color:
                    r, g, b = self._parse_color(text_color)
                    font_kwargs["TextColor"] = self.hwp.rgb_color(r, g, b)
                if font_kwargs:
                    self.hwp.set_font(**font_kwargs)
                if align:
                    align_map = {
                        "center_center": "TableCellAlignCenterCenter",
                        "center_top": "TableCellAlignCenterTop",
                        "left_center": "TableCellAlignLeftCenter",
                        "left_top": "TableCellAlignLeftTop",
                        "right_center": "TableCellAlignRightCenter",
                        "right_top": "TableCellAlignRightTop",
                    }
                    method = align_map.get(align.lower(), "TableCellAlignCenterCenter")
                    if hasattr(self.hwp, method):
                        getattr(self.hwp, method)()
                self.hwp.Cancel()

            # 2) 배경색 마지막 (cell_fill 내부에서 Cancel 호출됨)
            if bg_color:
                self._navigate_to_table(table, row)
                self.hwp.TableCellBlockRow()
                self.hwp.cell_fill(face_color=self._parse_color(bg_color))

            return {"isSuccess": True, "message": f"표{table} {row}행 서식 적용"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def style_table_cell_idx(self, table: int, row: int, col: int,
                             bg_color: str = None, bold: bool = None,
                             font_size: float = None, text_color: str = None,
                             align: str = None) -> dict:
        """인덱스로 표 셀 서식 적용."""
        if not self._navigate_to_table(table, row, col):
            return {"isSuccess": False, "message": f"표{table}의 [{row},{col}] 셀을 찾을 수 없음"}
        try:
            # 1) 폰트/정렬 먼저
            if bold is not None or font_size or text_color or align:
                self.hwp.TableCellBlock()
                font_kwargs = {}
                if bold is not None:
                    font_kwargs["Bold"] = bold
                if font_size:
                    font_kwargs["Height"] = float(font_size)
                if text_color:
                    r, g, b = self._parse_color(text_color)
                    font_kwargs["TextColor"] = self.hwp.rgb_color(r, g, b)
                if font_kwargs:
                    self.hwp.set_font(**font_kwargs)
                if align:
                    align_map = {
                        "left_top": "TableCellAlignLeftTop",
                        "left_center": "TableCellAlignLeftCenter",
                        "center_center": "TableCellAlignCenterCenter",
                        "center_top": "TableCellAlignCenterTop",
                        "right_center": "TableCellAlignRightCenter",
                        "right_top": "TableCellAlignRightTop",
                    }
                    method = align_map.get(align.lower())
                    if method and hasattr(self.hwp, method):
                        getattr(self.hwp, method)()
                self.hwp.Cancel()

            # 2) 배경색 마지막
            if bg_color:
                self._navigate_to_table(table, row, col)
                self.hwp.TableCellBlock()
                self.hwp.cell_fill(face_color=self._parse_color(bg_color))

            return {"isSuccess": True, "message": f"표{table} [{row},{col}] 셀 서식 적용"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def set_table_widths(self, table: int, widths: list) -> dict:
        """인덱스로 표 열 너비 설정. widths는 비율 리스트 (예: [1,2,3])."""
        if not self._navigate_to_table(table, 0, 0):
            return {"isSuccess": False, "message": f"표{table}을 찾을 수 없음"}
        try:
            self.hwp.set_col_width(widths)
            return {"isSuccess": True, "message": f"표{table} {len(widths)}개 열 너비 설정"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def format_text(self, font_size: float = None, bold: bool = None,
                    align: str = None, text_color: str = None,
                    font_family: str = None) -> dict:
        """현재 커서 위치의 문단 서식 적용 (block_id 불필요)."""
        try:
            self.hwp.MoveParaBegin()
            self.hwp.MoveSelParaEnd()

            font_kwargs = {}
            if bold is not None:
                font_kwargs["Bold"] = bold
            if font_size:
                font_kwargs["Height"] = float(font_size)
            if text_color:
                r, g, b = self._parse_color(text_color)
                font_kwargs["TextColor"] = self.hwp.rgb_color(r, g, b)
            if font_family:
                font_kwargs["FaceName"] = font_family
            if font_kwargs:
                self.hwp.set_font(**font_kwargs)

            if align:
                align_map = {"left": "Left", "center": "Center", "right": "Right", "justify": "Justify"}
                self.hwp.set_para(AlignType=align_map.get(align.lower(), align))

            self.hwp.Cancel()
            return {"isSuccess": True, "message": "텍스트 서식 적용"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def append_table_row(self, block_id: str, row_texts: List[str] = None) -> dict:
        """표에 행 추가 후 텍스트 채우기."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err

        try:
            # 마지막 행으로 이동 후 행 추가
            self.hwp.TableColEnd()
            self.hwp.TableColPageDown()
            self.hwp.TableAppendRow()

            # 새 행의 첫 셀로 이동
            self.hwp.TableColBegin()

            if row_texts:
                for i, text in enumerate(row_texts):
                    self.hwp.insert_text(text or "")
                    if i < len(row_texts) - 1:
                        self.hwp.TableRightCell()

            self._needs_rescan = True  # 행 추가 → 좌표 변경
            return {"isSuccess": True, "message": "행 추가 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def replace_table_row(self, block_id: str, row_texts: List[str] = None) -> dict:
        """표 행의 모든 셀 내용 교체."""
        self._rescan_if_needed()
        err = self._move_to_block(block_id, expect_cell=True)
        if err:
            return err

        try:

            # 행 첫 셀로
            self.hwp.TableColBegin()

            if row_texts:
                for i, text in enumerate(row_texts):
                    self.hwp.SelectAll()
                    self.hwp.insert_text(text or "")
                    if i < len(row_texts) - 1:
                        self.hwp.TableRightCell()

            return {"isSuccess": True, "message": "행 교체 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def save(self) -> dict:
        """문서 저장."""
        try:
            self.hwp.Save()
            return {"isSuccess": True, "message": "저장 완료"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def save_as(self, path: str, fmt: str = "HWPX") -> dict:
        """다른 이름으로 저장."""
        try:
            self.hwp.SaveAs(path, fmt)
            return {"isSuccess": True, "message": f"{fmt}로 저장: {path}"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}
