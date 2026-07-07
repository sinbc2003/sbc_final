"""채팅 처리 패키지 — intake(입력분석)/workflow(생성)/live_chat(문서제어).

외부는 기존처럼 `from engine.chat_handler import handle_chat, handle_live_chat, ...`
로 접근(facade).
"""

from engine.chat.intake import (
    FORM_EXTENSIONS, detect_form_intent, extract_file_paths, extract_user_instruction,
)
from engine.chat.workflow import (
    build_system_prompt, parse_workflow_response, handle_chat,
)
from engine.chat.live_chat import (
    parse_actions_response, prepare_live_chat_messages, handle_live_chat, _read_with_cvd,
)

__all__ = [
    "FORM_EXTENSIONS", "detect_form_intent", "extract_file_paths", "extract_user_instruction",
    "build_system_prompt", "parse_workflow_response", "handle_chat",
    "parse_actions_response", "prepare_live_chat_messages", "handle_live_chat", "_read_with_cvd",
]
