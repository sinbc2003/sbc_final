"""PowerPoint 라이브 제어 (win32com) — 읽기/실행 + 액션 정렬 유틸."""

from __future__ import annotations

from .base import ActionResult


class PptMixin:
    """LiveController에 PowerPoint 읽기/실행 기능을 제공하는 mixin."""

    @staticmethod
    def _ensure_ppt_slides(pres, n: int):
        """슬라이드가 n개 이상이 되도록 빈 슬라이드 자동 생성."""
        while pres.Slides.Count < n:
            pres.Slides.Add(pres.Slides.Count + 1, 2)  # 2 = ppLayoutText (제목+내용)

    @staticmethod
    def reorder_ppt_actions(actions: list[dict]) -> list[dict]:
        """PPT 액션 리스트에서 add_slide를 먼저 실행하도록 정렬."""
        return sorted(actions, key=lambda a: 0 if a.get("action") == "add_slide" else 1)

    def _read_ppt(self, ppt) -> str:
        """PowerPoint 슬라이드 내용."""
        parts = []
        try:
            pres = ppt.ActivePresentation
            if not pres:
                return "[PowerPoint] 열린 문서 없음"

            parts.append(f"파일: {pres.Name}")
            parts.append(f"슬라이드: {pres.Slides.Count}장")
            parts.append("")

            for i, slide in enumerate(pres.Slides, 1):
                parts.append(f"=== 슬라이드 {i} ===")
                for shape in slide.Shapes:
                    if shape.HasTextFrame:
                        text = shape.TextFrame.TextRange.Text
                        if text.strip():
                            parts.append(f"  [{shape.Name}] {text}")
                    if shape.HasTable:
                        tbl = shape.Table
                        for r in range(1, tbl.Rows.Count + 1):
                            row_vals = []
                            for c in range(1, tbl.Columns.Count + 1):
                                row_vals.append(tbl.Cell(r, c).Shape.TextFrame.TextRange.Text)
                            parts.append(f"  표: {' | '.join(row_vals)}")
                # 슬라이드 노트
                try:
                    notes = slide.NotesPage.Shapes[1].TextFrame.TextRange.Text
                    if notes.strip():
                        parts.append(f"  [노트] {notes}")
                except Exception:
                    pass
                parts.append("")
        except Exception as e:
            return f"[PPT 읽기 오류] {e}"

        return "\n".join(parts)

    def _exec_ppt(self, ppt, action: str, p: dict) -> ActionResult:
        pres = ppt.ActivePresentation
        if not pres:
            return ActionResult(False, "열린 PowerPoint 문서 없음")

        # slide 파라미터가 있는 액션은 해당 슬라이드가 존재하도록 보장 (안전망)
        if "slide" in p and action not in ("add_slide", "delete_slide"):
            slide_idx = int(p["slide"])
            self._ensure_ppt_slides(pres, slide_idx)

        if action == "set_text":
            slide_idx = int(p["slide"])
            shape_idx = int(p.get("shape", 0))
            text = p["text"]
            slide = pres.Slides(slide_idx)
            # shape_idx=0이면 제목, 1이면 본문
            shape = slide.Shapes(shape_idx + 1)
            shape.TextFrame.TextRange.Text = text
            return ActionResult(True, f"슬라이드 {slide_idx} 텍스트 수정")

        if action == "add_slide":
            layout = int(p.get("layout", 2))  # 2 = 제목+내용
            idx = pres.Slides.Count + 1
            slide = pres.Slides.Add(idx, layout)
            if "title" in p:
                try:
                    slide.Shapes(1).TextFrame.TextRange.Text = p["title"]
                except Exception:
                    pass
            if "content" in p:
                try:
                    slide.Shapes(2).TextFrame.TextRange.Text = p["content"]
                except Exception:
                    pass
            return ActionResult(True, f"슬라이드 {idx} 추가")

        if action == "set_note":
            slide_idx = int(p["slide"])
            text = p["text"]
            slide = pres.Slides(slide_idx)
            slide.NotesPage.Shapes(2).TextFrame.TextRange.Text = text
            return ActionResult(True, f"슬라이드 {slide_idx} 노트 수정")

        if action == "delete_slide":
            slide_idx = int(p["slide"])
            if slide_idx > pres.Slides.Count:
                return ActionResult(False, f"슬라이드 {slide_idx} 없음 (총 {pres.Slides.Count}장)")
            pres.Slides(slide_idx).Delete()
            return ActionResult(True, f"슬라이드 {slide_idx} 삭제")

        if action == "set_table_cell":
            slide_idx = int(p["slide"])
            shape_name = p.get("shape", "")
            row = int(p["row"])
            col = int(p["col"])
            text = p["text"]
            slide = pres.Slides(slide_idx)
            for shape in slide.Shapes:
                if shape.HasTable:
                    if not shape_name or shape.Name == shape_name:
                        shape.Table.Cell(row, col).Shape.TextFrame.TextRange.Text = text
                        return ActionResult(True, f"표[{row},{col}] = {text}")
            return ActionResult(False, "표를 찾을 수 없음")

        if action == "save":
            pres.Save()
            return ActionResult(True, "저장 완료")

        # ── 디자인 액션 ──

        if action == "set_slide_bg":
            slide_idx = int(p["slide"])
            color = int(p["color"], 16) if isinstance(p["color"], str) else int(p["color"])
            slide = pres.Slides(slide_idx)
            slide.FollowMasterBackground = 0
            slide.Background.Fill.Solid()
            slide.Background.Fill.ForeColor.RGB = color
            return ActionResult(True, f"슬라이드 {slide_idx} 배경색 변경")

        if action == "format_text":
            slide_idx = int(p["slide"])
            shape_idx = int(p.get("shape", 0))
            slide = pres.Slides(slide_idx)
            if shape_idx + 1 > slide.Shapes.Count:
                return ActionResult(False, f"슬라이드 {slide_idx}에 shape {shape_idx} 없음")
            shape = slide.Shapes(shape_idx + 1)
            tr = shape.TextFrame.TextRange
            if "size" in p:
                tr.Font.Size = int(p["size"])
            if "bold" in p:
                tr.Font.Bold = bool(p["bold"])
            if "color" in p:
                c = int(p["color"], 16) if isinstance(p["color"], str) else int(p["color"])
                tr.Font.Color.RGB = c
            if "name" in p:
                tr.Font.Name = p["name"]
            if "align" in p:
                # 1=left, 2=center, 3=right
                shape.TextFrame.TextRange.ParagraphFormat.Alignment = int(p["align"])
            return ActionResult(True, f"슬라이드 {slide_idx} 텍스트 서식 변경")

        if action == "add_shape":
            slide_idx = int(p["slide"])
            left = int(p.get("left", 0))
            top = int(p.get("top", 0))
            width = int(p.get("width", 200))
            height = int(p.get("height", 50))
            slide = pres.Slides(slide_idx)
            # msoShapeRectangle=1, msoShapeRoundedRectangle=5
            shape_type = int(p.get("shape_type", 1))
            shape = slide.Shapes.AddShape(shape_type, left, top, width, height)
            if "fill_color" in p:
                c = int(p["fill_color"], 16) if isinstance(p["fill_color"], str) else int(p["fill_color"])
                shape.Fill.Solid()
                shape.Fill.ForeColor.RGB = c
            if "text" in p:
                shape.TextFrame.TextRange.Text = p["text"]
                if "text_color" in p:
                    tc = int(p["text_color"], 16) if isinstance(p["text_color"], str) else int(p["text_color"])
                    shape.TextFrame.TextRange.Font.Color.RGB = tc
                if "text_size" in p:
                    shape.TextFrame.TextRange.Font.Size = int(p["text_size"])
            if "line_color" in p:
                lc = int(p["line_color"], 16) if isinstance(p["line_color"], str) else int(p["line_color"])
                shape.Line.ForeColor.RGB = lc
            else:
                shape.Line.Visible = 0
            return ActionResult(True, f"슬라이드 {slide_idx} 도형 추가")

        if action == "set_shape_fill":
            slide_idx = int(p["slide"])
            shape_idx = int(p["shape"])
            color = int(p["color"], 16) if isinstance(p["color"], str) else int(p["color"])
            slide = pres.Slides(slide_idx)
            if shape_idx + 1 > slide.Shapes.Count:
                return ActionResult(False, f"슬라이드 {slide_idx}에 shape {shape_idx} 없음")
            shape = slide.Shapes(shape_idx + 1)
            shape.Fill.Solid()
            shape.Fill.ForeColor.RGB = color
            return ActionResult(True, f"도형 채우기 색상 변경")

        return ActionResult(False, f"알 수 없는 PPT 명령: {action}")
