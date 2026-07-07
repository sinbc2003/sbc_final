"""HWP 액션 스키마 — LLM 노출용."""

HWP_ACTIONS_SCHEMA = {
    "replace_cell_content": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "표 셀 내용 교체 (blockId 기반)"
    },
    "delete_cell_content": {
        "params": {"block_id": "블록 ID"},
        "desc": "표 셀 내용 삭제"
    },
    "replace_paragraph": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "문단 내용 교체"
    },
    "append_paragraph": {
        "params": {"block_id": "블록 ID", "new_text": "새 텍스트"},
        "desc": "문단 뒤에 새 문단 추가"
    },
    "find_and_replace_all": {
        "params": {"old_text": "찾을 텍스트", "new_text": "바꿀 텍스트"},
        "desc": "전체 찾아 바꾸기"
    },
    "insert_text": {
        "params": {"text": "삽입할 텍스트"},
        "desc": "커서 위치에 텍스트 삽입"
    },
    "apply_para_style": {
        "params": {"block_id": "블록 ID", "font_size": "크기(pt)", "font_family": "글꼴", "align": "정렬(left/center/right/justify)", "spacing": "줄간격", "indentation": "들여쓰기"},
        "desc": "문단 서식 적용"
    },
    "create_table": {
        "params": {"rows": "행 수", "cols": "열 수"},
        "desc": "표 생성"
    },
    "replace_table_row": {
        "params": {"block_id": "블록 ID", "row_texts": ["셀1", "셀2", "..."]},
        "desc": "표 행 전체 셀 교체"
    },
    "append_table_row": {
        "params": {"block_id": "블록 ID", "row_texts": ["셀1", "셀2", "..."]},
        "desc": "표에 행 추가"
    },
    "save": {
        "params": {},
        "desc": "문서 저장"
    },
    "save_as": {
        "params": {"path": "저장 경로", "format": "HWP|HWPX|PDF"},
        "desc": "다른 이름으로 저장"
    },
}
