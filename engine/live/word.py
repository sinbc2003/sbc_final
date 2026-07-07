"""Word 라이브 제어 (win32com) — 읽기/실행."""

from __future__ import annotations

from .base import ActionResult


class WordMixin:
    """LiveController에 Word 읽기/실행 기능을 제공하는 mixin."""

    def _read_word(self, word) -> str:
        """Word 문서 내용."""
        parts = []
        try:
            doc = word.ActiveDocument
            if not doc:
                return "[Word] 열린 문서 없음"

            parts.append(f"파일: {doc.Name}")
            try:
                pages = doc.ComputeStatistics(2)  # wdStatisticPages
                parts.append(f"페이지: {pages}페이지")
            except Exception:
                pass
            parts.append("")

            # 문단별 텍스트
            for i in range(1, doc.Paragraphs.Count + 1):
                text = doc.Paragraphs(i).Range.Text.rstrip("\r")
                if text.strip():
                    parts.append(f"[P{i}] {text}")
                if i >= 200:
                    parts.append(f"... (이하 생략, 총 {doc.Paragraphs.Count}문단)")
                    break

            # 표 정보
            if doc.Tables.Count > 0:
                parts.append("")
                for t_idx in range(1, min(doc.Tables.Count + 1, 11)):
                    tbl = doc.Tables(t_idx)
                    parts.append(f"=== 표 {t_idx} ({tbl.Rows.Count}x{tbl.Columns.Count}) ===")
                    for r in range(1, min(tbl.Rows.Count + 1, 21)):
                        row_vals = []
                        for c in range(1, tbl.Columns.Count + 1):
                            try:
                                cell_text = tbl.Cell(r, c).Range.Text.rstrip("\r\x07")
                                row_vals.append(cell_text)
                            except Exception:
                                row_vals.append("")
                        parts.append(" | ".join(row_vals))
        except Exception as e:
            return f"[Word 읽기 오류] {e}"

        return "\n".join(parts)

    def _exec_word(self, word, action: str, p: dict) -> ActionResult:
        doc = word.ActiveDocument
        if not doc:
            return ActionResult(False, "열린 Word 문서 없음")

        if action == "insert_text":
            text = p["text"]
            word.Selection.TypeText(text)
            return ActionResult(True, f"텍스트 삽입: {text[:50]}")

        if action == "replace_text":
            find_text = p.get("find", p.get("old_text", ""))
            replace_text = p.get("replace", p.get("new_text", ""))
            rng = doc.Content
            rng.Find.Execute(find_text, False, False, False, False, False, True, 1, False, replace_text, 2)
            return ActionResult(True, f"'{find_text}' → '{replace_text}'")

        if action == "set_paragraph":
            para_idx = int(p["paragraph"])
            text = p["text"]
            if para_idx < 1 or para_idx > doc.Paragraphs.Count:
                return ActionResult(False, f"문단 번호 범위 초과: {para_idx}")
            doc.Paragraphs(para_idx).Range.Text = text + "\r"
            return ActionResult(True, f"문단 {para_idx} 수정")

        if action == "append_paragraph":
            text = p["text"]
            rng = doc.Content
            rng.InsertAfter("\r" + text)
            return ActionResult(True, f"문단 추가: {text[:50]}")

        if action == "format_paragraph":
            raw = p.get("paragraph", 1)
            try:
                para_idx = int(raw)
            except (ValueError, TypeError):
                # LLM이 숫자가 아닌 값 전달 시 마지막 문단
                para_idx = doc.Paragraphs.Count
            if para_idx < 1:
                para_idx = 1
            if para_idx > doc.Paragraphs.Count:
                para_idx = doc.Paragraphs.Count
            para = doc.Paragraphs(para_idx)
            rng = para.Range
            if "font_size" in p and p["font_size"] is not None:
                rng.Font.Size = float(p["font_size"])
            if "font_name" in p and p["font_name"] is not None:
                rng.Font.Name = p["font_name"]
            if "bold" in p and p["bold"] is not None:
                rng.Font.Bold = bool(p["bold"])
            if "italic" in p and p["italic"] is not None:
                rng.Font.Italic = bool(p["italic"])
            if "align" in p and p["align"] is not None:
                align_map = {"left": 0, "center": 1, "right": 2, "justify": 3}
                val = str(p["align"]).lower()
                para.Alignment = align_map.get(val, 0)
            return ActionResult(True, f"문단 {para_idx} 서식 변경")

        if action == "set_table_cell":
            table_idx = int(p.get("table", 1))
            row = int(p["row"])
            col = int(p["col"])
            text = p["text"]
            if table_idx > doc.Tables.Count:
                return ActionResult(False, f"표 {table_idx} 없음")
            tbl = doc.Tables(table_idx)
            tbl.Cell(row, col).Range.Text = text
            return ActionResult(True, f"표{table_idx}[{row},{col}] = {text}")

        if action == "insert_page_break":
            rng = doc.Content
            rng.Collapse(0)  # wdCollapseEnd
            rng.InsertBreak(7)  # wdPageBreak
            return ActionResult(True, "페이지 나누기 삽입")

        if action == "save":
            doc.Save()
            return ActionResult(True, "저장 완료")

        if action == "save_as":
            path = p["path"]
            doc.SaveAs2(path)
            return ActionResult(True, f"저장: {path}")

        return ActionResult(False, f"알 수 없는 Word 명령: {action}")
