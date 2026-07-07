"""Excel 라이브 제어 (win32com) — 읽기/실행."""

from __future__ import annotations

from .base import ActionResult, _col_letter


class ExcelMixin:
    """LiveController에 Excel 읽기/실행 기능을 제공하는 mixin."""

    def _read_excel(self, xl) -> str:
        """Excel 활성 시트 내용."""
        parts = []
        try:
            wb = xl.ActiveWorkbook
            if not wb:
                return "[Excel] 열린 문서 없음"

            parts.append(f"파일: {wb.Name}")
            parts.append(f"시트 목록: {', '.join(s.Name for s in wb.Sheets)}")
            parts.append("")

            ws = xl.ActiveSheet
            parts.append(f"=== 시트: {ws.Name} ===")

            used = ws.UsedRange
            if used:
                data = used.Value
                if data is None:
                    parts.append("(빈 시트)")
                elif isinstance(data, tuple):
                    for r_idx, row in enumerate(data, start=used.Row):
                        if isinstance(row, tuple):
                            cells = []
                            for c_idx, val in enumerate(row):
                                if val is not None:
                                    cells.append(f"{_col_letter(c_idx + used.Column)}{r_idx}={val}")
                            if cells:
                                parts.append(" | ".join(cells))
                        elif row is not None:
                            parts.append(f"A{r_idx}={row}")
                else:
                    parts.append(f"A1={data}")
        except Exception as e:
            return f"[Excel 읽기 오류] {e}"

        return "\n".join(parts)

    def _exec_excel(self, xl, action: str, p: dict) -> ActionResult:
        wb = xl.ActiveWorkbook
        if not wb:
            # Workbook이 없으면 자동 생성
            xl.Workbooks.Add()
            wb = xl.ActiveWorkbook
            if not wb:
                return ActionResult(False, "열린 Excel 문서 없음")

        ws = wb.ActiveSheet

        if action == "set_cell":
            cell_ref = p["cell"]  # "B3" 또는 "시트1!B3"
            value = p["value"]
            if "!" in cell_ref:
                sheet_name, cell_ref = cell_ref.split("!", 1)
                ws = wb.Sheets(sheet_name)
            ws.Range(cell_ref).Value = value
            return ActionResult(True, f"{cell_ref} = {value}")

        if action == "set_cells":
            # 여러 셀 한번에: {"cells": {"A1": "값1", "B2": "값2"}}
            cells = p["cells"]
            for ref, val in cells.items():
                target_ws = ws
                if "!" in ref:
                    sn, ref = ref.split("!", 1)
                    target_ws = wb.Sheets(sn)
                target_ws.Range(ref).Value = val
            return ActionResult(True, f"{len(cells)}개 셀 설정")

        if action == "get_cell":
            cell_ref = p["cell"]
            val = ws.Range(cell_ref).Value
            return ActionResult(True, f"{cell_ref} = {val}", data=val)

        if action == "get_range":
            range_ref = p["range"]  # "A1:C10"
            data = ws.Range(range_ref).Value
            return ActionResult(True, f"{range_ref} 읽기", data=data)

        if action == "active_sheet":
            sheet_name = p["sheet"]
            wb.Sheets(sheet_name).Activate()
            return ActionResult(True, f"시트 전환: {sheet_name}")

        if action == "add_sheet":
            name = p.get("name", "새 시트")
            new_ws = wb.Sheets.Add()
            new_ws.Name = name
            return ActionResult(True, f"시트 추가: {name}")

        if action == "insert_row":
            row = int(p["row"])
            ws.Rows(row).Insert()
            return ActionResult(True, f"{row}행 삽입")

        if action == "delete_row":
            row = int(p["row"])
            ws.Rows(row).Delete()
            return ActionResult(True, f"{row}행 삭제")

        if action == "auto_fit":
            ws.UsedRange.Columns.AutoFit()
            return ActionResult(True, "열 너비 자동 조정")

        if action == "save":
            wb.Save()
            return ActionResult(True, "저장 완료")

        # ── 디자인 액션 ──

        if action == "format_range":
            rng_ref = p["range"]  # "A1:D1" 또는 "A1"
            rng = ws.Range(rng_ref)
            if "bg_color" in p:
                r, g, b = int(p["bg_color"][1:3], 16), int(p["bg_color"][3:5], 16), int(p["bg_color"][5:7], 16)
                rng.Interior.Color = r + g * 256 + b * 65536
            if "bold" in p:
                rng.Font.Bold = bool(p["bold"])
            if "font_size" in p:
                rng.Font.Size = int(p["font_size"])
            if "text_color" in p:
                r, g, b = int(p["text_color"][1:3], 16), int(p["text_color"][3:5], 16), int(p["text_color"][5:7], 16)
                rng.Font.Color = r + g * 256 + b * 65536
            if "font_name" in p:
                rng.Font.Name = p["font_name"]
            if "align" in p:
                align_map = {"left": -4131, "center": -4108, "right": -4152}
                rng.HorizontalAlignment = align_map.get(p["align"], -4108)
            if "v_align" in p:
                va_map = {"top": -4160, "center": -4108, "bottom": -4107}
                rng.VerticalAlignment = va_map.get(p["v_align"], -4108)
            if "number_format" in p:
                rng.NumberFormat = p["number_format"]
            if "wrap" in p:
                rng.WrapText = bool(p["wrap"])
            return ActionResult(True, f"{rng_ref} 서식 적용")

        if action == "set_col_width":
            col = p["col"]  # "A" 또는 "A:D"
            width = p["width"]
            ws.Columns(col).ColumnWidth = width
            return ActionResult(True, f"열 {col} 너비 = {width}")

        if action == "set_row_height":
            row = int(p["row"])
            height = p["height"]
            ws.Rows(row).RowHeight = height
            return ActionResult(True, f"{row}행 높이 = {height}")

        if action == "merge_range":
            rng_ref = p["range"]
            ws.Range(rng_ref).Merge()
            return ActionResult(True, f"{rng_ref} 병합")

        if action == "border":
            rng_ref = p["range"]
            rng = ws.Range(rng_ref)
            style = p.get("style", "thin")
            # xlContinuous=1, xlThin=1, xlMedium=2, xlThick=4
            weight_map = {"thin": 2, "medium": -4138, "thick": 4}
            w = weight_map.get(style, 2)
            for edge in range(7, 13):  # xlEdgeLeft(7) ~ xlInsideHorizontal(12)
                try:
                    rng.Borders(edge).LineStyle = 1
                    rng.Borders(edge).Weight = w
                except Exception:
                    pass
            return ActionResult(True, f"{rng_ref} 테두리 적용")

        if action == "set_formula":
            cell_ref = p["cell"]
            formula = p["formula"]
            ws.Range(cell_ref).Formula = formula
            return ActionResult(True, f"{cell_ref} 수식 = {formula}")

        return ActionResult(False, f"알 수 없는 Excel 명령: {action}")
