"""
폰트 패밀리 별칭 정규화 모듈.

HWP/Excel 등 문서에서 동일 폰트가 다양한 이름으로 기록되는 문제를 해결.
예: "MalgunGothic", "Malgun Gothic", "맑은 고딕", "맑은고딕" → "맑은 고딕"

참조: Inline AI v0.3.1 font_family_aliases.py (63 식별자, Nuitka 바이너리 추출)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


# ── 폰트 별칭 그룹 ─────────────────────────────────────
# 각 그룹의 첫 번째 항목이 정규화 대표명(canonical name)

FONT_FAMILY_ALIAS_GROUPS: List[List[str]] = [

    # --- 한글 기본 시스템 폰트 ---

    ["맑은 고딕", "맑은고딕", "Malgun Gothic", "MalgunGothic"],

    ["바탕", "바탕체", "Batang", "BatangChe",
     "Hancom Batang", "Hansoft Batang", "한컴바탕", "HancomBatang"],

    ["굴림", "굴림체", "Gulim", "GulimChe"],

    ["돋움", "돋움체", "Dotum", "DotumChe",
     "Hancom Dotum", "Hansoft Dotum", "Hancom Gothic", "한컴돋움"],

    ["궁서", "궁서체", "Gungsuh", "GungsuhChe"],

    # --- 나눔 폰트 시리즈 ---

    ["나눔고딕", "NanumGothic", "NanumGothicBold", "NanumGothic Bold"],
    ["나눔명조", "NanumMyeongjo"],
    ["나눔바른고딕", "NanumBarunGothic", "NanumBarunGothicOTF",
     "NanumBarunGothic OTF"],

    # --- 한컴/함초롬 폰트 ---

    ["함초롬바탕", "HCR Batang"],
    ["함초롬돋움", "HCR Dotum"],

    # --- HY 폰트 시리즈 (한양 시스템) ---

    ["HY헤드라인M", "HYHeadLineM", "HYHeadLine-Medium", "han YHead B"],
    ["HY고딕", "HYGothicMedium", "HYgtrE", "han YGodic 230"],
    ["HY신명조", "HYSMyeongJoMedium", "HYSinMyeongJoMedium",
     "HYShinMyeongJoMedium"],
    ["HY울림M", "HYwulM"],
    ["HY해서", "HYhaeseo"],

    # --- 영문 폰트 ---

    ["Arial", "Helvetica"],
    ["Times New Roman", "TimesNewRoman", "Times"],
    ["Courier New", "CourierNew", "Courier"],
]


# ── 정규화 맵 구축 ─────────────────────────────────────

FONT_FAMILY_CANONICAL_MAP: Dict[str, str] = {}


def font_alias_key(name: str) -> str:
    """폰트 이름 → 정규화 조회 키.

    1. strip  2. casefold  3. 공백·하이픈·언더스코어 제거
    """
    if not name:
        return ""
    return re.sub(r'[\s\-_]+', '', name.strip().casefold())


def _build_canonical_map() -> None:
    """FONT_FAMILY_ALIAS_GROUPS → FONT_FAMILY_CANONICAL_MAP 구축."""
    FONT_FAMILY_CANONICAL_MAP.clear()
    for group in FONT_FAMILY_ALIAS_GROUPS:
        if not group:
            continue
        canonical = group[0]
        for alias in group:
            key = font_alias_key(alias)
            if key:
                FONT_FAMILY_CANONICAL_MAP[key] = canonical


_build_canonical_map()


# ── 공개 API ───────────────────────────────────────────

def canonicalize_font_family_name(name: str) -> str:
    """폰트 패밀리 이름을 정규화된 대표명으로 변환.

    매핑에 없으면 원본 이름 그대로 반환.
    """
    if not name:
        return name
    return FONT_FAMILY_CANONICAL_MAP.get(font_alias_key(name), name)


def register_alias_group(group: List[str]) -> None:
    """런타임에 폰트 별칭 그룹을 추가 등록.

    확장성: 사용자 커스텀 폰트 매핑 지원.
    """
    if not group or len(group) < 2:
        return
    FONT_FAMILY_ALIAS_GROUPS.append(group)
    canonical = group[0]
    for alias in group:
        key = font_alias_key(alias)
        if key:
            FONT_FAMILY_CANONICAL_MAP[key] = canonical


def is_same_font(name1: str, name2: str) -> bool:
    """두 폰트 이름이 동일 폰트인지 판별."""
    if not name1 or not name2:
        return False
    return canonicalize_font_family_name(name1) == canonicalize_font_family_name(name2)
