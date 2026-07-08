"""
XLSX 저장 노드.

pandas DataFrame을 to_excel로 XLSX 파일로 저장한다.
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from engine.table_utils import to_records  # noqa: E402


def execute(inputs: dict, params: dict, context: dict) -> dict:
    table_data = inputs["표데이터"]
    output_name = params.get("output_name", "output")
    output_path = os.path.join(context["temp_dir"], f"{output_name}.xlsx")

    context["progress"](0.1)
    context["log"]("XLSX 저장 시작")

    # DataFrame 변환 — 다양한 table 페이로드를 records로 정규화
    if isinstance(table_data, pd.DataFrame):
        df = table_data
    else:
        df = pd.DataFrame(to_records(table_data))

    if df.empty:
        context["log"]("경고: 빈 데이터프레임")

    context["progress"](0.5)

    df.to_excel(output_path, index=False, engine="openpyxl")

    context["progress"](1.0)
    context["log"](f"XLSX 저장 완료: {output_path} ({len(df)}행, {len(df.columns)}열)")

    return {"파일": output_path}
