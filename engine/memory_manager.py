"""
메모리 관리자 — 시스템 RAM 모니터링, 모델 로드/언로드 결정.

8GB  → Q3 (1.2GB) + ctx 2048
12GB → Q4 (1.5GB) + ctx 4096
16GB → Q6 (1.8GB) + ctx 8192
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

import psutil


@dataclass
class MemoryProfile:
    """시스템 메모리 프로필."""

    total_gb: float
    available_gb: float
    recommended_quant: str  # Q3, Q4, Q6
    recommended_ctx: int    # 컨텍스트 길이
    model_budget_mb: int    # 모델에 할당 가능한 MB


def get_memory_profile() -> MemoryProfile:
    """현재 시스템 메모리 상태를 분석하여 프로필 반환."""
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    available_gb = mem.available / (1024 ** 3)

    if total_gb >= 16:
        quant, ctx, budget = "Q6", 8192, 1800
    elif total_gb >= 12:
        quant, ctx, budget = "Q4", 4096, 1500
    else:
        quant, ctx, budget = "Q3", 2048, 1200

    return MemoryProfile(
        total_gb=round(total_gb, 1),
        available_gb=round(available_gb, 1),
        recommended_quant=quant,
        recommended_ctx=ctx,
        model_budget_mb=budget,
    )


def check_available_memory(required_mb: int) -> bool:
    """필요한 메모리(MB)가 현재 사용 가능한지 확인."""
    available_mb = psutil.virtual_memory().available / (1024 ** 2)
    # 500MB는 시스템 여유분으로 확보
    return available_mb - 500 >= required_mb


def get_system_info() -> dict:
    """디버그용 시스템 정보."""
    mem = psutil.virtual_memory()
    return {
        "platform": platform.system(),
        "python": platform.python_version(),
        "total_ram_gb": round(mem.total / (1024 ** 3), 1),
        "available_ram_gb": round(mem.available / (1024 ** 3), 1),
        "cpu_count": psutil.cpu_count(),
    }
