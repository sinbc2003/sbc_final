"""HWP 실시간 제어 — engine.hwp 패키지의 facade(재노출).

Inline AI 역공학 기반 HWP COM 제어. 1768줄 단일 파일을 engine/hwp/ 로 모듈화:
    hwp/models.py      Block, DocumentInfo
    hwp/blocks.py      BlockManager (blockId↔위치 매핑)
    hwp/scanner.py     DocumentScanner (스캔→CVD)
    hwp/editor.py      HwpEditor (blockId 기반 편집)
    hwp/controller.py  HwpController (연결/폴링/오케스트레이션)
    hwp/schemas.py     HWP_ACTIONS_SCHEMA

기존 `from engine.hwp_controller import HwpController, DocumentScanner,
BlockManager, HwpEditor, HWP_ACTIONS_SCHEMA` 를 그대로 유지하기 위한 재노출.
"""

from engine.hwp.models import Block, DocumentInfo
from engine.hwp.blocks import BlockManager
from engine.hwp.scanner import DocumentScanner
from engine.hwp.editor import HwpEditor
from engine.hwp.controller import HwpController
from engine.hwp.schemas import HWP_ACTIONS_SCHEMA

__all__ = ["Block", "DocumentInfo", "BlockManager", "DocumentScanner",
           "HwpEditor", "HwpController", "HWP_ACTIONS_SCHEMA"]
