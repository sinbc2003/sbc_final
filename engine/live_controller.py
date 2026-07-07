"""라이브 문서 제어 — engine.live 패키지의 facade(재노출).

실제 구현은 engine/live/ 아래로 모듈화되었다:
    live/base.py        공통 데이터클래스·HWP 싱글턴·유틸
    live/controller.py  LiveController (감지/연결/디스패치)
    live/{hwp,excel,ppt,word}.py  앱별 읽기/실행 mixin
    live/schemas.py     ACTIONS_SCHEMA

기존 코드는 이전과 동일하게
    from engine.live_controller import LiveController, _get_hwp_ctrl, ACTIONS_SCHEMA
로 사용할 수 있도록 이 파일이 재노출한다.

사용법:
    ctrl = LiveController()
    apps = ctrl.detect()          # {"hwp": True, "excel": True, "ppt": False}
    content = ctrl.read("hwp")    # 현재 문서 내용
    ctrl.execute("hwp", "insert_text", {"text": "안녕하세요"})
"""

from engine.live.base import AppInfo, ActionResult, _get_hwp_ctrl, _col_letter
from engine.live.controller import LiveController
from engine.live.schemas import ACTIONS_SCHEMA

__all__ = [
    "LiveController", "AppInfo", "ActionResult",
    "_get_hwp_ctrl", "_col_letter", "ACTIONS_SCHEMA",
]
