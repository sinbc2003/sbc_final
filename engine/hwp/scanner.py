"""DocumentScanner — 문서 스캔 → CVD(블록+위치) 추출."""

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
