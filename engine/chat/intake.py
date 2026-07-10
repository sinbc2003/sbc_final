"""입력 분석 — 양식 의도 감지, 파일 경로/지시문 추출."""

from __future__ import annotations

import json
import logging
import re
import math
from pathlib import Path
from typing import Any

_log = logging.getLogger("chat_handler")


FORM_EXTENSIONS = {".xlsx", ".xls", ".hwpx", ".hwp"}



_FORM_INTENT_KEYWORDS = [
    "채워", "채워줘", "채우기", "작성", "작성해", "입력", "넣어",
    "빈칸", "양식", "공문", "서식", "기입", "기재",
    "수정", "바꿔", "변경", "고쳐", "편집",
    "완성", "마무리",
]



def detect_form_intent(message: str, file_paths: list[str]) -> bool:
    """첨부 파일 확장자 + 메시지 키워드로 FormAssist 라우팅 여부 판단.

    조건: (1) 양식 확장자 파일이 1개 이상 AND (2) 메시지에 수정/채우기 의도 키워드
    """
    if not file_paths:
        return False

    has_form_file = any(
        Path(p).suffix.lower() in FORM_EXTENSIONS for p in file_paths
    )
    if not has_form_file:
        return False

    msg_lower = message.lower()
    has_intent = any(kw in msg_lower for kw in _FORM_INTENT_KEYWORDS)

    if has_intent:
        _log.info(f"FormAssist 의도 감지: 양식 파일 있음 + 키워드 매칭")
        return True

    # 파일만 있고 텍스트가 짧으면 (파일 드롭 후 간단한 지시) → FormAssist로
    text_only = re.sub(r"첨부된 파일 경로:.*", "", message, flags=re.DOTALL).strip()
    if has_form_file and len(text_only) < 50:
        _log.info(f"FormAssist 의도 감지: 양식 파일 + 짧은 메시지({len(text_only)}자)")
        return True

    return False



# 라이브 채우기 전용 신호 — 일반 편집(바꿔/만들어/삭제 등)은 액션 경로가 담당하므로
# '빈칸을 채운다'는 명시적 표현만 잡는다 (오라우팅 시 fill 실패 → 액션 경로 폴백).
_LIVE_FILL_KEYWORDS = ["채워", "채우", "빈칸", "기입해"]


def detect_live_fill_intent(message: str) -> bool:
    """라이브 채팅 메시지가 '열린 문서의 빈칸 채우기' 의도인지 판단.

    True면 그리드 fill-live 경로(gemma 배치→캐럿 라이브 기록)로 라우팅.
    감지 실패/채움 실패 시 호출 측이 기존 액션 경로로 폴백한다.
    """
    msg = (message or "").lower()
    hit = any(kw in msg for kw in _LIVE_FILL_KEYWORDS)
    if hit:
        _log.info("라이브 채우기 의도 감지 → fill-live 라우팅")
    return hit


def extract_file_paths(message: str) -> list[str]:
    """채팅 메시지에서 '첨부된 파일 경로:' 블록의 파일 경로 추출."""
    paths = []
    match = re.search(r"첨부된 파일 경로:\s*\n(.*)", message, re.DOTALL)
    if match:
        for line in match.group(1).strip().split("\n"):
            p = line.strip()
            if p and Path(p).suffix:
                paths.append(p)
    return paths



def extract_user_instruction(message: str) -> str:
    """메시지에서 파일 경로 블록을 제거하고 사용자 지시만 반환."""
    return re.sub(r"\n*첨부된 파일 경로:.*", "", message, flags=re.DOTALL).strip()
