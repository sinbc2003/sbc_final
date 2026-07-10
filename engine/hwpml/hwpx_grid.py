"""
HWPX 파일 기반 표 그리드 파서 + 셀 채우기.

form_extract / form_fill / 벤치마크가 공유하는 모듈.
COM 불필요 — HWPX(ZIP) 안의 section XML을 직접 파싱/수정한다.

핵심 설계:
  - 셀 주소 ID: "s{섹션}_t{표}_r{행}_c{열}" — 추출과 채움이 같은 표 순회
    순서(_iter_tables)를 공유하므로 ID가 항상 같은 셀을 가리킨다.
  - 병합: HWPX는 cellAddr/cellSpan 주소 기반이라 점유 맵으로 결정적 해석.
  - 헤더 추정: 표 상단의 "병합이 이어지는 연속 구간"을 헤더 행으로 간주.
  - 빈칸 라벨: 열 헤더(위쪽 헤더 경로) × 행 헤더(왼쪽 인접 텍스트)를
    코드가 계산 — LLM은 의미 매칭만 하면 된다.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from typing import Iterator, Optional

from lxml import etree

# 셀 주소 ID 형식
ID_RE = re.compile(r"^s(\d+)_t(\d+)_r(\d+)_c(\d+)$")

# 본문 밑줄 블랭크 ID 형식 ("성명: ______" 식 본문 빈칸)
BODY_ID_RE = re.compile(r"^s(\d+)_u(\d+)$")
# 밑줄런 = 블랭크 (ASCII/전각, 3자 이상 — 마크다운 강조 등 오인 방지)
BLANK_RUN_RE = re.compile(r"[_＿]{3,}")

# 이 크기 이하의 표는 "정보 표"로 보고 다음 표의 맥락 버퍼에 요약을 넣는다
SMALL_TABLE_CELLS = 12


def _ln(elem) -> str:
    """네임스페이스 제거한 로컬 태그명."""
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _elem_text(elem) -> str:
    """요소 하위 텍스트 (중첩 표 제외)."""
    parts: list[str] = []

    def walk(e):
        for ch in e:
            ln = _ln(ch)
            if ln == "tbl":
                continue  # 중첩 표 텍스트는 그 표의 몫
            if ln == "t":
                parts.append("".join(ch.itertext()))
            else:
                walk(ch)

    walk(elem)
    return " ".join("".join(parts).split())


# ── 데이터 구조 ─────────────────────────────────────

@dataclass
class GridCell:
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str = ""


@dataclass
class TableGrid:
    section_idx: int
    index: int              # 섹션 내 표 순번 (_iter_tables 순서)
    row_cnt: int
    col_cnt: int
    cells: dict = field(default_factory=dict)   # (row, col) → GridCell (anchor만)
    context: str = ""       # 표 직전 텍스트/소형 표 요약
    _occupancy: dict = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        return f"s{self.section_idx}_t{self.index}"

    def _build_occupancy(self):
        if self._occupancy:
            return
        for (r, c), cell in self.cells.items():
            for rr in range(r, r + cell.row_span):
                for cc in range(c, c + cell.col_span):
                    self._occupancy[(rr, cc)] = (r, c)

    def owner(self, r: int, c: int) -> Optional[GridCell]:
        """(r,c)를 덮는 anchor 셀 (병합 해석)."""
        self._build_occupancy()
        anchor = self._occupancy.get((r, c))
        return self.cells.get(anchor) if anchor else None

    def header_row_count(self) -> int:
        """상단 헤더 행 수 추정: 병합이 이어지는 연속 구간."""
        h = 1
        covered_until = 0
        for r in range(self.row_cnt):
            anchors = [c for c in self.cells.values() if c.row == r]
            has_merge = any(c.col_span > 1 or c.row_span > 1 for c in anchors)
            if r == 0:
                for c in anchors:
                    covered_until = max(covered_until, c.row + c.row_span)
                if not has_merge and covered_until <= 1:
                    break
                h = max(h, covered_until)
            elif r < covered_until or has_merge:
                for c in anchors:
                    covered_until = max(covered_until, c.row + c.row_span)
                h = max(h, r + 1, covered_until)
            else:
                break
        return max(1, min(h, self.row_cnt))

    def col_header(self, r: int, c: int, max_items: int = 3) -> str:
        """열 c의 헤더 경로 (헤더 구간에서 위→아래)."""
        h = self.header_row_count()
        if r < h:
            return ""  # 자기 자신이 헤더 구간
        texts: list[str] = []
        seen: set = set()
        for rr in range(h):
            cell = self.owner(rr, c)
            if cell and cell.text and (cell.row, cell.col) not in seen:
                seen.add((cell.row, cell.col))
                texts.append(cell.text[:30])
        return " / ".join(texts[-max_items:])

    def row_header(self, r: int, c: int, max_items: int = 2) -> str:
        """행 r에서 왼쪽의 비어있지 않은 셀 텍스트 (왼→오, 가까운 것 우선 수집)."""
        texts: list[str] = []
        seen: set = set()
        cc = c - 1
        while cc >= 0 and len(texts) < max_items:
            cell = self.owner(r, cc)
            if cell:
                if cell.text and (cell.row, cell.col) not in seen:
                    seen.add((cell.row, cell.col))
                    texts.append(cell.text[:30])
                cc = cell.col - 1
            else:
                cc -= 1
        texts.reverse()
        return " / ".join(texts)

    def summary(self, max_chars: int = 150) -> str:
        """소형 표 요약 — 2행 헤더-값 표는 '헤더=값' 형태로."""
        rows: dict[int, list[GridCell]] = {}
        for cell in self.cells.values():
            rows.setdefault(cell.row, []).append(cell)
        for r in rows:
            rows[r].sort(key=lambda c: c.col)
        if len(rows) == 2 and 0 in rows and 1 in rows and len(rows[0]) == len(rows[1]):
            pairs = [f"{h.text}={v.text}" for h, v in zip(rows[0], rows[1]) if h.text]
            return ("; ".join(pairs))[:max_chars]
        texts = [c.text for r in sorted(rows) for c in rows[r] if c.text]
        return (" | ".join(texts))[:max_chars]

    def render(self, mark_blanks: bool = False) -> str:
        """사람/LLM이 읽을 수 있는 그리드 렌더링.

        병합으로 덮인 칸: 가로 병합 ">", 세로 병합 "^" (md_to_hwpx 규칙과 동일).
        mark_blanks=True면 빈 anchor 셀을 {셀ID}로 표기.
        """
        self._build_occupancy()
        lines = [f"[표 {self.key}] {self.row_cnt}행×{self.col_cnt}열"
                 + (f" | 맥락: {self.context}" if self.context else "")]
        for r in range(self.row_cnt):
            row_parts = []
            for c in range(self.col_cnt):
                anchor = self._occupancy.get((r, c))
                if anchor is None:
                    row_parts.append("")
                elif anchor == (r, c):
                    cell = self.cells[(r, c)]
                    if cell.text:
                        row_parts.append(cell.text)
                    elif mark_blanks:
                        row_parts.append(f"{{{self.key}_r{r}_c{c}}}")
                    else:
                        row_parts.append("")
                else:
                    ar, ac = anchor
                    row_parts.append("^" if ar < r else ">")
            lines.append("| " + " | ".join(row_parts) + " |")
        return "\n".join(lines)


@dataclass
class HwpxDoc:
    tables: list = field(default_factory=list)          # [TableGrid]
    flow: list = field(default_factory=list)            # [("text", str) | ("table", TableGrid)]

    def render_text(self, mark_blanks: bool = False) -> str:
        """문서 전체를 텍스트 흐름으로 렌더링 (표는 그리드로)."""
        parts = []
        for kind, payload in self.flow:
            if kind == "text":
                parts.append(payload)
            else:
                parts.append(payload.render(mark_blanks=mark_blanks))
        return "\n".join(parts)


# ── 파싱 ────────────────────────────────────────────

def _section_files(zf: zipfile.ZipFile) -> list[str]:
    return sorted(
        n for n in zf.namelist()
        if "section" in n.lower() and n.endswith(".xml") and n.startswith("Contents")
    ) or sorted(
        n for n in zf.namelist()
        if "section" in n.lower() and n.endswith(".xml")
    )


def _parse_table_elem(tbl, section_idx: int, index: int, context: str) -> TableGrid:
    row_cnt = int(tbl.get("rowCnt") or 0)
    col_cnt = int(tbl.get("colCnt") or 0)
    grid = TableGrid(section_idx=section_idx, index=index,
                     row_cnt=row_cnt, col_cnt=col_cnt, context=context)

    trs = [ch for ch in tbl if _ln(ch) == "tr"]
    for r_i, tr in enumerate(trs):
        c_cursor = 0
        for tc in (c for c in tr if _ln(c) == "tc"):
            addr = None
            span = (1, 1)
            for ch in tc:
                ln = _ln(ch)
                if ln == "cellAddr":
                    addr = (int(ch.get("rowAddr") or r_i), int(ch.get("colAddr") or c_cursor))
                elif ln == "cellSpan":
                    span = (int(ch.get("rowSpan") or 1), int(ch.get("colSpan") or 1))
            if addr is None:
                addr = (r_i, c_cursor)
            c_cursor = addr[1] + span[1]
            grid.cells[addr] = GridCell(
                row=addr[0], col=addr[1],
                row_span=span[0], col_span=span[1],
                text=_elem_text(tc),
            )
    # rowCnt/colCnt 미기재 시 셀에서 계산
    if not grid.row_cnt and grid.cells:
        grid.row_cnt = max(r + c.row_span for (r, _), c in grid.cells.items())
    if not grid.col_cnt and grid.cells:
        grid.col_cnt = max(cc + c.col_span for (_, cc), c in grid.cells.items())
    return grid


def _iter_tables(root) -> Iterator[tuple]:
    """섹션 XML에서 (tbl 요소, 직전 맥락 텍스트) 를 문서 순서로 yield.

    파싱과 채움이 이 순회를 공유한다 → 표 인덱스 일관성 보장.
    중첩 표는 부모 표 뒤에 이어서 나온다.
    """
    buffer: list[str] = []

    def ctx() -> str:
        joined = " ".join(buffer)
        return joined[-200:] if joined else ""

    def walk(e):
        for ch in e:
            ln = _ln(ch)
            if ln == "tbl":
                yield ch, ctx()
                # 소형 표(정보 표)는 요약을 맥락 버퍼에 넣어 다음 표가 상속
                tcs = [x for x in ch.iter() if _ln(x) == "tc"]
                if len(tcs) <= SMALL_TABLE_CELLS:
                    cell_texts = [t for t in (_elem_text(tc) for tc in tcs) if t]
                    summary = " | ".join(cell_texts)[:150]
                    if summary:
                        buffer.append(f"[표: {summary}]")
                # 중첩 표: 이 표의 셀 내부 표들 (텍스트 버퍼는 셀 텍스트로 갱신하지 않음)
                nested = []

                def find_nested(x):
                    for sub in x:
                        if _ln(sub) == "tbl":
                            nested.append(sub)
                        else:
                            find_nested(sub)

                find_nested(ch)
                for sub in nested:
                    yield sub, ctx() + " (중첩 표)"
            elif ln == "t":
                txt = "".join(ch.itertext()).strip()
                if txt:
                    buffer.append(txt)
                    del buffer[:-20]
            else:
                yield from walk(ch)

    yield from walk(root)


def parse_hwpx(path: str) -> HwpxDoc:
    """HWPX 파일 → 표 그리드 목록 + 문서 흐름."""
    doc = HwpxDoc()
    with zipfile.ZipFile(path, "r") as zf:
        for s_idx, sec_name in enumerate(_section_files(zf)):
            try:
                root = etree.fromstring(zf.read(sec_name))
            except etree.XMLSyntaxError:
                continue

            t_idx = 0
            table_elems: set = set()
            grids: list[TableGrid] = []
            for tbl, context in _iter_tables(root):
                grid = _parse_table_elem(tbl, s_idx, t_idx, context)
                grids.append(grid)
                table_elems.add(id(tbl))
                t_idx += 1

            doc.tables.extend(grids)

            # 문서 흐름 재구성 (표 밖 텍스트 + 표, 소형 표 요약은 맥락으로 흡수됨)
            g_iter = iter(grids)

            def flow_walk(e):
                for ch in e:
                    ln = _ln(ch)
                    if ln == "tbl":
                        if id(ch) in table_elems:
                            g = next(g_iter, None)
                            if g is not None:
                                doc.flow.append(("table", g))
                        # 중첩 표 흐름은 부모 렌더링에 포함되지 않으므로 진입하지 않음
                    elif ln == "t":
                        txt = "".join(ch.itertext()).strip()
                        if txt:
                            doc.flow.append(("text", txt))
                    else:
                        flow_walk(ch)

            flow_walk(root)
    return doc


# ── 빈칸 추출 ───────────────────────────────────────

def extract_blank_fields(doc: HwpxDoc, include_filled: bool = False) -> list[dict]:
    """빈 셀(anchor)마다 행헤더×열헤더가 계산된 필드 딕셔너리 생성."""
    fields: list[dict] = []
    for grid in doc.tables:
        header_rows = grid.header_row_count()
        for (r, c), cell in sorted(grid.cells.items()):
            is_empty = not cell.text.strip()
            if not is_empty and not include_filled:
                continue
            if is_empty and r < header_rows:
                continue  # 헤더 구간의 빈 셀은 채움 대상 아님
            col_h = grid.col_header(r, c)
            row_h = grid.row_header(r, c)
            if row_h and col_h:
                label = f"{row_h} × {col_h}"
            elif col_h:
                label = f"{col_h} (행{r})"
            elif row_h:
                label = row_h
            else:
                label = f"표{grid.index} 행{r} 열{c}"
            fields.append({
                "id": f"{grid.key}_r{r}_c{c}",
                "section": grid.section_idx,
                "table": grid.index,
                "row": r,
                "col": c,
                "label": label,
                "row_header": row_h,
                "col_header": col_h,
                "context": grid.context,
                "current_value": cell.text,
                "is_empty": is_empty,
                "value_type": "text",
            })
    return fields


# ── 본문 밑줄 블랭크 ("성명: ______") ────────────────

# body walker가 진입하지 않는 서브트리 — 표(셀ID 경로), 머리말/꼬리말·각주·바탕쪽
# (장식 괘선이 흔한 영역, 본문 아님)
_BODY_SKIP_TAGS = {"tbl", "header", "footer", "footNote", "endNote", "masterPage"}


def _iter_body_t(root) -> Iterator:
    """본문(표 밖) <t> 요소를 문서 순서로 yield.

    추출(extract_body_blanks)과 채움(fill_hwpx_cells body_map)이 이 순회와
    BLANK_RUN_RE를 공유한다 → 블랭크 카운터(ID) 일관성 보장.
    - 표 셀 내부: 그리드 셀ID 경로 담당 (충돌 방지, 의도적 제외)
    - 누름틀(fieldBegin~fieldEnd) 내부: 누름틀 정밀 채움 경로 담당 (이중 추출 방지)
    - 머리말/꼬리말/각주/바탕쪽: 장식 괘선 영역, 제외
    """
    field_depth = 0

    def walk(e):
        nonlocal field_depth
        for ch in e:
            ln = _ln(ch)
            if ln in _BODY_SKIP_TAGS:
                continue
            if ln in ("fieldBegin", "FIELDBEGIN"):
                field_depth += 1
            elif ln in ("fieldEnd", "FIELDEND"):
                field_depth = max(0, field_depth - 1)
            elif ln == "t":
                if field_depth == 0:
                    yield ch
            else:
                yield from walk(ch)

    yield from walk(root)


# 이 길이 이상의 밑줄런은 장식 구분선으로 간주 (서명란은 보통 6~14자)
_SEPARATOR_RUN_LEN = 15


def _iter_body_blank_matches(path: str):
    """본문 밑줄런 매치를 문서 순서로 yield — (섹션, 순번, 런 문자열, prefix, suffix, 장식여부).

    extract_body_blanks(방출 판정)와 라이브 find 순회(body_blank_runs)가 이
    단일 순회를 공유한다 → 카운터(ID)·장식 판정 정합 보장.
    """
    with zipfile.ZipFile(path, "r") as zf:
        for s_idx, sec_name in enumerate(_section_files(zf)):
            try:
                root = etree.fromstring(zf.read(sec_name))
            except etree.XMLSyntaxError:
                continue
            counter = 0
            for t in _iter_body_t(root):
                text = t.text or ""
                matches = list(BLANK_RUN_RE.finditer(text))
                for i, m in enumerate(matches):
                    # 앞뒤 문맥은 인접 블랭크 경계에서 자름 (라벨 혼동 방지)
                    lo = matches[i - 1].end() if i > 0 else 0
                    hi = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    prefix = text[lo:m.start()].strip()[-20:]
                    suffix = text[m.end():hi].strip()[:12]
                    decorative = ((not prefix and not suffix)
                                  or len(m.group()) >= _SEPARATOR_RUN_LEN)
                    yield s_idx, counter, m.group(), prefix, suffix, decorative
                    counter += 1


def extract_body_blanks(path: str) -> list[dict]:
    """본문 문단의 밑줄런 블랭크마다 라벨(앞뒤 문맥) 붙인 필드 생성.

    ID = s{섹션}_u{순번} (섹션 내 문서 순서 카운터 — 채움과 동일 순회로 정합).
    같은 문단(t)에 라벨 문맥이 없거나 구분선 길이(15자+)인 밑줄런은 장식으로
    보고 방출하지 않는다(카운터는 증가 → 채움 쪽 카운터와 어긋나지 않음).
    """
    fields: list[dict] = []
    for s_idx, counter, run, prefix, suffix, decorative in _iter_body_blank_matches(path):
        if decorative:
            continue
        fields.append({
            "id": f"s{s_idx}_u{counter}",
            "section": s_idx,
            "label": f"{prefix} ___ {suffix}".strip(),
            "context": "",
            "current_value": "",
            "is_empty": True,
            "value_type": "body",
            "blank_run": run,
        })
    return fields


def body_blank_runs(path: str) -> list[tuple]:
    """문서 순서의 본문 밑줄런 전체 목록 — [(블랭크ID, 런 문자열)].

    장식(방출 제외) 런도 포함(ID 자리 유지)하되 ID는 동일 형식으로 부여 —
    라이브 find 순회가 문서의 모든 본문 밑줄런을 순서대로 지나가며
    카운터를 extract와 정확히 맞추기 위한 목록이다.
    """
    return [(f"s{s}_u{c}", run)
            for s, c, run, _p, _sfx, _d in _iter_body_blank_matches(path)]


def _fill_body_blanks(root, s_idx: int, body_targets: dict) -> int:
    """body_targets({순번: 값})의 밑줄런을 값으로 교체. 순회·regex는 추출과 동일."""
    counter = 0
    filled = 0
    for t in _iter_body_t(root):
        text = t.text or ""
        matches = list(BLANK_RUN_RE.finditer(text))
        if not matches:
            continue
        replaces = {}  # match idx → 값
        for i, _m in enumerate(matches):
            if counter in body_targets:
                replaces[i] = str(body_targets[counter])
            counter += 1
        if replaces:
            parts = []
            pos = 0
            for i, m in enumerate(matches):
                parts.append(text[pos:m.start()])
                parts.append(replaces.get(i, m.group()))
                pos = m.end()
            parts.append(text[pos:])
            t.text = "".join(parts)
            filled += len(replaces)
    return filled


# ── "이하빈칸" 마커 이동 ────────────────────────────

# 공문서 관례: 마지막 데이터 행 바로 아래 행에 "이하빈칸"(또는 "이하여백") 표기.
# 실문서에선 셀 하나에 한 글자씩 흩어지기도 한다 — 행 단위로 이어 붙여 판정.
MARKER_TEXTS = {"이하빈칸", "이하여백"}


def find_below_marker(grid: TableGrid) -> Optional[dict]:
    """데이터 영역에서 '이하빈칸' 마커 행 탐지.

    반환: {"row": r, "cells": [(col, text)]} 또는 None.
    숫자만 있는 셀(미리 인쇄된 관리번호)은 판정에서 제외한다.
    """
    for r in range(grid.header_row_count(), grid.row_cnt):
        parts = [(c, cell.text.strip())
                 for (rr, c), cell in sorted(grid.cells.items())
                 if rr == r and cell.text.strip() and not cell.text.strip().isdigit()]
        if parts and "".join(t for _, t in parts).replace(" ", "") in MARKER_TEXTS:
            return {"row": r, "cells": parts}
    return None


def relocate_below_markers(doc: HwpxDoc, fill_map: dict, log=None) -> dict:
    """'이하빈칸' 마커를 채워진 마지막 행 바로 아래 빈 행으로 옮기는 추가 항목 계산.

    반환: {셀ID: 값} — 기존 마커 클리어("") + 새 위치 마커 문자.
    fill_map과 겹치는 키는 호출 측에서 fill_map을 우선할 것(setdefault 병합).
    빈 행이 없으면(표가 가득 참) 마커를 지우기만 한다 — 원본 문서 관례와 동일.
    """
    overrides = {str(k).strip(): str(v) for k, v in fill_map.items()}
    by_table: dict[tuple, set] = {}
    for key, value in overrides.items():
        m = ID_RE.match(key)
        if m and value.strip():
            s, t, r, _c = (int(g) for g in m.groups())
            by_table.setdefault((s, t), set()).add(r)

    extra: dict = {}
    for grid in doc.tables:
        marker = find_below_marker(grid)
        if not marker:
            continue
        filled_rows = by_table.get((grid.section_idx, grid.index))
        if not filled_rows:
            continue  # 이 표에 채우는 값이 없으면 마커 유지
        target = max(filled_rows) + 1
        if target == marker["row"]:
            continue

        clears = {f"{grid.key}_r{marker['row']}_c{c}": "" for c, _ in marker["cells"]}

        def projected(r: int, c: int, cell: GridCell) -> str:
            key = f"{grid.key}_r{r}_c{c}"
            if key in overrides:
                return overrides[key].strip()
            if key in clears:
                return ""
            return cell.text.strip()

        def row_ok(r: int) -> bool:
            """채운 뒤 기준으로 빈 행(미리 인쇄된 숫자만 있는 행 포함)인가."""
            texts = [projected(r, c, cell)
                     for (rr, c), cell in grid.cells.items() if rr == r]
            return bool(texts) and all(not t or t.isdigit() for t in texts)

        placed = next((rr for rr in range(target, grid.row_cnt) if row_ok(rr)), None)

        extra.update(clears)
        if placed is not None:
            for c, text in marker["cells"]:
                extra[f"{grid.key}_r{placed}_c{c}"] = text
            if log:
                log(f"{grid.key}: '이하빈칸' 마커 r{marker['row']} → r{placed}")
        elif log:
            log(f"{grid.key}: 빈 행 없음 — '이하빈칸' 마커 제거 (r{marker['row']})")
    return extra


# ── 셀 채우기 ───────────────────────────────────────

def _set_cell_text(tc, value: str) -> bool:
    """tc 셀의 첫 문단 첫 run에 텍스트 설정. 기존 서식(charPr) 보존."""
    # tc > subList > p > run > t
    sub = next((ch for ch in tc if _ln(ch) == "subList"), None)
    container = sub if sub is not None else tc
    p = next((ch for ch in container if _ln(ch) == "p"), None)
    if p is None:
        return False
    ns_uri = p.tag.rsplit("}", 1)[0].lstrip("{") if "}" in p.tag else None

    run = next((ch for ch in p if _ln(ch) == "run"), None)
    if run is None:
        run = etree.SubElement(p, f"{{{ns_uri}}}run" if ns_uri else "run")

    ts = [ch for ch in run if _ln(ch) == "t"]
    if ts:
        ts[0].text = value
        for extra in ts[1:]:
            extra.text = ""
    else:
        t = etree.SubElement(run, f"{{{ns_uri}}}t" if ns_uri else "t")
        t.text = value

    # 같은 셀의 나머지 문단/run 텍스트는 비운다 (병합 셀의 잔여 텍스트 방지)
    first_run_seen = False
    for pp in (ch for ch in container if _ln(ch) == "p"):
        for rr in (ch for ch in pp if _ln(ch) == "run"):
            for t_el in (ch for ch in rr if _ln(ch) == "t"):
                if not first_run_seen:
                    first_run_seen = True
                    continue
                t_el.text = ""
    return True


def _fill_fields_precise(root, field_map: dict) -> int:
    """누름틀(fieldBegin) 값을 '정확한 이름 일치'로만 채운다.

    form_fill._fill_hwpx_section의 라벨 퍼지매칭(인접 라벨=키 부분일치)과 달리
    fieldBegin name == 키일 때 그 필드의 첫 <t>에만 쓴다 → 무관한 빈 셀 과충전 없음.
    """
    order = list(root.iter())
    filled = 0
    for i, elem in enumerate(order):
        if _ln(elem) not in ("fieldBegin", "FIELDBEGIN"):
            continue
        name = elem.get("name") or elem.get("Name") or ""
        if name not in field_map:
            continue
        for j in range(i + 1, len(order)):
            if _ln(order[j]) == "t":
                t = order[j]
                value = str(field_map[name])
                cur = t.text or ""
                m = BLANK_RUN_RE.search(cur)
                if m and cur.strip() != m.group():
                    # 표시 텍스트에 라벨이 섞인 누름틀("성명: ______") —
                    # 밑줄런만 치환해 접두 텍스트 보존
                    t.text = cur[:m.start()] + value + cur[m.end():]
                else:
                    t.text = value
                filled += 1
                break
    return filled


def fill_hwpx_cells(src_path: str, out_path: str, fill_map: dict, log=None,
                    field_map: dict | None = None,
                    body_map: dict | None = None) -> int:
    """fill_map({셀ID: 값})의 값을 원본 서식 그대로 유지하며 주입.

    셀ID 형식: s{섹션}_t{표}_r{행}_c{열}. 값이 ""이면 셀 내용 삭제(클리어).
    field_map({누름틀명: 값})이 주어지면 누름틀도 정확 이름 일치로 채운다.
    body_map({본문블랭크ID: 값}, s{섹션}_u{순번})은 본문 밑줄런을 값으로 교체.
    반환: 실제 주입된 셀(+누름틀+본문블랭크) 수.
    """
    # 섹션별로 그룹핑
    by_section: dict[int, dict[tuple, str]] = {}
    for key, value in fill_map.items():
        m = ID_RE.match(str(key).strip())
        if not m:
            continue
        s, t, r, c = (int(g) for g in m.groups())
        by_section.setdefault(s, {})[(t, r, c)] = str(value)

    body_by_section: dict[int, dict[int, str]] = {}
    for key, value in (body_map or {}).items():
        m = BODY_ID_RE.match(str(key).strip())
        if not m:
            continue
        # 빈 값은 밑줄런 자체를 지워버림(양식 훼손) → 건너뜀.
        # (그리드 셀의 ""=클리어 의미는 본문 블랭크에 적용하지 않는다.)
        if not str(value).strip():
            continue
        s, u = (int(g) for g in m.groups())
        body_by_section.setdefault(s, {})[u] = str(value)

    fields = dict(field_map) if field_map else {}

    filled = 0
    with zipfile.ZipFile(src_path, "r") as zf_in:
        sections = _section_files(zf_in)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                data = zf_in.read(item.filename)
                if item.filename in sections:
                    s_idx = sections.index(item.filename)
                    targets = by_section.get(s_idx)
                    body_targets = body_by_section.get(s_idx)
                    if targets or fields or body_targets:
                        try:
                            root = etree.fromstring(data)
                        except etree.XMLSyntaxError:
                            zf_out.writestr(item, data)
                            continue
                        # 본문 블랭크를 먼저 — 그리드/누름틀 수정이 카운터에
                        # 영향 주지 않도록 (본문 walker는 tbl을 안 보지만 순서 고정)
                        if body_targets:
                            filled += _fill_body_blanks(root, s_idx, body_targets)
                        if targets:
                            # 파싱과 같은 순회 순서로 표를 찾는다
                            for t_idx, (tbl, _ctx) in enumerate(_iter_tables(root)):
                                wanted = {(r, c): v for (t, r, c), v in targets.items() if t == t_idx}
                                if not wanted:
                                    continue
                                for tr in (ch for ch in tbl if _ln(ch) == "tr"):
                                    for tc in (ch for ch in tr if _ln(ch) == "tc"):
                                        addr = None
                                        for ch in tc:
                                            if _ln(ch) == "cellAddr":
                                                addr = (int(ch.get("rowAddr") or -1),
                                                        int(ch.get("colAddr") or -1))
                                                break
                                        if addr in wanted:
                                            if _set_cell_text(tc, wanted[addr]):
                                                filled += 1
                                            elif log:
                                                log(f"셀 구조 인식 실패: t{t_idx} {addr}")
                        if fields:
                            filled += _fill_fields_precise(root, fields)
                        data = etree.tostring(root, xml_declaration=True,
                                              encoding="UTF-8", standalone=True)
                zf_out.writestr(item, data)

    if log:
        total = len(fill_map) + len(fields) + len(body_map or {})
        log(f"그리드 채움: {filled}/{total}개")
    return filled
