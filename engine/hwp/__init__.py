"""HWP COM 제어 패키지 (pyhwpx 기반).

Inline AI 역공학 기반 HWP 제어. models/blocks/scanner/editor/controller로 분리.
외부는 기존처럼 `from engine.hwp_controller import HwpController, DocumentScanner,
BlockManager, HwpEditor, HWP_ACTIONS_SCHEMA` 로 접근(facade).
"""

from engine.hwp.models import Block, DocumentInfo
from engine.hwp.blocks import BlockManager
from engine.hwp.scanner import DocumentScanner
from engine.hwp.editor import HwpEditor
from engine.hwp.controller import HwpController
from engine.hwp.schemas import HWP_ACTIONS_SCHEMA

__all__ = ["Block", "DocumentInfo", "BlockManager", "DocumentScanner",
           "HwpEditor", "HwpController", "HWP_ACTIONS_SCHEMA"]
