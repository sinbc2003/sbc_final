"""HwpController — COM 연결/해제, 문서 상태 폴링, 편집 오케스트레이션."""

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
from engine.hwp.blocks import BlockManager
from engine.hwp.scanner import DocumentScanner
from engine.hwp.editor import HwpEditor


class HwpController:
    """pyhwpx 기반 HWP 실시간 제어 컨트롤러.

    pyhwpx가 COM 초기화를 내부에서 처리하므로 별도 COM 스레드 불필요.
    threading.Lock으로 동시 접근만 방지.
    """

    def __init__(self):
        self._hwp = None              # pyhwpx.Hwp 인스턴스
        self._connected = False
        self._lock = threading.Lock()
        self._block_manager = BlockManager()
        self._editor: Optional[HwpEditor] = None
        self._scanner: Optional[DocumentScanner] = None
        self._doc_info: Optional[DocumentInfo] = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 연결 ──

    def connect(self, visible: bool = True) -> dict:
        """실행 중인 한/글에 연결. 없으면 새 인스턴스 생성."""
        with self._lock:
            try:
                # 기존 연결 살아있으면 재사용
                if self._hwp and self._connected:
                    try:
                        self._hwp.get_pos()
                        doc_name = ""
                        try:
                            doc_name = self._hwp.FileName or ""
                        except Exception:
                            pass
                        return {"success": True, "connected": True, "document": doc_name}
                    except Exception:
                        pass  # stale → 새로 생성

                import pythoncom
                pythoncom.CoInitialize()
                from pyhwpx import Hwp
                hwp = Hwp(visible=visible)

                self._hwp = hwp
                self._connected = True
                self._editor = HwpEditor(hwp, self._block_manager)
                self._scanner = DocumentScanner(hwp)

                doc_name = ""
                try:
                    doc_name = hwp.FileName or ""
                except Exception:
                    pass

                return {"success": True, "connected": True, "document": doc_name}
            except Exception as e:
                logger.error(f"pyhwpx 연결 실패: {e}")
                self._connected = False
                return {"success": False, "error": str(e)}

    def disconnect(self):
        """COM 연결 해제."""
        with self._lock:
            self._hwp = None
            self._connected = False
            self._editor = None
            self._scanner = None

    # ── 문서 상태 ──

    def get_document_info(self) -> dict:
        """현재 문서 실시간 정보 수집."""
        if not self._connected or not self._hwp:
            return {"error": "not connected"}

        with self._lock:
            try:
                hwp = self._hwp
                pos = hwp.get_pos()

                doc_path = ""
                doc_name = ""
                try:
                    doc_path = hwp.Path or ""
                    doc_name = hwp.FileName or ""
                except Exception:
                    pass

                current_page = 0
                total_pages = 0
                try:
                    current_page = hwp.current_page
                    total_pages = hwp.PageCount
                except Exception:
                    pass

                selected = ""
                try:
                    selected = hwp.get_selected_text(keep_select=True) or ""
                except Exception:
                    pass

                ctrl_type = None
                try:
                    if hwp.is_cell():
                        ctrl_type = "표"
                except Exception:
                    pass

                modified = False
                try:
                    modified = bool(hwp.IsModified)
                except Exception:
                    pass

                info = DocumentInfo(
                    document_path=doc_path,
                    document_name=doc_name,
                    caret_position=pos,
                    caret_page=current_page,
                    total_pages=total_pages,
                    selected_text=selected,
                    ctrl_type=ctrl_type,
                    document_mode="EDIT",
                    modified=modified,
                )
                self._doc_info = info
                return info.to_dict()
            except Exception as e:
                return {"error": str(e)}

    # ── CVD 추출 ──

    def _refresh_hwp(self):
        """COM 인스턴스를 갱신 (reload 이후 stale 방지).

        기존 연결이 살아있으면 재사용, 없거나 stale하면 새로 생성.
        일시적 COM 에러는 자동 재시도.
        """
        if self._hwp and self._connected:
            # 기존 인스턴스 동작 확인
            try:
                self._hwp.get_pos()
                # scanner/editor가 없으면 재생성
                if not self._scanner:
                    self._scanner = DocumentScanner(self._hwp)
                if not self._editor:
                    self._editor = HwpEditor(self._hwp, self._block_manager)
                return
            except Exception as e:
                # 일시적 COM 에러면 재시도 전에 잠깐 대기
                if _HWPML_AVAILABLE and is_transient_com_error(e):
                    import time
                    time.sleep(0.5)
                    try:
                        self._hwp.get_pos()
                        return
                    except Exception:
                        pass
                # stale → 새로 생성
        import pythoncom
        pythoncom.CoInitialize()
        from pyhwpx import Hwp
        hwp = Hwp(visible=True)
        self._hwp = hwp
        self._connected = True
        self._editor = HwpEditor(hwp, self._block_manager)
        self._scanner = DocumentScanner(hwp)

    def extract_cvd(
        self,
        page_range: Optional[Tuple[int, int]] = None,
        mode: str = "auto",
    ) -> dict:
        """문서 구조 추출 (Content View Document).

        Args:
            page_range: (min_page, max_page)
            mode: "auto" | "hwpml" | "cursor"
                auto — HWPML 우선, 실패 시 커서 폴백
                hwpml — HWPML2X 파싱만 사용
                cursor — 기존 커서 스캔만 사용

        Returns:
            {"cvd": str, "blocks": [...], "block_count": int, "scan_mode": str}
        """
        with self._lock:
            try:
                self._refresh_hwp()

                # HWPML 모드 시도
                if mode in ("auto", "hwpml") and _HWPML_AVAILABLE:
                    hwpml_result = self._scanner.scan_hwpml()
                    if hwpml_result:
                        blocks = hwpml_result["blocks"]
                        id_to_pos = hwpml_result["id_to_pos"]
                        style_lookup = hwpml_result["style_lookup"]

                        # BlockManager 초기화 (HWPML 모드)
                        self._block_manager.initialize_from_blocks(blocks, id_to_pos)

                        # td 좌표 캘리브레이션 — HWPML 가상 좌표를 InitScan
                        # 실좌표로 교체 (편집 set_pos 신뢰성, §5 gap 해소)
                        try:
                            raw = self._scanner.raw_scan()
                            self._block_manager.calibrate_with_scan(raw)
                        except Exception as e:
                            logger.warning(f"td 캘리브레이션 건너뜀: {e}")

                        # CVD 빌더로 고품질 CVD 생성
                        file_name = ""
                        try:
                            file_name = self._hwp.FileName or ""
                        except Exception:
                            pass

                        cvd_text = build_cvd(
                            blocks=blocks,
                            id_to_pos=id_to_pos,
                            style_lookup=style_lookup,
                            page_range=page_range,
                            file_name=file_name,
                        )
                        return {
                            "cvd": cvd_text,
                            "blocks": blocks,
                            "block_count": len(blocks),
                            "scan_mode": "hwpml",
                        }

                    if mode == "hwpml":
                        return {"error": "HWPML 스캔 실패", "scan_mode": "hwpml"}

                # 커서 모드 (폴백)
                elements = self._scanner.scan(page_range)
                self._block_manager.initialize_from_scan(elements)
                cvd_text = self._block_manager.to_cvd_text()
                return {
                    "cvd": cvd_text,
                    "blocks": elements,
                    "block_count": len(elements),
                    "scan_mode": "cursor",
                }
            except Exception as e:
                import traceback
                logger.error(f"extract_cvd 실패: {traceback.format_exc()}")
                return {"error": str(e), "traceback": traceback.format_exc()}

    # ── 읽기 ──

    def read_text(self) -> str:
        """문서 전체 텍스트 읽기 (페이지 설정 포함)."""
        with self._lock:
            try:
                self._refresh_hwp()
                hwp = self._hwp
                parts = []

                # 페이지 설정 정보
                try:
                    pd = hwp.get_pagedef_as_dict("eng")
                    pw = pd.get("PaperWidth", 210)
                    ph = pd.get("PaperHeight", 297)
                    lm = pd.get("LeftMargin", 30)
                    rm = pd.get("RightMargin", 30)
                    tm = pd.get("TopMargin", 25)
                    bm_ = pd.get("BottomMargin", 25)
                    gt = pd.get("GutterLen", 0)
                    uw = round(pw - lm - rm - gt, 1)
                    parts.append(
                        f"[용지] {pw}x{ph}mm, "
                        f"여백 좌{lm} 우{rm} 상{tm} 하{bm_}mm, "
                        f"가용폭 {uw}mm"
                    )
                except Exception:
                    parts.append("[용지] 정보 없음 (A4 가정: 가용폭 약150mm)")

                hwp.MoveDocBegin()
                hwp.init_scan(option=4, range=0x0077)

                for _ in range(10000):  # 안전 상한
                    state, text = hwp.get_text()
                    if state == 0:
                        break
                    if state == 1:
                        continue
                    if text and text.strip():
                        parts.append(text.strip())

                hwp.release_scan()

                # 누름틀 필드 정보
                try:
                    fields = hwp.get_field_list()
                    if fields:
                        parts.append("\n=== 누름틀 필드 ===")
                        for f in fields.split("\x02"):
                            if f:
                                val = hwp.get_field_text(f) or "(비어있음)"
                                parts.append(f"  [{f}] = {val}")
                except Exception:
                    pass

                return "\n".join(parts)
            except Exception as e:
                return f"[HWP 읽기 오류] {e}"

    # ── 편집 ──

    def execute(self, operation: str, **kwargs) -> dict:
        """편집 명령 실행.

        Args:
            operation: 명령 이름 (replace_cell_content, replace_paragraph, ...)
            **kwargs: 명령별 파라미터 (block_id, new_text, old_text, row_texts, ...)
        """
        if not self._connected or not self._editor:
            try:
                self._refresh_hwp()
            except Exception:
                return {"isSuccess": False, "message": "not connected"}

        with self._lock:
            try:
                editor = self._editor

                method_map = {
                    "replace_cell_content": lambda: editor.replace_cell_content(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "delete_cell_content": lambda: editor.delete_cell_content(
                        kwargs["block_id"]),
                    "replace_paragraph": lambda: editor.replace_paragraph(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "append_paragraph": lambda: editor.append_paragraph(
                        kwargs["block_id"], kwargs.get("new_text", "")),
                    "find_and_replace_all": lambda: editor.find_and_replace_all(
                        kwargs["old_text"], kwargs["new_text"]),
                    "insert_text": lambda: editor.insert_text_at_cursor(
                        kwargs["text"]),
                    "apply_para_style": lambda: editor.apply_para_style(
                        kwargs["block_id"],
                        font_size=kwargs.get("font_size"),
                        font_family=kwargs.get("font_family"),
                        align=kwargs.get("align"),
                        spacing=kwargs.get("spacing"),
                        indentation=kwargs.get("indentation")),
                    "create_table": lambda: editor.create_table(
                        int(kwargs.get("rows", 2)), int(kwargs.get("cols", 2)),
                        data=kwargs.get("data")),
                    "replace_table_row": lambda: editor.replace_table_row(
                        kwargs["block_id"], kwargs.get("row_texts")),
                    "append_table_row": lambda: editor.append_table_row(
                        kwargs["block_id"], kwargs.get("row_texts")),
                    "style_cell": lambda: editor.style_cell(
                        kwargs["block_id"],
                        bg_color=kwargs.get("bg_color"),
                        align=kwargs.get("align"),
                        bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"),
                        text_color=kwargs.get("text_color")),
                    "style_row": lambda: editor.style_row(
                        kwargs["block_id"],
                        bg_color=kwargs.get("bg_color"),
                        bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"),
                        text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "merge_cells": lambda: editor.merge_cells(
                        kwargs["block_id"],
                        right=int(kwargs.get("right", 0)),
                        down=int(kwargs.get("down", 0))),
                    "set_table_col_width": lambda: editor.set_table_col_width(
                        kwargs["block_id"], kwargs["widths"]),
                    "save": lambda: editor.save(),
                    "save_as": lambda: editor.save_as(
                        kwargs["path"], kwargs.get("format", "HWPX")),
                    # 인덱스 기반 (block_id 불필요)
                    "style_table_row_idx": lambda: editor.style_table_row_idx(
                        int(kwargs.get("table", 1)), int(kwargs.get("row", 0)),
                        bg_color=kwargs.get("bg_color"), bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"), text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "style_table_cell_idx": lambda: editor.style_table_cell_idx(
                        int(kwargs.get("table", 1)), int(kwargs.get("row", 0)), int(kwargs.get("col", 0)),
                        bg_color=kwargs.get("bg_color"), bold=kwargs.get("bold"),
                        font_size=kwargs.get("font_size"), text_color=kwargs.get("text_color"),
                        align=kwargs.get("align")),
                    "set_table_widths": lambda: editor.set_table_widths(
                        int(kwargs.get("table", 1)), kwargs.get("widths", [])),
                    "format_text": lambda: editor.format_text(
                        font_size=kwargs.get("font_size"), bold=kwargs.get("bold"),
                        align=kwargs.get("align"), text_color=kwargs.get("text_color"),
                        font_family=kwargs.get("font_family")),
                    "_raw_set_field": lambda: self._raw_set_field(
                        kwargs["field_name"], kwargs["value"]),
                    "_raw_move": lambda: self._raw_move(kwargs.get("direction", "start")),
                }

                handler = method_map.get(operation)
                if not handler:
                    return {"isSuccess": False, "message": f"알 수 없는 명령: {operation}"}

                return handler()
            except Exception as e:
                return {"isSuccess": False, "message": str(e)}

    # ── 레거시 raw 명령 (set_field, move) ──

    def _raw_set_field(self, field_name: str, value: str) -> dict:
        try:
            hwp = self._hwp
            hwp.PutFieldText(field_name, str(value))
            # 반영 확인 — PutFieldText는 누름틀 없으면 조용히 무시됨
            try:
                actual = hwp.GetFieldText(field_name)
                if actual is None or actual == "":
                    return {"isSuccess": False, "message": f"누름틀 '{field_name}' 없거나 반영 실패"}
            except Exception:
                pass  # GetFieldText 실패 시 확인 불가
            return {"isSuccess": True, "message": f"필드 '{field_name}' = {value}"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    def _raw_move(self, direction: str = "start") -> dict:
        try:
            if direction == "start":
                self._hwp.MoveDocBegin()
            else:
                self._hwp.MoveDocEnd()
            return {"isSuccess": True, "message": f"문서 {direction}으로 이동"}
        except Exception as e:
            return {"isSuccess": False, "message": str(e)}

    # ── 다중 문서 관리 ──

    def list_documents(self) -> list[dict]:
        """열려있는 모든 HWP 문서 목록 반환."""
        if not self._connected or not self._hwp:
            return []

        with self._lock:
            docs = []
            try:
                xdocs = self._hwp.XHwpDocuments
                count = xdocs.Count
                for i in range(count):
                    doc = xdocs.Item(i)
                    full_name = ""
                    title = ""
                    try:
                        full_name = doc.FullName or ""
                    except Exception:
                        pass
                    try:
                        title = doc.Title or ""
                    except Exception:
                        pass

                    # 표시명: 파일명 > Title > "새 문서 N"
                    if full_name:
                        import os
                        display = os.path.basename(full_name)
                    elif title:
                        display = title
                    else:
                        display = f"새 문서 {i + 1}"

                    docs.append({
                        "index": i,
                        "title": display,
                        "path": full_name,
                    })
            except Exception as e:
                logger.debug(f"XHwpDocuments 접근 실패, 단일 문서 fallback: {e}")
                name = ""
                path = ""
                try:
                    name = self._hwp.FileName or ""
                    path = self._hwp.Path or ""
                except Exception:
                    pass
                docs.append({
                    "index": 0,
                    "title": name or "현재 문서",
                    "path": path,
                })
            return docs

    def switch_document(self, doc_index: int) -> dict:
        """특정 문서로 전환 (0-based index)."""
        if not self._connected or not self._hwp:
            return {"success": False, "error": "not connected"}

        with self._lock:
            try:
                xdocs = self._hwp.XHwpDocuments
                count = xdocs.Count
                if doc_index < 0 or doc_index >= count:
                    return {"success": False, "error": f"인덱스 범위 초과 (0~{count-1})"}

                doc = xdocs.Item(doc_index)
                doc.SetActive_XHwpDocument()

                # 전환 후 스캐너/에디터 재초기화
                self._scanner = DocumentScanner(self._hwp)
                self._block_manager = BlockManager()
                self._editor = HwpEditor(self._hwp, self._block_manager)

                doc_name = ""
                try:
                    doc_name = self._hwp.FileName or ""
                except Exception:
                    pass

                return {"success": True, "document": doc_name}
            except Exception as e:
                logger.error(f"문서 전환 실패: {e}")
                return {"success": False, "error": str(e)}

    # ── 표 스캔 ──

    def scan_tables(self) -> dict:
        """문서의 모든 표 구조 추출."""
        if not self._connected or not self._scanner:
            return {"error": "not connected"}

        with self._lock:
            try:
                tables = self._scanner.scan_tables()
                return {"tables": tables, "count": len(tables)}
            except Exception as e:
                return {"error": str(e)}
