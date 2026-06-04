"""
컬럼명 매핑 노드.

"학번→학생번호, 국→국어점수" 형태의 규칙을 파싱하여
표 데이터의 컬럼명을 rename한다.
"""

import re

import pandas as pd


def _parse_mapping_rules(rules_str: str) -> dict[str, str]:
    """매핑 규칙 문자열을 딕셔너리로 파싱."""
    if not rules_str or not rules_str.strip():
        return {}

    mapping = {}
    # 쉼표 또는 줄바꿈으로 구분
    parts = re.split(r"[,\n]", rules_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # → 또는 -> 로 구분
        match = re.match(r"^(.+?)\s*(?:→|->)\s*(.+)$", part)
        if match:
            old_name = match.group(1).strip()
            new_name = match.group(2).strip()
            mapping[old_name] = new_name

    return mapping


def execute(inputs: dict, params: dict, context: dict) -> dict:
    import json as _json
    table_data = inputs["표데이터"]
    rules_str = params.get("mapping_rules", "")

    # JSON 문자열이면 파싱
    if isinstance(table_data, str):
        try:
            table_data = _json.loads(table_data)
        except (ValueError, _json.JSONDecodeError):
            raise TypeError(f"표 데이터를 파싱할 수 없습니다: {table_data[:100]}")

    context["progress"](0.1)
    context["log"]("컬럼명 매핑 시작")

    # DataFrame 변환
    if isinstance(table_data, list):
        df = pd.DataFrame(table_data)
    elif isinstance(table_data, pd.DataFrame):
        df = table_data.copy()
    else:
        raise TypeError(f"지원하지 않는 데이터 타입: {type(table_data)}")

    mapping = _parse_mapping_rules(rules_str)

    if not mapping:
        context["log"]("매핑 규칙이 없어 원본 그대로 반환")
        context["progress"](1.0)
        return {"표데이터": df.to_dict("records")}

    # 존재하는 컬럼만 매핑 적용
    valid_mapping = {k: v for k, v in mapping.items() if k in df.columns}
    skipped = set(mapping.keys()) - set(valid_mapping.keys())

    if skipped:
        context["log"](f"존재하지 않는 컬럼 건너뜀: {', '.join(skipped)}")

    df = df.rename(columns=valid_mapping)

    context["progress"](1.0)
    context["log"](
        f"매핑 완료 ({len(valid_mapping)}개 변경: "
        + ", ".join(f"{k}→{v}" for k, v in valid_mapping.items())
        + ")"
    )

    return {"표데이터": df.to_dict("records")}
