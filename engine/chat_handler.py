"""채팅 기반 워크플로우 자동 생성 + 라이브 문서 제어 — engine.chat 패키지 facade.

770줄 단일 파일을 engine/chat/ 로 모듈화(관심사 3분리):
    chat/intake.py     양식 의도 감지·파일/지시문 추출
    chat/workflow.py   handle_chat(워크플로우 생성) + 양식 assist
    chat/live_chat.py  handle_live_chat(라이브 COM 제어)·CVD 읽기·액션 파싱

기존 import를 그대로 유지하기 위한 재노출.
"""

from engine.chat.intake import (
    FORM_EXTENSIONS, detect_form_intent, detect_live_fill_intent, extract_file_paths, extract_user_instruction,
)
from engine.chat.workflow import (
    build_system_prompt, parse_workflow_response, handle_chat,
)
from engine.chat.live_chat import (
    parse_actions_response, prepare_live_chat_messages, handle_live_chat, _read_with_cvd,
)

__all__ = [
    "FORM_EXTENSIONS", "detect_form_intent", "detect_live_fill_intent", "extract_file_paths", "extract_user_instruction",
    "build_system_prompt", "parse_workflow_response", "handle_chat",
    "parse_actions_response", "prepare_live_chat_messages", "handle_live_chat", "_read_with_cvd",
]
