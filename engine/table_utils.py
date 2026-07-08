"""표(table) 페이로드 정규화 유틸.

노드마다 'table'을 서로 다른 모양으로 내보내 연결 시 데이터가 조용히
오염되던 문제를 흡수한다. 표를 소비하는 노드는 입력을 to_records()로
정규화한 뒤 사용한다.

지원하는 입력 모양:
- records:            [{col: val}, ...]                     (표준)
- 시트 래퍼(xlsx_to_md): [{"sheet":.., "data":[records]}, ...]
- 헤더행 2D 리스트:    [[헤더...], [값...], ...]
- 단일 dict:          {col: val}
- JSON 문자열:        위 구조를 직렬화한 문자열
"""

from __future__ import annotations

import json


def is_sheet_wrapper(item) -> bool:
    """xlsx_to_md의 시트 래퍼({sheet/columns/rows + data: [records]})인지."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("data"), list)
        and ("sheet" in item or "columns" in item or "rows" in item)
    )


def to_records(value) -> list[dict]:
    """어떤 table 페이로드든 records(list[dict])로 정규화한다.

    정규화 불가능한 입력은 빈 리스트를 반환한다(호출부가 빈 표로 처리).
    pandas.DataFrame은 이 함수가 처리하지 않는다(호출부에서 먼저 분기).
    """
    # JSON 문자열
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return []

    if value is None:
        return []

    # 단일 dict
    if isinstance(value, dict):
        if is_sheet_wrapper(value):
            return [r for r in value["data"] if isinstance(r, dict)]
        return [value]

    if not isinstance(value, list) or not value:
        return []

    # 시트 래퍼 리스트: 모든 시트의 data를 이어붙임
    if all(is_sheet_wrapper(it) for it in value):
        out: list[dict] = []
        for sheet in value:
            out.extend(r for r in sheet["data"] if isinstance(r, dict))
        return out

    # 헤더행 + 데이터행 2D 리스트
    if all(isinstance(it, (list, tuple)) for it in value):
        header = [str(h) for h in value[0]]
        out = []
        for row in value[1:]:
            out.append(
                {header[i]: (str(row[i]) if i < len(row) else "") for i in range(len(header))}
            )
        return out

    # 이미 records (dict가 아닌 항목은 버림)
    return [it for it in value if isinstance(it, dict)]
