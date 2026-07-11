"""BlockManager — blockId ↔ 위치 매핑, 삽입 추적."""

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

    def calibrate_with_scan(self, elements: List[dict]) -> dict:
        """HWPML 가상 좌표를 InitScan 실좌표로 캘리브레이션 — 셀 그룹 단위.

        원리(grid_live 정렬과 동일, bench 1126셀 실증): InitScan 셀(list_id
        최초등장 순)과 HWPML td 블록(블록ID 순 = 문서 순)은 같은 문서 내부
        순서다.

        HWPML 구조: 셀 = 빈 td 블록 + 셀 내용 문단 블록(들)이 **같은 가상
        list(position[0])를 공유**. LLM이 CVD에서 고르는 것은 내용 블록이므로,
        검산(그룹 내용 텍스트 ↔ 스캔 셀 텍스트, 공백 무시)을 통과한 셀 그룹의
        **모든 블록**을 스캔 셀 실좌표로 교체 + calibrated 마킹 →
        HwpEditor set_pos가 신뢰 가능("셀 위치 불일치" 해소).
        표 밖 문단 블록은 건드리지 않음.
        """
        stats = {"scan_cells": 0, "td_blocks": 0, "calibrated_cells": 0,
                 "calibrated_blocks": 0, "mismatched": 0}
        if self._scan_mode != "hwpml":
            return stats

        def norm(s: str) -> str:
            return "".join((s or "").split())

        def _bid(b) -> int:
            return int(b.id) if str(b.id).isdigit() else 0

        # InitScan 셀: list_id 최초등장 순서로 병합 (grid_live.scan_cells_in_order와 동일)
        seen: Dict[int, dict] = {}
        order: List[int] = []
        for e in elements:
            if e.get("type") != "td":
                continue
            lid = e.get("list_id")
            if lid not in seen:
                seen[lid] = {"texts": [], "pos": e["pos"]}
                order.append(lid)
            t = (e.get("text") or "").strip()
            if t:
                seen[lid]["texts"].append(t)
        scells = [(norm(" ".join(seen[lid]["texts"])), seen[lid]["pos"]) for lid in order]

        # 가상 list(position[0]) → 그 셀의 블록 그룹 (td + 내용 문단)
        td_blocks = sorted((b for b in self.blocks.values() if b.block_type == "td"),
                           key=_bid)
        groups: Dict[int, List] = {}
        td_vlists = {b.position[0] for b in td_blocks}
        for b in self.blocks.values():
            vl = b.position[0]
            if vl in td_vlists:
                groups.setdefault(vl, []).append(b)

        stats["scan_cells"] = len(scells)
        stats["td_blocks"] = len(td_blocks)

        if not scells or len(scells) != len(td_blocks):
            logger.warning(f"캘리브레이션 중단: 셀 수 불일치 (스캔 {len(scells)} vs 블록 {len(td_blocks)})")
            return stats

        for td_block, (stext, pos) in zip(td_blocks, scells):
            group = sorted(groups.get(td_block.position[0], [td_block]), key=_bid)
            content = norm("".join(b.text for b in group if b.block_type != "td"))
            if content == stext:
                for b in group:
                    b.position = tuple(pos)
                    b.calibrated = True
                    stats["calibrated_blocks"] += 1
                stats["calibrated_cells"] += 1
            else:
                stats["mismatched"] += 1

        logger.info(f"셀 좌표 캘리브레이션: {stats['calibrated_cells']}/{len(td_blocks)}셀 "
                    f"({stats['calibrated_blocks']}블록)"
                    + (f", 불일치 {stats['mismatched']}" if stats["mismatched"] else ""))
        return stats

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
