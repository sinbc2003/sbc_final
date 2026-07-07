"""한/글 라이브 제어 — 실제 편집은 HwpController(pyhwpx)에 위임.

여기서는 라이브 액션명 → HwpController 명령 매핑과 액션 정렬만 담당한다.
"""

from __future__ import annotations

from .base import ActionResult, _get_hwp_ctrl


class HwpMixin:
    """LiveController에 한/글 읽기/실행 기능을 제공하는 mixin."""

    @staticmethod
    def reorder_hwp_block_actions(actions: list[dict]) -> list[dict]:
        """HWP block_id 기반 편집 액션을 문서 뒤쪽부터 실행하도록 정렬.
        앞쪽 셀 편집 시 뒤쪽 셀의 좌표(para_id)가 밀리는 문제 방지."""
        BLOCK_ID_ACTIONS = {
            "replace_cell_content", "delete_cell_content", "replace_paragraph",
            "append_paragraph", "apply_para_style", "replace_table_row",
            "append_table_row", "style_cell", "style_row", "merge_cells",
            "set_table_col_width",
        }

        hwp_ctrl = _get_hwp_ctrl()
        bm = hwp_ctrl._block_manager if hwp_ctrl else None
        if not bm or not bm.blocks:
            return actions

        non_bid = []
        bid = []
        for act in actions:
            action_name = act.get("action", "")
            has_bid = act.get("params", {}).get("block_id")
            if action_name in BLOCK_ID_ACTIONS and has_bid:
                bid.append(act)
            else:
                non_bid.append(act)

        if len(bid) <= 1:
            return actions

        # 문서 뒤쪽 셀부터 편집 → 앞쪽 좌표에 영향 없음
        bid.sort(
            key=lambda a: bm.get_position(str(a["params"]["block_id"])) or (0, 0, 0),
            reverse=True,
        )

        return non_bid + bid

    def _read_hwp(self, _obj) -> str:
        """한/글 문서 전체 텍스트 — HwpController 위임."""
        hwp_ctrl = _get_hwp_ctrl()
        return hwp_ctrl.read_text()

    def _exec_hwp(self, _obj, action: str, p: dict) -> ActionResult:
        """HWP 명령 실행 — HwpController 위임."""
        hwp_ctrl = _get_hwp_ctrl()

        # 기존 액션명 → HwpController 명령 매핑
        action_map = {
            "insert_text": ("insert_text", {"text": p.get("text", "")}),
            "replace_text": ("find_and_replace_all", {"old_text": p.get("find", ""), "new_text": p.get("replace", "")}),
            "save": ("save", {}),
            "save_as": ("save_as", {"path": p.get("path", ""), "format": p.get("format", "HWPX")}),
            "create_table": ("create_table", {"rows": p.get("rows", 2), "cols": p.get("cols", 2), "data": p.get("data")}),
            # blockId 기반 신규 액션들은 그대로 통과
            "replace_cell_content": ("replace_cell_content", {"block_id": p.get("block_id", ""), "new_text": p.get("new_text", "")}),
            "delete_cell_content": ("delete_cell_content", {"block_id": p.get("block_id", "")}),
            "replace_paragraph": ("replace_paragraph", {"block_id": p.get("block_id", ""), "new_text": p.get("new_text", "")}),
            "append_paragraph": ("append_paragraph", {"block_id": p.get("block_id", ""), "new_text": p.get("new_text", "")}),
            "find_and_replace_all": ("find_and_replace_all", {"old_text": p.get("old_text", ""), "new_text": p.get("new_text", "")}),
            "apply_para_style": ("apply_para_style", {
                "block_id": p.get("block_id", ""),
                "font_size": p.get("font_size"), "font_family": p.get("font_family"),
                "align": p.get("align"), "spacing": p.get("spacing"), "indentation": p.get("indentation"),
            }),
            "replace_table_row": ("replace_table_row", {"block_id": p.get("block_id", ""), "row_texts": p.get("row_texts")}),
            "append_table_row": ("append_table_row", {"block_id": p.get("block_id", ""), "row_texts": p.get("row_texts")}),
            "style_cell": ("style_cell", {
                "block_id": p.get("block_id", ""), "bg_color": p.get("bg_color"),
                "align": p.get("align"), "bold": p.get("bold"),
                "font_size": p.get("font_size"), "text_color": p.get("text_color"),
            }),
            "style_row": ("style_row", {
                "block_id": p.get("block_id", ""), "bg_color": p.get("bg_color"),
                "bold": p.get("bold"), "font_size": p.get("font_size"),
                "text_color": p.get("text_color"), "align": p.get("align"),
            }),
            "merge_cells": ("merge_cells", {
                "block_id": p.get("block_id", ""),
                "right": p.get("right", 0), "down": p.get("down", 0),
            }),
            "set_table_col_width": ("set_table_col_width", {
                "block_id": p.get("block_id", ""), "widths": p.get("widths", []),
            }),
            # ── 인덱스 기반 (block_id 불필요) ──
            "style_table_row": ("style_table_row_idx", {
                "table": p.get("table", 1), "row": p.get("row", 0),
                "bg_color": p.get("bg_color"), "bold": p.get("bold"),
                "font_size": p.get("font_size"), "text_color": p.get("text_color"),
                "align": p.get("align"),
            }),
            "style_table_cell": ("style_table_cell_idx", {
                "table": p.get("table", 1), "row": p.get("row", 0), "col": p.get("col", 0),
                "bg_color": p.get("bg_color"), "bold": p.get("bold"),
                "font_size": p.get("font_size"), "text_color": p.get("text_color"),
                "align": p.get("align"),
            }),
            "set_table_widths": ("set_table_widths", {
                "table": p.get("table", 1), "widths": p.get("widths", []),
            }),
            "format_text": ("format_text", {
                "font_size": p.get("font_size"), "bold": p.get("bold"),
                "align": p.get("align"), "text_color": p.get("text_color"),
                "font_family": p.get("font_family"),
            }),
        }

        # set_field — pyhwpx 직접 호출
        if action == "set_field":
            try:
                result = hwp_ctrl.execute("_raw_set_field", field_name=p["field_name"], value=p["value"])
                if result.get("isSuccess"):
                    return ActionResult(True, f"필드 '{p['field_name']}' = {p['value']}")
                return ActionResult(False, result.get("message", "필드 설정 실패"))
            except Exception as e:
                return ActionResult(False, str(e))

        # move 명령 — pyhwpx 직접 호출
        if action == "move_to_start":
            result = hwp_ctrl.execute("_raw_move", direction="start")
            return ActionResult(True, "문서 처음으로 이동")
        if action == "move_to_end":
            result = hwp_ctrl.execute("_raw_move", direction="end")
            return ActionResult(True, "문서 끝으로 이동")

        # 표 셀 직접 채우기 (레거시 호환)
        if action == "fill_table_cell":
            result = hwp_ctrl.execute("replace_cell_content",
                                      block_id=p.get("block_id", ""),
                                      new_text=p.get("text", ""))
            msg = result.get("message", "")
            return ActionResult(result.get("isSuccess", False), msg)

        mapped = action_map.get(action)
        if not mapped:
            return ActionResult(False, f"알 수 없는 HWP 명령: {action}")

        op, kwargs = mapped
        result = hwp_ctrl.execute(op, **kwargs)
        msg = result.get("message", "")
        return ActionResult(result.get("isSuccess", False), msg)
