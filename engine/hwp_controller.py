"""
HWP 실시간 제어 모듈 — pyhwpx 기반.

Inline AI 역공학 분석을 바탕으로 구현한 HWP COM 제어 시스템.
기존 live_controller.py의 HWP 부분을 완전히 대체.

핵심 구조:
  HwpController        — COM 연결/해제, 문서 상태 폴링
  DocumentScanner      — 문서 스캔 → CVD(블록+위치) 추출
  BlockManager         — blockId ↔ 위치 매핑, 삽입 추적
  HwpEditor            — blockId 기반 편집 명령 실행

사용법:
    ctrl = HwpController()
    ctrl.connect()                          # 실행 중인 한/글에 연결
    info = ctrl.get_document_info()         # 문서 상태
    cvd  = ctrl.extract_cvd()              # 문서 구조 추출
    ctrl.execute("replace_cell_content", block_id="102", new_text="새 내용")
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# HWPML 모듈 (Phase 2)
try:
    from .hwpml import (
        parse_hwpml2x,
        PositionEngine,
        build_cvd,
        extract_table_merge_map,
        StyleLookup,
    )
    from .hwpml.com_retry import com_retry, is_transient_com_error
    _HWPML_AVAILABLE = True
except ImportError:
    _HWPML_AVAILABLE = False


# ── 데이터 클래스 ─────────────────────────────────────

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



# ── BlockManager ──────────────────────────────────────

class BlockManager:
    """블록 위치-텍스트 매핑 관리. CVD에서 초기화."""

    def __init__(self):
        self.blocks: Dict[str, Block] = {}
        self._insertion_offsets: Dict[int, Dict[int, int]] = {}  # {list_pos: {para_pos: count}}
        self._table_groups: Dict[int, List[str]] = {}  # group_id → [block_ids]
        self._scan_mode: str = "cursor"  # "cursor" | "hwpml"

    def initialize_from_scan(self, elements: List[dict]):
        """커서 스캔 결과로 초기화."""
        self.blocks.clear()
        self._table_groups.clear()
        self._insertion_offsets.clear()
        self._scan_mode = "cursor"

        for elem in elements:
            bid = str(elem["id"])
            pos = tuple(elem["position"])
            self.blocks[bid] = Block(
                id=bid,
                position=pos,
                text=elem.get("text", ""),
                block_type=elem.get("type", "text"),
                table_group_id=elem.get("table_group_id"),
                table_idx=elem.get("table_idx"),
                cell_seq=elem.get("cell_seq"),
            )
            gid = elem.get("table_group_id")
            if gid is not None:
                self._table_groups.setdefault(gid, []).append(bid)

    def initialize_from_blocks(self, blocks: List[dict], id_to_pos: Dict[int, Tuple[int, int, int]]):
        """PositionEngine 블록 리스트로 초기화 (HWPML 모드).

        병합 정보, 스타일 참조 등 HWPML에서만 얻을 수 있는 메타데이터를 보존.
        """
        self.blocks.clear()
        self._table_groups.clear()
        self._insertion_offsets.clear()
        self._scan_mode = "hwpml"

        table_idx_map: Dict[int, int] = {}  # table_group_id → sequential index
        cell_seq_map: Dict[int, int] = {}   # table_group_id → cell counter

        for block in blocks:
            bid = str(block.get('block_id', ''))
            btype = block.get('block_type', 'text')
            pos = id_to_pos.get(block.get('block_id'), (0, 0, 0))

            tg = block.get('table_group_id')
            t_idx = None
            c_seq = None
            if tg is not None and btype == 'td':
                if tg not in table_idx_map:
                    table_idx_map[tg] = len(table_idx_map)
                    cell_seq_map[tg] = 0
                t_idx = table_idx_map[tg]
                c_seq = cell_seq_map[tg]
                cell_seq_map[tg] += 1

            self.blocks[bid] = Block(
                id=bid,
                position=pos,
                text=block.get('text', ''),
                block_type=btype,
                table_group_id=tg,
                table_idx=t_idx,
                cell_seq=c_seq,
                col_addr=block.get('col_addr'),
                row_addr=block.get('row_addr'),
                col_span=block.get('col_span', 1),
                row_span=block.get('row_span', 1),
                charshape_id=block.get('charshape_id', 0),
                parashape_id=block.get('parashape_id', 0),
                outline_level=block.get('outline_level', 0),
            )
            if tg is not None:
                self._table_groups.setdefault(tg, []).append(bid)

    # ── 삽입 오프셋 추적 ──

    def record_insertion(self, block_id: str, para_count: int = 1):
        """블록 뒤에 para_count개 문단이 삽입됨을 기록."""
        block = self.blocks.get(str(block_id))
        if not block:
            return
        lp, pp, _ = block.position
        offsets = self._insertion_offsets.setdefault(lp, {})
        offsets[pp] = offsets.get(pp, 0) + para_count

    def get_adjusted_position(self, block_id: str) -> Optional[Tuple[int, int, int]]:
        """삽입 오프셋을 적용한 보정 위치 반환."""
        block = self.blocks.get(str(block_id))
        if not block:
            return None
        lp, pp, cp = block.position
        offset = 0
        for ref_pp, count in self._insertion_offsets.get(lp, {}).items():
            if ref_pp < pp:
                offset += count
        return (lp, pp + offset, cp)

    def get_position(self, block_id: str) -> Optional[Tuple[int, int, int]]:
        block = self.blocks.get(str(block_id))
        if block:
            return block.position
        return None

    def get_text(self, block_id: str) -> Optional[str]:
        block = self.blocks.get(str(block_id))
        if block:
            return block.text
        return None

    def get_block_type(self, block_id: str) -> Optional[str]:
        block = self.blocks.get(str(block_id))
        if block:
            return block.block_type
        return None

    def update_text(self, block_id: str, new_text: str):
        block = self.blocks.get(str(block_id))
        if block:
            block.text = new_text

    def get_table_group_id(self, block_id: str) -> Optional[int]:
        block = self.blocks.get(str(block_id))
        if block:
            return block.table_group_id
        return None

    def to_cvd_text(self) -> str:
        """블록들을 CVD 텍스트 형식으로 직렬화.

        테이블 구분자를 삽입하여 LLM이 동일 라벨의 셀을
        다른 테이블에서 구별할 수 있게 한다.
        """
        lines = []
        current_table = None
        for bid, block in sorted(self.blocks.items(), key=lambda x: x[1].position):
            # 테이블 시작/전환 시 구분자 삽입
            if block.block_type == "td":
                tg = block.table_group_id
                if tg != current_table:
                    current_table = tg
                    lines.append(f"--- table {tg} ---")
                lines.append(f"<td {bid}>{block.text}")
            else:
                if current_table is not None:
                    current_table = None
                prefix = "<list>" if block.block_type == "list" else ""
                lines.append(f"{prefix}<{bid}>{block.text}")
        return "\n".join(lines)


# ── DocumentScanner ───────────────────────────────────

class DocumentScanner:
    """pyhwpx를 사용하여 문서 구조를 스캔하고 블록 목록을 생성.

    듀얼 모드:
      - hwpml: SaveAs("HWPML2X") → parse_hwpml2x → PositionEngine (정확, 스타일+병합 보존)
      - cursor: init_scan + TableRightCell (폴백, COM 직접 순회)
    """

    def __init__(self, hwp):
        self.hwp = hwp
        self._last_hwpml_data: Optional[dict] = None  # HWPML 스캔 캐시

    def scan_hwpml(self) -> Optional[dict]:
        """HWPML2X로 저장 → 파싱 → 블록 리스트 반환.

        Returns:
            {
                "blocks": List[dict],      # PositionEngine 출력
                "id_to_pos": Dict,         # blockId → (list, para, char)
                "style_lookup": StyleLookup,
                "doc": DocNode,
            }
            실패 시 None.
        """
        if not _HWPML_AVAILABLE:
            logger.debug("HWPML 모듈 미설치 — scan_hwpml 불가")
            return None

        hwp = self.hwp
        tmp_path = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="hwpml_")
            tmp_path = os.path.join(tmp_dir, "doc.xml")

            # HWPML2X로 저장
            hwp.SaveAs(tmp_path, "HWPML2X")

            if not os.path.exists(tmp_path):
                logger.warning("HWPML2X 저장 실패: 파일 미생성")
                return None

            with open(tmp_path, 'r', encoding='utf-8-sig') as f:
                xml_text = f.read()

            if not xml_text.strip():
                logger.warning("HWPML2X 파일이 비어있음")
                return None

            # 파싱
            doc = parse_hwpml2x(xml_text)

            # 블록 변환
            engine = PositionEngine()
            blocks, id_to_pos = engine.process_body(doc)

            result = {
                "blocks": blocks,
                "id_to_pos": id_to_pos,
                "style_lookup": doc.style_lookup,
                "doc": doc,
            }
            self._last_hwpml_data = result
            logger.info(f"HWPML 스캔 완료: {len(blocks)}개 블록")
            return result

        except Exception as e:
            logger.warning(f"HWPML 스캔 실패: {e}")
            return None
        finally:
            # 임시 파일 정리
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    os.rmdir(os.path.dirname(tmp_path))
                except Exception:
                    pass

    def scan(self, page_range: Optional[Tuple[int, int]] = None) -> List[dict]:
        """문서를 스캔하여 블록 목록 반환.

        Phase 1: init_scan으로 비-테이블 텍스트 수집 + 테이블 개수 카운트
        Phase 2: get_into_nth_table + TableRightCell로 셀 단위 순회
                 (SelectAll + get_selected_text로 셀 텍스트 직접 읽기)

        cell_seq는 Phase 2 순회 순서 기준이므로
        _move_to_block의 TableRightCell 탐색과 정확히 일치한다.
        """
        hwp = self.hwp
        import time as _time

        # ── Phase 1: init_scan — 비-테이블 텍스트 + 테이블 카운트 ──
        text_elements = []
        block_id = 100
        table_count = 0
        in_table = False

        hwp.MoveDocBegin()
        hwp.init_scan(option=4, range=0x0077)

        prev_pos = None
        scan_start = _time.monotonic()
        for _ in range(10000):
            if _time.monotonic() - scan_start > 15:
                logger.warning("Phase 1 스캔 타임아웃 (15초)")
                break

            state, text = hwp.get_text()
            if state == 0:
                break
            if state == 1:
                in_table = False
                continue

            hwp.move_pos(201)
            pos = hwp.get_pos()

            clean = (text or "").replace("\r\n", "").replace("\r", "")
            if prev_pos == pos and not clean.strip():
                continue
            prev_pos = pos

            try:
                cell_check = hwp.is_cell()
            except Exception:
                cell_check = pos[0] > 0

            if cell_check:
                if not in_table:
                    in_table = True
                    table_count += 1
            else:
                in_table = False
                if clean.strip():
                    text_elements.append({
                        "id": str(block_id),
                        "position": pos,
                        "text": clean.strip(),
                        "type": "text",
                        "table_group_id": None,
                        "table_idx": None,
                        "cell_seq": None,
                    })
                    block_id += 2

        hwp.release_scan()

        # ── Phase 2: 커서 기반 테이블 셀 스캔 (유일한 셀 소스) ──
        elements = list(text_elements)

        for t_idx in range(table_count):
            try:
                result = hwp.get_into_nth_table(t_idx)
                if not (result or hwp.is_cell()):
                    continue

                visited = set()
                cell_seq = 0
                for _ in range(2000):
                    if not hwp.is_cell():
                        break
                    pos = hwp.get_pos()
                    if pos in visited:
                        break
                    visited.add(pos)

                    # 셀 텍스트 직접 읽기
                    cell_text = ""
                    try:
                        hwp.Run("SelectAll")
                        cell_text = hwp.get_selected_text() or ""
                        hwp.Run("Cancel")
                    except Exception:
                        pass
                    cell_text = cell_text.replace("\r\n", " ").replace("\r", " ").strip()

                    elements.append({
                        "id": str(block_id),
                        "position": pos,
                        "text": cell_text,
                        "type": "td",
                        "table_group_id": t_idx + 1,
                        "table_idx": t_idx,
                        "cell_seq": cell_seq,
                    })
                    block_id += 2
                    cell_seq += 1

                    old_pos = pos
                    try:
                        hwp.TableRightCell()
                    except Exception:
                        break
                    if hwp.get_pos() == old_pos:
                        break

                try:
                    hwp.Cancel()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"테이블 {t_idx} 스캔 실패: {e}")

        # 위치 기준 정렬 (문서 순서 유지)
        elements.sort(key=lambda e: e["position"])
        return elements

    def scan_tables(self) -> List[dict]:
        """문서의 모든 표를 순회하며 셀 내용 추출."""
        hwp = self.hwp
        tables = []

        hwp.MoveDocBegin()
        table_idx = 0

        while True:
            # 다음 표 찾기
            found = False
            try:
                # 현재 위치에서 표 컨트롤 찾기
                ctrl = hwp.HeadCtrl
                while ctrl:
                    if ctrl.UserDesc == "표":
                        found = True
                        break
                    ctrl = ctrl.Next
            except Exception:
                break

            if not found:
                break

            table_data = {"index": table_idx, "cells": []}

            try:
                # 표 안으로 진입
                hwp.MoveDocBegin()
                for _ in range(table_idx + 1):
                    if not hwp.find_ctrl("tbl"):
                        break

                # 첫 셀로
                hwp.TableColBegin()
                hwp.TableColPageUp()

                row = 0
                while True:
                    col = 0
                    while True:
                        # 셀 텍스트 읽기
                        pos = hwp.get_pos()
                        hwp.SelectAll()
                        cell_text = ""
                        try:
                            cell_text = hwp.get_selected_text(keep_select=False) or ""
                        except Exception:
                            pass
                        hwp.Cancel()

                        table_data["cells"].append({
                            "row": row, "col": col,
                            "text": cell_text.strip(),
                            "position": pos,
                        })

                        # 다음 열
                        prev_pos = hwp.get_pos()
                        hwp.TableRightCell()
                        if hwp.get_pos() == prev_pos:
                            break
                        col += 1

                    # 다음 행
                    hwp.TableColBegin()
                    prev_pos = hwp.get_pos()
                    hwp.TableLowerCell()
                    if hwp.get_pos() == prev_pos:
                        break
                    row += 1

            except Exception as e:
                logger.debug(f"표 {table_idx} 스캔 실패: {e}")

            tables.append(table_data)
            table_idx += 1

            # 다음 표를 위해 현재 표 밖으로
            try:
                hwp.MoveParentList()
                hwp.MoveNextParaBegin()
            except Exception:
                break

        return tables


# ── HwpEditor ─────────────────────────────────────────

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
                     f"seq={block.cell_seq}, pos={block.position}")

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


# ── 메인 컨트롤러 ────────────────────────────────────

class HwpController:
    """pyhwpx 기반 HWP 실시간 제어 컨트롤러.

    pyhwpx가 COM 초기화를 내부에서 처리하므로 별도 COM 스레드 불필요.
    threading.Lock으로 동시 접근만 방지.
    """

    def __init__(self):
        self._hwp = None              # pyhwpx.Hwp 인스턴스
        self._connected = False
        self._lock = threading.Lock()
        self._block_manager = BlockManager()
        self._editor: Optional[HwpEditor] = None
        self._scanner: Optional[DocumentScanner] = None
        self._doc_info: Optional[DocumentInfo] = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 연결 ──

    def connect(self, visible: bool = True) -> dict:
        """실행 중인 한/글에 연결. 없으면 새 인스턴스 생성."""
        with self._lock:
            try:
                # 기존 연결 살아있으면 재사용
                if self._hwp and self._connected:
                    try:
                        self._hwp.get_pos()
                        doc_name = ""
                        try:
                            doc_name = self._hwp.FileName or ""
                        except Exception:
                            pass
                        return {"success": True, "connected": True, "document": doc_name}
                    except Exception:
                        pass  # stale → 새로 생성

                import pythoncom
                pythoncom.CoInitialize()
                from pyhwpx import Hwp
                hwp = Hwp(visible=visible)

                self._hwp = hwp
                self._connected = True
                self._editor = HwpEditor(hwp, self._block_manager)
                self._scanner = DocumentScanner(hwp)

                doc_name = ""
                try:
                    doc_name = hwp.FileName or ""
                except Exception:
                    pass

                return {"success": True, "connected": True, "document": doc_name}
            except Exception as e:
                logger.error(f"pyhwpx 연결 실패: {e}")
                self._connected = False
                return {"success": False, "error": str(e)}

    def disconnect(self):
        """COM 연결 해제."""
        with self._lock:
            self._hwp = None
            self._connected = False
            self._editor = None
            self._scanner = None

    # ── 문서 상태 ──

    def get_document_info(self) -> dict:
        """현재 문서 실시간 정보 수집."""
        if not self._connected or not self._hwp:
            return {"error": "not connected"}

        with self._lock:
            try:
                hwp = self._hwp
                pos = hwp.get_pos()

                doc_path = ""
                doc_name = ""
                try:
                    doc_path = hwp.Path or ""
                    doc_name = hwp.FileName or ""
                except Exception:
                    pass

                current_page = 0
                total_pages = 0
                try:
                    current_page = hwp.current_page
                    total_pages = hwp.PageCount
                except Exception:
                    pass

                selected = ""
                try:
                    selected = hwp.get_selected_text(keep_select=True) or ""
                except Exception:
                    pass

                ctrl_type = None
                try:
                    if hwp.is_cell():
                        ctrl_type = "표"
                except Exception:
                    pass

                modified = False
                try:
                    modified = bool(hwp.IsModified)
                except Exception:
                    pass

                info = DocumentInfo(
                    document_path=doc_path,
                    document_name=doc_name,
                    caret_position=pos,
                    caret_page=current_page,
                    total_pages=total_pages,
                    selected_text=selected,
                    ctrl_type=ctrl_type,
                    document_mode="EDIT",
                    modified=modified,
                )
                self._doc_info = info
                return info.to_dict()
            except Exception as e:
                return {"error": str(e)}

    # ── CVD 추출 ──

    def _refresh_hwp(self):
        """COM 인스턴스를 갱신 (reload 이후 stale 방지).

        기존 연결이 살아있으면 재사용, 없거나 stale하면 새로 생성.
        일시적 COM 에러는 자동 재시도.
        """
        if self._hwp and self._connected:
            # 기존 인스턴스 동작 확인
            try:
                self._hwp.get_pos()
                # scanner/editor가 없으면 재생성
                if not self._scanner:
                    self._scanner = DocumentScanner(self._hwp)
                if not self._editor:
                    self._editor = HwpEditor(self._hwp, self._block_manager)
                return
            except Exception as e:
                # 일시적 COM 에러면 재시도 전에 잠깐 대기
                if _HWPML_AVAILABLE and is_transient_com_error(e):
                    import time
                    time.sleep(0.5)
                    try:
                        self._hwp.get_pos()
                        return
                    except Exception:
                        pass
                # stale → 새로 생성
        import pythoncom
        pythoncom.CoInitialize()
        from pyhwpx import Hwp
        hwp = Hwp(visible=True)
        self._hwp = hwp
        self._connected = True
        self._editor = HwpEditor(hwp, self._block_manager)
        self._scanner = DocumentScanner(hwp)

    def extract_cvd(
        self,
        page_range: Optional[Tuple[int, int]] = None,
        mode: str = "auto",
    ) -> dict:
        """문서 구조 추출 (Content View Document).

        Args:
            page_range: (min_page, max_page)
            mode: "auto" | "hwpml" | "cursor"
                auto — HWPML 우선, 실패 시 커서 폴백
                hwpml — HWPML2X 파싱만 사용
                cursor — 기존 커서 스캔만 사용

        Returns:
            {"cvd": str, "blocks": [...], "block_count": int, "scan_mode": str}
        """
        with self._lock:
            try:
                self._refresh_hwp()

                # HWPML 모드 시도
                if mode in ("auto", "hwpml") and _HWPML_AVAILABLE:
                    hwpml_result = self._scanner.scan_hwpml()
                    if hwpml_result:
                        blocks = hwpml_result["blocks"]
                        id_to_pos = hwpml_result["id_to_pos"]
                        style_lookup = hwpml_result["style_lookup"]

                        # BlockManager 초기화 (HWPML 모드)
                        self._block_manager.initialize_from_blocks(blocks, id_to_pos)

                        # CVD 빌더로 고품질 CVD 생성
                        file_name = ""
                        try:
                            file_name = self._hwp.FileName or ""
                        except Exception:
                            pass

                        cvd_text = build_cvd(
                            blocks=blocks,
                            id_to_pos=id_to_pos,
                            style_lookup=style_lookup,
                            page_range=page_range,
                            file_name=file_name,
                        )
                        return {
                            "cvd": cvd_text,
                            "blocks": blocks,
                            "block_count": len(blocks),
                            "scan_mode": "hwpml",
                        }

                    if mode == "hwpml":
                        return {"error": "HWPML 스캔 실패", "scan_mode": "hwpml"}

                # 커서 모드 (폴백)
                elements = self._scanner.scan(page_range)
                self._block_manager.initialize_from_scan(elements)
                cvd_text = self._block_manager.to_cvd_text()
                return {
                    "cvd": cvd_text,
                    "blocks": elements,
                    "block_count": len(elements),
                    "scan_mode": "cursor",
                }
            except Exception as e:
                import traceback
                logger.error(f"extract_cvd 실패: {traceback.format_exc()}")
                return {"error": str(e), "traceback": traceback.format_exc()}

    # ── 읽기 ──

    def read_text(self) -> str:
        """문서 전체 텍스트 읽기 (페이지 설정 포함)."""
        with self._lock:
            try:
                self._refresh_hwp()
                hwp = self._hwp
                parts = []

                # 페이지 설정 정보
                try:
                    pd = hwp.get_pagedef_as_dict("eng")
                    pw = pd.get("PaperWidth", 210)
                    ph = pd.get("PaperHeight", 297)
                    lm = pd.get("LeftMargin", 30)
                    rm = pd.get("RightMargin", 30)
                    tm = pd.get("TopMargin", 25)
                    bm_ = pd.get("BottomMargin", 25)
                    gt = pd.get("GutterLen", 0)
                    uw = round(pw - lm - rm - gt, 1)
                    parts.append(
                        f"[용지] {pw}x{ph}mm, "
                        f"여백 좌{lm} 우{rm} 상{tm} 하{bm_}mm, "
                        f"가용폭 {uw}mm"
                    )
                except Exception:
                    parts.append("[용지] 정보 없음 (A4 가정: 가용폭 약150mm)")

                hwp.MoveDocBegin()
                hwp.init_scan(option=4, range=0x0077)

                for _ in range(10000):  # 안전 상한
                    state, text = hwp.get_text()
                    if state == 0:
                        break
                    if state == 1:
                        continue
                    if text and text.strip():
                        parts.append(text.strip())

                hwp.release_scan()

                # 누름틀 필드 정보
                try:
                    fields = hwp.get_field_list()
                    if fields:
                        parts.append("\n=== 누름틀 필드 ===")
                        for f in fields.split("\x02"):
                            if f:
                                val = hwp.get_field_text(f) or "(비어있음)"
                                parts.append(f"  [{f}] = {val}")
                except Exception:
                    pass

                return "\n".join(parts)
            except Exception as e:
                return f"[HWP 읽기 오류] {e}"

    # ── 편집 ──

    def execute(self, operation: str, **kwargs) -> dict:
        """편집 명령 실행.

        Args:
            operation: 명령 이름 (replace_cell_content, replace_paragraph, ...)
            **kwargs: 명령별 파라미터 (block_id, new_text, old_text, row_texts, ...)
        """
        if not self._connected or not self._editor:
            try:
                self._refresh_hwp()
            except Exception:
                return {"isSuccess": False, "message": "not connected"}

        with self._lock:
            try:
                editor = self._editor

                method_map = {
                    "replace_cell_content": lambda: editor.replace_cell_content(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "delete_cell_content": lambda: editor.delete_cell_content(
                        kwargs["block_id"]),
                    "replace_paragraph": lambda: editor.replace_paragraph(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "append_paragraph": lambda: editor.append_paragraph(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "find_and_replace_all": lambda: editor.find_and_replace_all(
                        kwargs["old_text"], kwargs["new_text"]),
                    "insert_text": lambda: editor.insert_text_at_cursor(
                        kwargs["text"]),
                    "apply_para_style": lambda: editor.apply_para_style(
                        kwargs["block_id"],
                        font_size=kwargs.get("font_size"),
                        font_family=kwargs.get("font_family"),
                        align=kwargs.get("align"),
                        spacing=kwargs.get("spacing"),
                        indentation=kwargs.get("indentation")),
                    "create_table": lambda: editor.create_table(
                        int(kwargs.get("rows", 2)), int(kwargs.get("cols", 2)),
                        data=kwargs.get("data")),
                    "replace_table_row": lambda: editor.replace_table_row(
                        kwargs["block_id"], kwargs.get("row_texts")),
                    "append_table_row": lambda: editor.append_table_row(
                        kwargs["block_id"], kwargs.get("row_texts")),
                    "style_cell": lambda: editor.style_cell(
                        kwargs["block_id"],
                        bg_color=kwargs.get("bg_color"),
                        align=kwargs.get("align"),
                        bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"),
                        text_color=kwargs.get("text_color")),
                    "style_row": lambda: editor.style_row(
                        kwargs["block_id"],
                        bg_color=kwargs.get("bg_color"),
                        bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"),
                        text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "merge_cells": lambda: editor.merge_cells(
                        kwargs["block_id"],
                        right=int(kwargs.get("right", 0)),
                        down=int(kwargs.get("down", 0))),
                    "set_table_col_width": lambda: editor.set_table_col_width(
                        kwargs["block_id"], kwargs["widths"]),
                    "save": lambda: editor.save(),
                    "save_as": lambda: editor.save_as(
                        kwargs["path"], kwargs.get("format", "HWPX")),
                    # 인덱스 기반 (block_id 불필요)
                    "style_table_row_idx": lambda: editor.style_table_row_idx(
                        int(kwargs.get("table", 1)), int(kwargs.get("row", 0)),
                        bg_color=kwargs.get("bg_color"), bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"), text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "style_table_cell_idx": lambda: editor.style_table_cell_idx(
                        int(kwargs.get("table", 1)), int(kwargs.get("row", 0)), int(kwargs.get("col", 0)),
                        bg_color=kwargs.get("bg_color"), bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"), text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "set_table_widths": lambda: editor.set_table_widths(
                        int(kwargs.get("table", 1)), kwargs.get("widths", [])),
                    "format_text": lambda: editor.format_text(
                        font_size=kwargs.get("font_size"), bold=kwargs.get("bold"),
                        align=kwargs.get("align"), text_color=kwargs.get("text_color"),
                        font_family=kwargs.get("font_family")),
                    "_raw_set_field": lambda: self._raw_set_field(
                        kwargs["field_name"], kwargs["value"]),
                    "_raw_move": lambda: self._raw_move(kwargs.get("direction", "start")),
                }

                handler = method_map.get(operation)
                if not handler:
                    return {"isSuccess": False, "message": f"알 수 없는 명령: {operation}"}

                return handler()
            except Exception as e:
                return {"isSuccess": False, "message": str(e)}

    # ── 레거시 raw 명령 (set_field, move) ──

    def _raw_set_field(self, field_name: str, value: str) -> dict:
        try:
            hwp = self._hwp
            hwp.PutFieldText(field_name, str(value))
            # 반영 확인 — PutFieldText는 누름틀 없으면 조용히 무시됨
            try:
                actual = hwp.GetFieldText(field_name)
                if actual is None or actual == "":
                    return {"isSuccess": False, "message": f"누름틀 '{field_name}' 없거나 반영 실패"}
            except Exception:
                pass  # GetFieldText 실패 시 확인 불가
            return {"isSuccess": True, "message": f"필드 '{field_name}' = {value}"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def _raw_move(self, direction: str = "start") -> dict:
        try:
            if direction == "start":
                self._hwp.MoveDocBegin()
            else:
                self._hwp.MoveDocEnd()
            return {"isSuccess": True, "message": f"문서 {direction}으로 이동"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    # ── 다중 문서 관리 ──

    def list_documents(self) -> list[dict]:
        """열려있는 모든 HWP 문서 목록 반환."""
        if not self._connected or not self._hwp:
            return []

        with self._lock:
            docs = []
            try:
                xdocs = self._hwp.XHwpDocuments
                count = xdocs.Count
                for i in range(count):
                    doc = xdocs.Item(i)
                    full_name = ""
                    title = ""
                    try:
                        full_name = doc.FullName or ""
                    except Exception:
                        pass
                    try:
                        title = doc.Title or ""
                    except Exception:
                        pass

                    # 표시명: 파일명 > Title > "새 문서 N"
                    if full_name:
                        import os
                        display = os.path.basename(full_name)
                    elif title:
                        display = title
                    else:
                        display = f"새 문서 {i + 1}"

                    docs.append({
                        "index": i,
                        "title": display,
                        "path": full_name,
                    })
            except Exception as e:
                logger.debug(f"XHwpDocuments 접근 실패, 단일 문서 fallback: {e}")
                name = ""
                path = ""
                try:
                    name = self._hwp.FileName or ""
                    path = self._hwp.Path or ""
                except Exception:
                    pass
                docs.append({
                    "index": 0,
                    "title": name or "현재 문서",
                    "path": path,
                })
            return docs

    def switch_document(self, doc_index: int) -> dict:
        """특정 문서로 전환 (0-based index)."""
        if not self._connected or not self._hwp:
            return {"success": False, "error": "not connected"}

        with self._lock:
            try:
                xdocs = self._hwp.XHwpDocuments
                count = xdocs.Count
                if doc_index < 0 or doc_index >= count:
                    return {"success": False, "error": f"인덱스 범위 초과 (0~{count-1})"}

                doc = xdocs.Item(doc_index)
                doc.SetActive_XHwpDocument()

                # 전환 후 스캐너/에디터 재초기화
                self._scanner = DocumentScanner(self._hwp)
                self._block_manager = BlockManager()
                self._editor = HwpEditor(self._hwp, self._block_manager)

                doc_name = ""
                try:
                    doc_name = self._hwp.FileName or ""
                except Exception:
                    pass

                return {"success": True, "document": doc_name}
            except Exception as e:
                logger.error(f"문서 전환 실패: {e}")
                return {"success": False, "error": str(e)}

    # ── 표 스캔 ──

    def scan_tables(self) -> dict:
        """문서의 모든 표 구조 추출."""
        if not self._connected or not self._scanner:
            return {"error": "not connected"}

        with self._lock:
            try:
                tables = self._scanner.scan_tables()
                return {"tables": tables, "count": len(tables)}
            except Exception as e:
                return {"error": str(e)}


# ── 액션 스키마 (LLM 프롬프트용) ──────────────────────

HWP_ACTIONS_SCHEMA = {
    "replace_cell_content": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "표 셀 내용 교체 (blockId 기반)"
    },
    "delete_cell_content": {
        "params": {"block_id": "블록 ID"},
        "desc": "표 셀 내용 삭제"
    },
    "replace_paragraph": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "문단 내용 교체"
    },
    "append_paragraph": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "문단 뒤에 새 문단 추가"
    },
    "find_and_replace_all": {
        "params": {"old_text": "찾을 텍스트", "new_text": "바꿀 텍스트"},
        "desc": "전체 찾아 바꾸기"
    },
    "insert_text": {
        "params": {"text": "삽입할 텍스트"},
        "desc": "커서 위치에 텍스트 삽입"
    },
    "apply_para_style": {
        "params": {"block_id": "블록 ID", "font_size": "크기(pt)", "font_family": "글꼴", "align": "정렬(left/center/right/justify)", "spacing": "줄간격", "indentation": "들여쓰기"},
        "desc": "문단 서식 적용"
    },
    "create_table": {
        "params": {"rows": "행 수", "cols": "열 수"},
        "desc": "표 생성"
    },
    "replace_table_row": {
        "params": {"block_id": "블록 ID", "row_texts": ["셀1", "셀2", "..."]},
        "desc": "표 행 전체 셀 교체"
    },
    "append_table_row": {
        "params": {"block_id": "블록 ID", "row_texts": ["셀1", "셀2", "..."]},
        "desc": "표에 행 추가"
    },
    "save": {
        "params": {},
        "desc": "문서 저장"
    },
    "save_as": {
        "params": {"path": "저장 경로", "format": "HWP|HWPX|PDF"},
        "desc": "다른 이름으로 저장"
    },
}
