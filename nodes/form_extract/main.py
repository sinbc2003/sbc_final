"""
양식 빈칸 추출 노드.

XLSX: openpyxl로 빈 셀 + 인접 라벨 추출
HWPX: ZIP→XML 파싱, 빈 텍스트 필드 탐색
HWP: 한/글 COM API (Windows 전용)
"""

import json
import os
import zipfile
from pathlib import Path


def execute(inputs: dict, params: dict, context: dict) -> dict:
    file_path = inputs["파일"]
    if not Path(file_path).exists():
        raise FileNotFoundError(f"파일 없음: {file_path}")

    include_filled = params.get("include_filled", False)
    ext = Path(file_path).suffix.lower()

    context["progress"](0.1)

    if ext in (".xlsx", ".xls"):
        try:
            fields, full_text = _extract_xlsx(file_path, include_filled, context)
        except (IndexError, Exception) as e:
            context["log"](f"openpyxl 파싱 실패, lxml 직접 파싱으로 재시도: {e}")
            fields, full_text = _extract_xlsx_raw(file_path, include_filled, context)
    elif ext == ".hwpx":
        fields, full_text = _extract_hwpx(file_path, include_filled, context)
    elif ext == ".hwp":
        fields, full_text = _extract_hwp(file_path, include_filled, context)
    else:
        raise ValueError(f"지원하지 않는 형식: {ext}")

    context["progress"](0.9)
    context["log"](f"빈칸 {len(fields)}개 추출 완료")
    context["progress"](1.0)

    return {
        "빈칸목록": json.dumps(fields, ensure_ascii=False, indent=2),
        "원본텍스트": full_text,
    }


# ── XLSX ──────────────────────────────────────────────

def _extract_xlsx(path: str, include_filled: bool, context) -> tuple[list, str]:
    import openpyxl

    context["log"]("엑셀 양식 분석 중...")
    wb = openpyxl.load_workbook(path, data_only=True)
    fields = []
    text_parts = []
    field_id = 0

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        text_parts.append(f"=== 시트: {sheet_name} ===")

        # 모든 셀 스캔
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
            row_texts = []
            for cell in row:
                val = cell.value
                if val is not None:
                    row_texts.append(str(val))
                else:
                    row_texts.append("")

                # 빈 셀 감지 (수식 셀 제외)
                is_empty = val is None or (isinstance(val, str) and val.strip() == "")
                is_formula = isinstance(val, str) and val.startswith("=")

                if is_formula:
                    continue

                if is_empty or include_filled:
                    # 인접 라벨 찾기
                    label = _find_xlsx_label(ws, cell.row, cell.column)
                    if not label and is_empty:
                        # 라벨 없는 빈 셀은 무시 (테두리가 있는 셀만)
                        if not _has_border(cell):
                            continue

                    field_id += 1
                    fields.append({
                        "id": f"xlsx_{field_id}",
                        "sheet": sheet_name,
                        "cell_ref": cell.coordinate,
                        "row": cell.row,
                        "col": cell.column,
                        "label": label or f"({cell.coordinate})",
                        "context": _get_xlsx_context(ws, cell.row, cell.column),
                        "current_value": str(val) if val is not None else "",
                        "is_empty": is_empty,
                        "value_type": "text",
                    })

            if any(t for t in row_texts):
                text_parts.append(" | ".join(row_texts))

    wb.close()
    return fields, "\n".join(text_parts)


def _find_xlsx_label(ws, row: int, col: int) -> str:
    """빈 셀의 왼쪽 또는 위쪽에서 라벨(텍스트) 탐색."""
    # 왼쪽 셀
    if col > 1:
        left = ws.cell(row=row, column=col - 1).value
        if left and isinstance(left, str) and left.strip():
            return left.strip()
    # 위쪽 셀
    if row > 1:
        above = ws.cell(row=row - 1, column=col).value
        if above and isinstance(above, str) and above.strip():
            return above.strip()
    # 왼쪽 2칸
    if col > 2:
        left2 = ws.cell(row=row, column=col - 2).value
        if left2 and isinstance(left2, str) and left2.strip():
            return left2.strip()
    return ""


def _has_border(cell) -> bool:
    """셀에 테두리가 있는지 확인."""
    border = cell.border
    if border is None:
        return False
    for side in [border.left, border.right, border.top, border.bottom]:
        if side and side.style and side.style != "none":
            return True
    return False


def _get_xlsx_context(ws, row: int, col: int) -> str:
    """빈 셀 주변의 텍스트를 모아 맥락 제공."""
    parts = []
    for r in range(max(1, row - 1), min(ws.max_row + 1, row + 2)):
        for c in range(max(1, col - 2), min(ws.max_column + 1, col + 3)):
            v = ws.cell(row=r, column=c).value
            if v is not None and str(v).strip():
                parts.append(str(v).strip())
    return " | ".join(parts[:10])


# ── XLSX fallback (lxml 직접 파싱) ──────────────────────

