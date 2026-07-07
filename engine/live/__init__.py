"""라이브 문서 제어 패키지.

실행 중인 한/글·Excel·PowerPoint·Word에 COM으로 연결해 문서를 읽고 쓴다.
앱별 로직은 각 모듈(hwp/excel/ppt/word)의 mixin으로 분리, LiveController가 조립.

외부에서는 기존처럼 `from engine.live_controller import LiveController, _get_hwp_ctrl,
ACTIONS_SCHEMA` 로 접근한다(facade). 신규 코드는 이 패키지를 직접 import 해도 된다.
"""

from .base import AppInfo, ActionResult, _get_hwp_ctrl, _col_letter
from .controller import LiveController
from .schemas import ACTIONS_SCHEMA

__all__ = [
    "LiveController", "AppInfo", "ActionResult",
    "_get_hwp_ctrl", "_col_letter", "ACTIONS_SCHEMA",
]
