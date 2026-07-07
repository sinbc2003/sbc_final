"""라이브 컨트롤러 공통 요소 — 데이터클래스, HWP 싱글턴, 유틸.

앱별 mixin과 컨트롤러가 공유하는 최소 기반. COM 스레드 직렬화는
server.py의 _com_pool(단일 워커 ThreadPoolExecutor)이 담당하므로,
여기의 함수/메서드는 항상 그 스레드에서 호출된다고 가정한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("engine.live")

# HWP 전용 컨트롤러 (pyhwpx 기반) — 프로세스 전역 싱글턴.
# 모든 앱 mixin/컨트롤러가 이 함수를 통해 같은 인스턴스를 공유한다.
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
    app_type: str           # "hwp" | "excel" | "ppt" | "word"
    name: str               # 표시 이름
    connected: bool = False
    doc_name: str = ""      # 현재 열린 문서 이름
    doc_path: str = ""      # 문서 경로


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    data: Any = None


# ── 유틸 ─────────────────────────────────────────────

def _col_letter(col_num: int) -> str:
    """1 → A, 2 → B, ..., 27 → AA"""
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result