def _extract_xlsx_raw(path: str, include_filled: bool, context) -> tuple[list, str]:
    """openpyxl 실패 시 lxml으로 xlsx XML을 직접 파싱하여 빈칸 추출."""
    import re as _re
    from lxml import etree

    context["log"]("엑셀 양식 분석 중 (lxml 직접 파싱)...")

    NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns = {"x": NS}

    fields = []
    text_parts = []
    field_id = 0

    with zipfile.ZipFile(path, "r") as zf:
        # shared strings
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_xml = etree.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_xml.findall(".//x:si", ns):
                shared_strings.append("".join(si.itertext()))

        # 시트 이름 목록
        wb_xml = etree.fromstring(zf.read("xl/workbook.xml"))
        sheet_names = [s.get("name") for s in wb_xml.findall(".//x:sheets/x:sheet", ns)]

        # 시트 파일 목록 (rels에서)
        rels_xml = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid_map = {}
        for rel in rels_xml:
            rid_map[rel.get("Id")] = rel.get("Target")

        wb_sheets = wb_xml.findall(".//x:sheets/x:sheet", ns)

        for sheet_idx, sheet_elem in enumerate(wb_sheets):
            sheet_name = sheet_elem.get("name", f"Sheet{sheet_idx+1}")
            rid = sheet_elem.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rid_map.get(rid, f"worksheets/sheet{sheet_idx+1}.xml")
            sheet_path = f"xl/{target}" if not target.startswith("xl/") else target

            if sheet_path not in zf.namelist():
                continue

            sheet_xml = etree.fromstring(zf.read(sheet_path))
            text_parts.append(f"=== 시트: {sheet_name} ===")

            # 셀 데이터를 dict로 수집: (row, col) → value
            cell_data: dict[tuple[int, int], str] = {}
            max_row = 0
            max_col = 0

            for row_elem in sheet_xml.findall(".//x:sheetData/x:row", ns):
                for c_elem in row_elem.findall("x:c", ns):
                    ref = c_elem.get("r", "")
                    if not ref:
                        continue

                    # 셀 참조 파싱 (A1 → row=1, col=1)
                    m = _re.match(r"([A-Z]+)(\d+)", ref)
                    if not m:
                        continue
                    col_str, row_num = m.group(1), int(m.group(2))
                    col_num = _col_letter_to_num(col_str)
                    max_row = max(max_row, row_num)
                    max_col = max(max_col, col_num)

                    # 값 추출
                    t = c_elem.get("t", "")
                    v_elem = c_elem.find("x:v", ns)
                    val = v_elem.text if v_elem is not None else ""

                    if t == "s" and val:
                        idx = int(val)
                        val = shared_strings[idx] if idx < len(shared_strings) else val

                    # 수식 셀 (f 태그)
                    f_elem = c_elem.find("x:f", ns)
                    is_formula = f_elem is not None

                    cell_data[(row_num, col_num)] = val if val else ""

                    if is_formula:
                        continue  # 수식 셀은 빈칸 후보에서 제외

                    is_empty = not val or (isinstance(val, str) and not val.strip())

                    if is_empty or include_filled:
                        # 인접 라벨 찾기
                        label = _find_raw_label(cell_data, row_num, col_num)
                        if not label and is_empty:
                            continue  # 라벨 없는 빈 셀 무시 (border 확인 불가)

                        field_id += 1
                        context_text = _get_raw_context(cell_data, row_num, col_num)
                        fields.append({
                            "id": f"xlsx_{field_id}",
                            "sheet": sheet_name,
                            "cell_ref": ref,
                            "row": row_num,
                            "col": col_num,
                            "label": label or f"({ref})",
                            "context": context_text,
                            "current_value": val if val else "",
                            "is_empty": is_empty,
                            "value_type": "text",
                        })

            # text_parts 구성
            for r in range(1, max_row + 1):
                row_vals = []
                for c in range(1, max_col + 1):
                    row_vals.append(cell_data.get((r, c), ""))
                if any(v for v in row_vals):
                    text_parts.append(" | ".join(row_vals))

    context["log"](f"lxml 파싱 완료: 빈칸 {len(fields)}개")
    return fields, "\n".join(text_parts)


def _col_letter_to_num(letters: str) -> int:
    """A→1, B→2, ..., Z→26, AA→27, ..."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _num_to_col_letter(n: int) -> str:
    """1→A, 2→B, ..., 26→Z, 27→AA, ..."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _find_raw_label(cell_data: dict, row: int, col: int) -> str:
    """dict 기반 인접 라벨 찾기."""
    # 왼쪽
    left = cell_data.get((row, col - 1), "")
    if left and left.strip():
        return left.strip()
    # 위쪽
    above = cell_data.get((row - 1, col), "")
    if above and above.strip():
        return above.strip()
    # 왼쪽 2칸
    left2 = cell_data.get((row, col - 2), "")
    if left2 and left2.strip():
        return left2.strip()
    return ""


def _get_raw_context(cell_data: dict, row: int, col: int) -> str:
    """dict 기반 주변 맥락."""
    parts = []
    for r in range(row - 1, row + 2):
        for c in range(col - 2, col + 3):
            v = cell_data.get((r, c), "")
            if v and v.strip():
                parts.append(v.strip())
    return " | ".join(parts[:10])


