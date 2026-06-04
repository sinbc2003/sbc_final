"""
XLSX 저장 노드.

pandas DataFrame을 to_excel로 XLSX 파일로 저장한다.
"""

import os

import pandas as pd


def execute(inputs: dict, params: dict, context: dict) -> dict:
    import json as _json
    table_data = inputs["표데이터"]
    output_name = params.get("output_name", "output")
    output_path = os.path.join(context["temp_dir"], f"{output_name}.xlsx")

    # JSON 문자열이면 파싱
    if isinstance(table_data, str):
        try:
            table_data = _json.loads(table_data)
        except (ValueError, _json.JSONDecodeError):
            raise TypeError(f"표 데이터를 파싱할 수 없습니다: {table_data[:100]}")

    context["progress"](0.1)
    context["log"]("XLSX 저장 시작")

    # DataFrame 변환
    if isinstance(table_data, list):
        df = pd.DataFrame(table_data)
    elif isinstance(table_data, pd.DataFrame):
        df = table_data
    else:
        raise TypeError(f"지원하지 않는 데이터 타입: {type(table_data)}")

    if df.empty:
        context["log"]("경고: 빈 데이터프레임")

    context["progress"](0.5)

    df.to_excel(output_path, index=False, engine="openpyxl")

    context["progress"](1.0)
    context["log"](f"XLSX 저장 완료: {output_path} ({len(df)}행, {len(df.columns)}열)")

    return {"파일": output_path}
