"""라이브 제어 액션 스키마 — LLM 프롬프트/도구 노출용.

앱별로 사용 가능한 액션명·파라미터·설명. LiveController.execute가 실제로
처리하는 액션과 대응한다(앱별 _exec_* 참조).
"""

ACTIONS_SCHEMA = {
    "hwp": {
        # blockId 기반 정밀 편집 (CVD 스캔 후 사용)
        "replace_cell_content": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "표 셀 내용 교체"},
        "delete_cell_content": {"params": {"block_id": "블록ID"}, "desc": "표 셀 내용 삭제"},
        "replace_paragraph": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "문단 내용 교체"},
        "append_paragraph": {"params": {"block_id": "블록ID", "new_text": "새 텍스트"}, "desc": "문단 뒤에 새 문단 추가"},
        "replace_table_row": {"params": {"block_id": "블록ID", "row_texts": ["셀1", "셀2"]}, "desc": "표 행 전체 교체"},
        "append_table_row": {"params": {"block_id": "블록ID", "row_texts": ["셀1", "셀2"]}, "desc": "표에 행 추가"},
        "apply_para_style": {"params": {"block_id": "블록ID", "font_size": "크기", "font_family": "글꼴", "align": "정렬"}, "desc": "문단 서식 적용"},
        # 범용 편집
        "insert_text": {"params": {"text": "텍스트"}, "desc": "커서 위치에 텍스트 삽입"},
        "find_and_replace_all": {"params": {"old_text": "찾을 텍스트", "new_text": "바꿀 텍스트"}, "desc": "전체 찾아 바꾸기"},
        "set_field": {"params": {"field_name": "누름틀 이름", "value": "값"}, "desc": "누름틀 필드에 값 설정"},
        "create_table": {"params": {"rows": "행 수", "cols": "열 수"}, "desc": "표 생성"},
        "move_to_start": {"params": {}, "desc": "문서 처음으로 이동"},
        "move_to_end": {"params": {}, "desc": "문서 끝으로 이동"},
        "save": {"params": {}, "desc": "저장"},
        "save_as": {"params": {"path": "경로", "format": "HWP|HWPX|PDF"}, "desc": "다른 이름으로 저장"},
    },
    "excel": {
        "set_cell": {"params": {"cell": "셀 참조 (A1 또는 시트!A1)", "value": "값"}, "desc": "셀 값 설정"},
        "set_cells": {"params": {"cells": "{셀참조: 값, ...}"}, "desc": "여러 셀 한번에 설정"},
        "get_cell": {"params": {"cell": "셀 참조"}, "desc": "셀 값 읽기"},
        "get_range": {"params": {"range": "범위 (A1:C10)"}, "desc": "범위 읽기"},
        "active_sheet": {"params": {"sheet": "시트 이름"}, "desc": "시트 전환"},
        "add_sheet": {"params": {"name": "시트 이름"}, "desc": "시트 추가"},
        "insert_row": {"params": {"row": "행 번호"}, "desc": "행 삽입"},
        "delete_row": {"params": {"row": "행 번호"}, "desc": "행 삭제"},
        "auto_fit": {"params": {}, "desc": "열 너비 자동 조정"},
        "save": {"params": {}, "desc": "저장"},
    },
    "ppt": {
        "set_text": {"params": {"slide": "슬라이드 번호", "shape": "도형 인덱스(0=제목,1=본문)", "text": "텍스트"}, "desc": "텍스트 수정"},
        "add_slide": {"params": {"title": "제목", "content": "내용", "layout": "레이아웃(2=제목+내용)"}, "desc": "슬라이드 추가"},
        "set_note": {"params": {"slide": "슬라이드 번호", "text": "노트 내용"}, "desc": "발표자 노트 수정"},
        "delete_slide": {"params": {"slide": "슬라이드 번호"}, "desc": "슬라이드 삭제"},
        "set_table_cell": {"params": {"slide": "슬라이드 번호", "row": "행", "col": "열", "text": "텍스트"}, "desc": "표 셀 수정"},
        "save": {"params": {}, "desc": "저장"},
    },
    "word": {
        "insert_text": {"params": {"text": "텍스트"}, "desc": "커서 위치에 텍스트 삽입"},
        "replace_text": {"params": {"find": "찾을 텍스트", "replace": "바꿀 텍스트"}, "desc": "전체 찾아 바꾸기"},
        "set_paragraph": {"params": {"paragraph": "문단 번호", "text": "새 텍스트"}, "desc": "문단 내용 교체"},
        "append_paragraph": {"params": {"text": "텍스트"}, "desc": "문서 끝에 문단 추가"},
        "format_paragraph": {"params": {"paragraph": "문단 번호", "font_size": "크기", "font_name": "글꼴", "bold": "볼드", "align": "정렬"}, "desc": "문단 서식 변경"},
        "set_table_cell": {"params": {"table": "표 번호", "row": "행", "col": "열", "text": "텍스트"}, "desc": "표 셀 수정"},
        "save": {"params": {}, "desc": "저장"},
        "save_as": {"params": {"path": "경로"}, "desc": "다른 이름으로 저장"},
    },
}