# ── HWPX ─────────────────────────────────────────────

def _extract_hwpx(path: str, include_filled: bool, context) -> tuple[list, str]:
    """병합-인지 그리드 추출 (engine/hwpml/hwpx_grid).

    표를 (행,열) 그리드 + 병합 맵으로 해석하고, 빈칸마다 행헤더×열헤더를
    코드로 계산한다. LLM은 의미 매칭만 하면 된다.
    셀 ID 형식: s{섹션}_t{표}_r{행}_c{열} — form_fill과 공유하는 주소 체계.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from engine.hwpml.hwpx_grid import parse_hwpx, extract_blank_fields

    context["log"]("HWPX 양식 분석 중 (병합-인지 그리드)...")

    doc = parse_hwpx(path)
    fields = extract_blank_fields(doc, include_filled=include_filled)
    full_text = doc.render_text(mark_blanks=True)

    # 누름틀(폼 필드)은 그리드와 별개로 보존
    from lxml import etree
    field_id = 0
    with zipfile.ZipFile(path, "r") as zf:
        section_files = sorted(
            [n for n in zf.namelist() if "section" in n.lower() and n.endswith(".xml")]
        )
        for sec_file in section_files:
            try:
                root = etree.fromstring(zf.read(sec_file))
            except etree.XMLSyntaxError:
                continue
            for elem in root.iter():
                tag = etree.QName(elem.tag).localname if "}" in str(elem.tag) else str(elem.tag)
                if tag in ("fieldBegin", "FIELDBEGIN"):
                    name = elem.get("name", "") or elem.get("Name", "")
                    field_id += 1
                    fields.append({
                        "id": f"hwpx_field_{field_id}",
                        "label": name or f"필드{field_id}",
                        "context": "",
                        "field_name": name,
                        "xpath": sec_file,
                        "current_value": "",
                        "is_empty": True,
                        "value_type": "field",
                    })

    context["log"](f"표 {len(doc.tables)}개, 그리드 빈칸 {sum(1 for f in fields if f.get('value_type') == 'text')}개")
    return fields, full_text


# ── HWP (COM) ────────────────────────────────────────

def _extract_hwp(path: str, include_filled: bool, context) -> tuple[list, str]:
    """HWP 바이너리 — olefile로 텍스트 추출 (COM 불필요)."""
    context["log"]("HWP 텍스트 분석 중...")

    # olefile로 텍스트 추출
    full_text = ""
    try:
        import olefile
        ole = olefile.OleFileIO(path)
        if ole.exists("PrvText"):
            data = ole.openstream("PrvText").read()
            full_text = data.decode("utf-16-le", errors="ignore")
        else:
            texts = []
            for stream in ole.listdir():
                name = "/".join(stream)
                if "BodyText" in name:
                    raw = ole.openstream(stream).read()
                    text = raw.decode("utf-16-le", errors="ignore")
                    text = "".join(c for c in text if c.isprintable() or c in "\n\r\t")
                    if text.strip():
                        texts.append(text.strip())
            full_text = "\n\n".join(texts)
        ole.close()
    except Exception as e:
        context["log"](f"olefile 추출 실패: {e}")

    if not full_text:
        try:
            from hwp5.hwp5txt import extract_text
            import io
            buf = io.StringIO()
            extract_text(path, buf)
            full_text = buf.getvalue()
        except Exception:
            pass

    # 추출 완전 실패 시 무음 성공(빈 양식) 대신 명확히 실패시킨다
    if not full_text or not full_text.strip():
        raise RuntimeError(
            f"HWP 텍스트 추출 실패: {os.path.basename(path)} — "
            f"olefile/hwp5 미설치이거나 지원하지 않는 형식입니다. "
            f".hwpx로 저장 후 사용하거나 'pip install olefile'을 설치하세요."
        )

    # 텍스트 기반 빈칸 추출 — 빈 괄호, 밑줄, 빈 칸 패턴
    import re
    fields = []
    field_id = 0
    lines = full_text.split("\n")
    prev_line = ""

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # 빈 괄호 패턴: (     ), [     ], 「    」
        for m in re.finditer(r'[\(\[「]\s{2,}[\)\]」]', stripped):
            field_id += 1
            label = prev_line.strip()[-20:] if prev_line.strip() else f"행{line_num}"
            fields.append({
                "id": f"hwp_{field_id}",
                "label": label,
                "context": stripped[:50],
                "line": line_num,
                "current_value": "",
                "is_empty": True,
                "value_type": "text",
            })

        # 밑줄 패턴: _____
        for m in re.finditer(r'_{3,}', stripped):
            field_id += 1
            # 밑줄 앞의 텍스트를 라벨로
            before = stripped[:m.start()].strip()
            label = before[-20:] if before else f"행{line_num}"
            fields.append({
                "id": f"hwp_{field_id}",
                "label": label,
                "context": stripped[:50],
                "line": line_num,
                "current_value": "",
                "is_empty": True,
                "value_type": "text",
            })

        if stripped:
            prev_line = stripped

    context["log"](f"텍스트 {len(lines)}줄, 빈칸 패턴 {len(fields)}개")
    return fields, full_text
