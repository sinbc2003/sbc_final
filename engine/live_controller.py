"""
라이브 문서 제어 모듈.

실행 중인 한/글, Excel, PowerPoint에 COM API로 연결하여
문서를 읽고 쓴다. LLM 채팅과 결합하여 자연어로 문서를 제어.

사용법:
    ctrl = LiveController()
    apps = ctrl.detect()          # {"hwp": True, "excel": True, "ppt": False}
    content = ctrl.read("hwp")    # 현재 문서 내용
    ctrl.execute("hwp", "insert_text", {"text": "안녕하세요"})
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# HWP 전용 컨트롤러 (pyhwpx 기반)
_hwp_ctrl = None
def _get_hwp_ctrl():
    global _hwp_ctrl
    if _hwp_ctrl is None:
        from engine.hwp_controller import HwpController
        _hwp_ctrl = HwpController()
    return _hwp_ctrl

# ── 앱 정보 ──────────────────────────────────────────

@dataclass
class AppInfo:
    app_type: str           # "hwp" | "excel" | "ppt"
    name: str               # 표시 이름
    connected: bool = False
    doc_name: str = ""      # 현재 열린 문서 이름
    doc_path: str = ""      # 문서 경로


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    data: Any = None


# ── COM 스레드 관련 ──────────────────────────────────
# COM 스레드 직렬화는 server.py의 _com_pool(단일 워커 ThreadPoolExecutor)이 담당.
# LiveController 메서드는 항상 _com_pool 스레드에서 호출되므로 직접 COM 접근 가능.

# ── 메인 컨트롤러 ────────────────────────────────────

class LiveController:
    """실행 중인 오피스 앱을 감지하고 제어."""

    def __init__(self):
        self._connections: dict[str, Any] = {}  # app_type → COM object
        self._is_windows = platform.system() == "Windows"
        self._com_initialized = False

    def _ensure_com_init(self):
        """COM 아파트먼트 초기화 (현재 스레드에서 매 호출 시)."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        self._com_initialized = True

    # ── 감지 ──

    def detect(self) -> dict[str, AppInfo]:
        """실행 중인 앱을 프로세스 목록으로 감지하고, 미연결 앱은 자동 연결 시도."""
        result = {
            "hwp": AppInfo("hwp", "한/글", "hwp" in self._connections),
            "excel": AppInfo("excel", "Excel", "excel" in self._connections),
            "ppt": AppInfo("ppt", "PowerPoint", "ppt" in self._connections),
            "word": AppInfo("word", "Word", "word" in self._connections),
        }

        if not self._is_windows:
            return result

        # 프로세스 감지
        running = set()
        try:
            import subprocess
            ps = subprocess.run(
                ["tasklist", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=3,
            )
            out = ps.stdout.lower()
            if "hwp.exe" in out:
                running.add("hwp")
            if "excel.exe" in out:
                running.add("excel")
            if "powerpnt.exe" in out:
                running.add("ppt")
            if "winword.exe" in out:
                running.add("word")
        except Exception:
            pass

        # 프로세스 상태 반영 (자동 연결 안 함 — 블로킹 방지)
        for app_type in running:
            if app_type == "hwp":
                # HWP는 HwpController 상태 확인
                hwp_ctrl = _get_hwp_ctrl()
                if hwp_ctrl.connected:
                    result["hwp"].connected = True
                    result["hwp"].doc_name = "연결됨"
                else:
                    result["hwp"].doc_name = "(실행 중)"
            elif app_type in self._connections:
                result[app_type].connected = True
                result[app_type].doc_name = "연결됨"
            else:
                result[app_type].doc_name = "(실행 중)"

        # 연결 있지만 프로세스 없음 → 연결 해제
        for app_type in list(self._connections.keys()):
            if app_type not in running:
                del self._connections[app_type]
                result[app_type].connected = False
                result[app_type].doc_name = ""

        # HWP 프로세스 종료 시 HwpController도 해제
        if "hwp" not in running and _get_hwp_ctrl().connected:
            _get_hwp_ctrl().disconnect()
            result["hwp"].connected = False
            result["hwp"].doc_name = ""

        return result

    def connect(self, app_type: str) -> ActionResult:
        """앱에 COM으로 연결. server.py의 _com_pool 스레드에서 호출됨."""
        if not self._is_windows:
            return ActionResult(False, "Windows에서만 사용 가능")

        self._ensure_com_init()
        try:
            import win32com.client

            if app_type == "hwp":
                hwp_ctrl = _get_hwp_ctrl()
                result = hwp_ctrl.connect()
                if result.get("success"):
                    self._connections["hwp"] = True
                    doc = result.get("document", "")
                    return ActionResult(True, f"한/글 연결 성공: {doc}")
                else:
                    return ActionResult(False, f"한/글 연결 실패: {result.get('error', '')}")

            elif app_type == "excel":
                xl = None
                # 1. 기존 연결이 유효하고 문서가 있으면 재사용
                existing = self._connections.get("excel")
                if existing:
                    try:
                        cnt = existing.Workbooks.Count
                        if cnt > 0 and existing.Visible:
                            doc = existing.ActiveWorkbook.Name
                            logger.info(f"Excel: 기존 연결 재사용 ({doc})")
                            return ActionResult(True, f"Excel 연결 성공: {doc}")
                        else:
                            # 유령 인스턴스 정리
                            logger.info("Excel: 기존 연결 비활성, 정리")
                            try:
                                existing.Quit()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._connections.pop("excel", None)

                # 2. GetActiveObject → 유효한 인스턴스만 사용
                try:
                    xl = win32com.client.GetActiveObject("Excel.Application")
                    if xl.Workbooks.Count == 0 and not xl.Visible:
                        logger.info("Excel: GetActiveObject 유령, 정리")
                        try:
                            xl.Quit()
                        except Exception:
                            pass
                        xl = None
                    else:
                        logger.info(f"Excel: GetActiveObject 성공 (workbooks={xl.Workbooks.Count})")
                except Exception:
                    xl = None

                # 3. subprocess로 실행 후 GetActiveObject
                if xl is None:
                    import subprocess, time
                    try:
                        subprocess.Popen(["start", "excel"], shell=True)
                        for _ in range(10):
                            time.sleep(0.5)
                            try:
                                xl = win32com.client.GetActiveObject("Excel.Application")
                                logger.info("Excel: subprocess+GetActiveObject 성공")
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if xl is None:
                        try:
                            xl = win32com.client.Dispatch("Excel.Application")
                        except Exception as e2:
                            return ActionResult(False, f"Excel 연결 실패: {e2}")

                xl.Visible = True
                if xl.Workbooks.Count == 0:
                    xl.Workbooks.Add()
                self._connections["excel"] = xl
                doc = ""
                try:
                    doc = xl.ActiveWorkbook.Name
                except Exception:
                    pass
                return ActionResult(True, f"Excel 연결 성공: {doc}")

            elif app_type == "ppt":
                existing = self._connections.get("ppt")
                if existing:
                    try:
                        cnt = existing.Presentations.Count
                        if cnt > 0 and existing.Visible:
                            doc = existing.ActivePresentation.Name
                            return ActionResult(True, f"PowerPoint 연결 성공: {doc}")
                        else:
                            try:
                                existing.Quit()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._connections.pop("ppt", None)

                ppt = None
                try:
                    ppt = win32com.client.GetActiveObject("PowerPoint.Application")
                    if ppt.Presentations.Count == 0 and not ppt.Visible:
                        try:
                            ppt.Quit()
                        except Exception:
                            pass
                        ppt = None
                    else:
                        logger.info(f"PPT: GetActiveObject 성공 (presentations={ppt.Presentations.Count})")
                except Exception:
                    ppt = None

                if ppt is None:
                    import subprocess, time
                    try:
                        subprocess.Popen(["start", "powerpnt"], shell=True)
                        for _ in range(10):
                            time.sleep(0.5)
                            try:
                                ppt = win32com.client.GetActiveObject("PowerPoint.Application")
                                logger.info("PPT: subprocess+GetActiveObject 성공")
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if ppt is None:
                        try:
                            ppt = win32com.client.Dispatch("PowerPoint.Application")
                        except Exception as e2:
                            return ActionResult(False, f"PowerPoint 연결 실패: {e2}")

                ppt.Visible = True
                if ppt.Presentations.Count == 0:
                    ppt.Presentations.Add()
                self._connections["ppt"] = ppt
                doc = ""
                try:
                    doc = ppt.ActivePresentation.Name
                except Exception:
                    pass
                return ActionResult(True, f"PowerPoint 연결 성공: {doc}")

            elif app_type == "word":
                existing = self._connections.get("word")
                if existing:
                    try:
                        cnt = existing.Documents.Count
                        if cnt > 0 and existing.Visible:
                            doc = existing.ActiveDocument.Name
                            return ActionResult(True, f"Word 연결 성공: {doc}")
                        # 유령: Visible=False 또는 문서 0개
                        if not existing.Visible and cnt == 0:
                            try:
                                existing.Quit()
                            except Exception:
                                pass
                    except Exception:
                        pass  # RPC 오류 = 이미 죽은 프로세스
                    self._connections.pop("word", None)

                word = None
                try:
                    word = win32com.client.GetActiveObject("Word.Application")
                    if word.Documents.Count == 0 and not word.Visible:
                        try:
                            word.Quit()
                        except Exception:
                            pass
                        word = None
                    else:
                        logger.info(f"Word: GetActiveObject 성공 (documents={word.Documents.Count})")
                except Exception:
                    word = None

                if word is None:
                    # subprocess로 실행 후 GetActiveObject (COM 참조 독립)
                    import subprocess, time
                    try:
                        subprocess.Popen(["start", "winword"], shell=True)
                        for _ in range(10):
                            time.sleep(0.5)
                            try:
                                word = win32com.client.GetActiveObject("Word.Application")
                                logger.info("Word: subprocess+GetActiveObject 성공")
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if word is None:
                        try:
                            word = win32com.client.Dispatch("Word.Application")
                        except Exception as e2:
                            return ActionResult(False, f"Word 연결 실패: {e2}")

                word.Visible = True
                if word.Documents.Count == 0:
                    word.Documents.Add()
                self._connections["word"] = word
                doc = ""
                try:
                    doc = word.ActiveDocument.Name
                except Exception:
                    pass
                return ActionResult(True, f"Word 연결 성공: {doc}")

            return ActionResult(False, f"알 수 없는 앱: {app_type}")
        except Exception as e:
            return ActionResult(False, f"연결 실패: {e}")

    # ── 문서 목록 ──

    def list_documents(self, app_type: str) -> list[dict]:
        """연결된 앱의 열린 문서 목록 반환."""
        self._ensure_com_init()
        obj = self._connections.get(app_type)
        if not obj:
            return []

        try:
            if app_type == "excel":
                docs = []
                for i in range(1, obj.Workbooks.Count + 1):
                    wb = obj.Workbooks(i)
                    docs.append({"index": i, "title": wb.Name, "path": wb.FullName or ""})
                return docs
            elif app_type == "ppt":
                docs = []
                for i in range(1, obj.Presentations.Count + 1):
                    p = obj.Presentations(i)
                    docs.append({"index": i, "title": p.Name, "path": p.FullName or ""})
                return docs
            elif app_type == "word":
                docs = []
                for i in range(1, obj.Documents.Count + 1):
                    d = obj.Documents(i)
                    docs.append({"index": i, "title": d.Name, "path": d.FullName or ""})
                return docs
        except Exception as e:
            logger.warning(f"{app_type} 문서 목록 오류: {e}")
            # RPC 오류 등 → 죽은 연결 정리
            self._connections.pop(app_type, None)
        return []

    def activate_document(self, app_type: str, index: int) -> ActionResult:
        """열린 문서 중 index번째를 활성화."""
        self._ensure_com_init()
        obj = self._connections.get(app_type)
        if not obj:
            return ActionResult(False, f"[{app_type}] 연결 안 됨")

        try:
            if app_type == "excel":
                wb = obj.Workbooks(index)
                wb.Activate()
                return ActionResult(True, f"활성 문서: {wb.Name}")
            elif app_type == "ppt":
                pres = obj.Presentations(index)
                pres.Windows(1).Activate()
                return ActionResult(True, f"활성 문서: {pres.Name}")
            elif app_type == "word":
                doc = obj.Documents(index)
                doc.Activate()
                return ActionResult(True, f"활성 문서: {doc.Name}")
        except Exception as e:
            return ActionResult(False, f"문서 전환 실패: {e}")
        return ActionResult(False, f"알 수 없는 앱: {app_type}")

    # ── 읽기 ──

    def read(self, app_type: str) -> str:
        """현재 열린 문서 내용을 텍스트로 반환."""
        obj = self._connections.get(app_type)
        if not obj:
            return f"[{app_type}] 연결 안 됨"

        self._ensure_com_init()
        try:
            return self._read_dispatch(app_type, obj)
        except Exception as e:
            return f"[{app_type} 읽기 오류] {e}"

    def _read_dispatch(self, app_type: str, obj) -> str:

        if app_type == "hwp":
            return self._read_hwp(obj)
        elif app_type == "excel":
            return self._read_excel(obj)
        elif app_type == "ppt":
            return self._read_ppt(obj)
        elif app_type == "word":
            return self._read_word(obj)
        return ""

    def _read_hwp(self, _obj) -> str:
        """한/글 문서 전체 텍스트 — HwpController 위임."""
        hwp_ctrl = _get_hwp_ctrl()
        return hwp_ctrl.read_text()

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

    # ── 실행 ──

    def execute(self, app_type: str, action: str, params: dict) -> ActionResult:
        """앱에 명령 실행."""
        self._ensure_com_init()
        obj = self._connections.get(app_type)
        if not obj:
            # 자동 재연결 시도
            result = self.connect(app_type)
            if not result.success:
                return ActionResult(False, f"[{app_type}] 연결 안 됨")
            obj = self._connections.get(app_type)
            if not obj:
                return ActionResult(False, f"[{app_type}] 연결 안 됨")
        try:
            if app_type == "hwp":
                return self._exec_hwp(obj, action, params)
            elif app_type == "excel":
                return self._exec_excel(obj, action, params)
            elif app_type == "ppt":
                return self._exec_ppt(obj, action, params)
            elif app_type == "word":
                return self._exec_word(obj, action, params)
            return ActionResult(False, f"알 수 없는 앱: {app_type}")
        except Exception as e:
            logger.error(f"라이브 실행 오류: {app_type}/{action} — {e}")
            return ActionResult(False, str(e))

    # ── HWP 명령 ──

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

    # ── Excel 명령 ──

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

    # ── PowerPoint 명령 ──

    @staticmethod
    def _ensure_ppt_slides(pres, n: int):
        """슬라이드가 n개 이상이 되도록 빈 슬라이드 자동 생성."""
        while pres.Slides.Count < n:
            pres.Slides.Add(pres.Slides.Count + 1, 2)  # 2 = ppLayoutText (제목+내용)

    @staticmethod
    def reorder_ppt_actions(actions: list[dict]) -> list[dict]:
        """PPT 액션 리스트에서 add_slide를 먼저 실행하도록 정렬."""
        return sorted(actions, key=lambda a: 0 if a.get("action") == "add_slide" else 1)

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

    # ── Word 명령 ──

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


# ── 유틸 ─────────────────────────────────────────────

def _col_letter(col_num: int) -> str:
    """1 → A, 2 → B, ..., 27 → AA"""
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ── 사용 가능한 액션 목록 (LLM 프롬프트용) ──────────

ACTIONS_SCHEMA = {
    "hwp": {
        # blockId 기반 정밀 편집 (CVD 스캔 후 사용)
        "replace_cell_content": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "표 셀 내용 교체"},
        "delete_cell_content": {"params": {"block_id": "블록ID"}, "desc": "표 셀 내용 삭제"},
        "replace_paragraph": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "문단 내용 교체"},
        "append_paragraph": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "문단 뒤에 새 문단 추가"},
        "replace_table_row": {"params": {"block_id": "블록ID", "row_texts": ["셀1", "셀2"]}, "desc": "표 행 전체 교체"},
        "append_table_row": {"params": {"block_id": "블록ID", "row_texts": ["셀1", "셀2"]}, "desc": "표에 행 추가"},
        "apply_para_style": {"params": {"block_id": "블록ID", "font_size": "크기", "font_family": "글꼴", "align": "정렬"}, "desc": "문단 서식 적용"},
        # 범용 편집
        "insert_text": {"params": {"text": "텍스트"}, "desc": "커서 위치에 텍스트 삽입"},
        "find_and_replace_all": {"params": {"old_text": "찾을 텍스트", "new_text": "바꿀 텍스트"}, "desc": "전체 찾아 바꾸기"},
        "set_field": {"params": {"field_name": "누름틀 이름", "value": "값"}, "desc": "누름틀 필드에 값 설정"},
        "create_table": {"params": {"rows": "행 수", "cols": "열 수"}, "desc": "표 생성"},
        "move_to_start": {"params": {}, "desc": "문서 처음으로 이동"},
        "move_to_end": {"params": {}, "desc": "문서 끝으로 이동"},
        "save": {"params": {}, "desc": "저장"},
        "save_as": {"params": {"path": "경로", "format": "HWP|HWPX|PDF"}, "desc": "다른 이름으로 저장"},
    },
    "excel": {
        "set_cell": {"params": {"cell": "셀 참조 (A1 또는 시트!A1)", "value": "값"}, "desc": "셀 값 설정"},
        "set_cells": {"params": {"cells": "{셀참조: 값, ...}"}, "desc": "여러 셀 한번에 설정"},
        "get_cell": {"params": {"cell": "셀 참조"}, "desc": "셀 값 읽기"},
        "get_range": {"params": {"range": "범위 (A1:C10)"}, "desc": "범위 읽기"},
        "active_sheet": {"params": {"sheet": "시트 이름"}, "desc": "시트 전환"},
        "add_sheet": {"params": {"name": "시트 이름"}, "desc": "시트 추가"},
        "insert_row": {"params": {"row": "행 번호"}, "desc": "행 삽입"},
        "delete_row": {"params": {"row": "행 번호"}, "desc": "행 삭제"},
        "auto_fit": {"params": {}, "desc": "열 너비 자동 조정"},
        "save": {"params": {}, "desc": "저장"},
    },
    "ppt": {
        "set_text": {"params": {"slide": "슬라이드 번호", "shape": "도형 인덱스(0=제목,1=본문)", "text": "텍스트"}, "desc": "텍스트 수정"},
        "add_slide": {"params": {"title": "제목", "content": "내용", "layout": "레이아웃(2=제목+내용)"}, "desc": "슬라이드 추가"},
        "set_note": {"params": {"slide": "슬라이드 번호", "text": "노트 내용"}, "desc": "발표자 노트 수정"},
        "delete_slide": {"params": {"slide": "슬라이드 번호"}, "desc": "슬라이드 삭제"},
        "set_table_cell": {"params": {"slide": "슬라이드 번호", "row": "행", "col": "열", "text": "텍스트"}, "desc": "표 셀 수정"},
        "save": {"params": {}, "desc": "저장"},
    },
    "word": {
        "insert_text": {"params": {"text": "텍스트"}, "desc": "커서 위치에 텍스트 삽입"},
        "replace_text": {"params": {"find": "찾을 텍스트", "replace": "바꿀 텍스트"}, "desc": "전체 찾아 바꾸기"},
        "set_paragraph": {"params": {"paragraph": "문단 번호", "text": "새 텍스트"}, "desc": "문단 내용 교체"},
        "append_paragraph": {"params": {"text": "텍스트"}, "desc": "문서 끝에 문단 추가"},
        "format_paragraph": {"params": {"paragraph": "문단 번호", "font_size": "크기", "font_name": "글꼴", "bold": "볼드", "align": "정렬"}, "desc": "문단 서식 변경"},
        "set_table_cell": {"params": {"table": "표 번호", "row": "행", "col": "열", "text": "텍스트"}, "desc": "표 셀 수정"},
        "save": {"params": {}, "desc": "저장"},
        "save_as": {"params": {"path": "경로"}, "desc": "다른 이름으로 저장"},
    },
}
