"""LiveController — 실행 중인 오피스 앱 감지·연결·디스패치.

앱별 읽기/실행 로직은 각 mixin(HwpMixin/ExcelMixin/PptMixin/WordMixin)에 있고,
이 클래스는 감지(detect)·연결(connect)·문서목록·디스패치(read/execute)만 담당한다.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

from .base import AppInfo, ActionResult, _get_hwp_ctrl
from .excel import ExcelMixin
from .hwp import HwpMixin
from .ppt import PptMixin
from .word import WordMixin

logger = logging.getLogger(__name__)


class LiveController(HwpMixin, ExcelMixin, PptMixin, WordMixin):
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

    # ── 읽기 (앱별 mixin으로 디스패치) ──

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

    # ── 실행 (앱별 mixin으로 디스패치) ──

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
