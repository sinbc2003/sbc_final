"""
COM 호출 재시도 라이브러리.

HWP/Excel COM 자동화에서 발생하는 일시적 RPC 에러를 자동 재시도.
5종 HRESULT 코드 + 8종 에러 메시지 패턴 기반 판별.

참조: Inline AI v0.3.1 hwp_com_retry_lib.py (68 식별자, Nuitka 바이너리 추출)
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, Set

logger = logging.getLogger(__name__)


# ── 재시도 대상 HRESULT ─────────────────────────────────

COM_RETRY_HRESULTS: Set[int] = {
    -2147418111,  # RPC_E_CALL_REJECTED       (0x80010001)
    -2147417848,  # RPC_E_SERVERFAULT         (0x80010105)
    -2147023174,  # RPC_S_SERVER_UNAVAILABLE  (0x800706BA)
    -2147023170,  # RPC_S_CALL_FAILED         (0x800706BE)
    -2146959355,  # CO_E_SERVER_EXEC_FAILURE  (0x80080005)
}

# ── 재시도 대상 에러 메시지 패턴 ────────────────────────

COM_RETRY_MESSAGES = [
    'Call was rejected by callee',
    'Server execution failed',
    'RPC server is unavailable',
    'The remote procedure call failed',
    'The object invoked has disconnected',
    'System call failed',
    'Server busy',
    'Application is busy',
]


# ── 판별 함수 ──────────────────────────────────────────

def is_transient_com_error(err: Exception) -> bool:
    """일시적 COM 에러인지 판별.

    pywintypes.com_error의 hresult 속성 또는 args[0] 체크,
    실패 시 에러 메시지 패턴 매칭.
    """
    # hresult 속성 체크
    hresult = getattr(err, 'hresult', None)
    if hresult is not None and hresult in COM_RETRY_HRESULTS:
        return True

    # args[0]에서 HRESULT 추출
    if hasattr(err, 'args') and err.args:
        arg0 = err.args[0]
        if isinstance(arg0, int) and arg0 in COM_RETRY_HRESULTS:
            return True

    # 메시지 기반 매칭
    msg = str(err).lower()
    return any(m.lower() in msg for m in COM_RETRY_MESSAGES)


def sleep_backoff(attempt: int, base: float = 0.5, max_sleep: float = 5.0):
    """지수 백오프 슬립."""
    delay = min(base * (2 ** attempt), max_sleep)
    time.sleep(delay)


# ── 데코레이터 ─────────────────────────────────────────

def com_retry(tries: int = 3,
              cleanup_func: Optional[Callable] = None,
              init_func: Optional[Callable] = None):
    """COM 호출 재시도 데코레이터.

    Args:
        tries: 최대 시도 횟수 (기본 3)
        cleanup_func: 재시도 전 정리 함수 (옵션)
        init_func: 재시도 전 재초기화 함수 (옵션, 새 COM 인스턴스 반환 가능)

    Usage::

        @com_retry(tries=3)
        def some_com_operation(hwp, ...):
            hwp.SomeMethod()
    """
    def _wrap(func: Callable) -> Callable:
        @functools.wraps(func)
        def _inner(*args, **kwargs):
            last_err = None
            _args = args

            for attempt in range(tries):
                try:
                    return func(*_args, **kwargs)
                except Exception as err:
                    last_err = err

                    if not is_transient_com_error(err):
                        raise

                    logger.warning(
                        f"COM retry {attempt + 1}/{tries} for "
                        f"{func.__name__}: {err}"
                    )

                    sleep_backoff(attempt)

                    if cleanup_func:
                        try:
                            cleanup_func()
                        except Exception:
                            pass

                    if init_func:
                        try:
                            new_instance = init_func()
                            if new_instance and _args:
                                _args = (new_instance,) + _args[1:]
                        except Exception:
                            pass

            if last_err:
                raise last_err

        return _inner
    return _wrap


def com_retry_simple(tries: int = 3):
    """간단한 COM 재시도 데코레이터 (cleanup/init 없음).

    확장성: 가장 흔한 사용 패턴을 간결하게 지원.
    """
    return com_retry(tries=tries)
