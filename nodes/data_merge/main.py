"""
데이터 병합 노드.

pandas를 사용하여 여러 표 데이터를 concat 또는 merge로 병합한다.
"""

import pandas as pd


def _parse_table(data):
    """JSON 문자열이면 파싱, 아니면 그대로."""
    import json
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return data
    return data


def execute(inputs: dict, params: dict, context: dict) -> dict:
    table_list = _parse_table(inputs.get("표목록", []))
    join_type = params.get("join_type", "concat")

    if not table_list:
        raise ValueError("병합할 표 데이터가 비어있습니다")

    context["progress"](0.1)
    context["log"](f"데이터 병합 시작 ({len(table_list)}개, 방식={join_type})")

    # list of dict → DataFrame 변환
    dfs = []
    for item in table_list:
        if isinstance(item, list):
            dfs.append(pd.DataFrame(item))
        elif isinstance(item, pd.DataFrame):
            dfs.append(item)
        elif isinstance(item, dict):
            dfs.append(pd.DataFrame([item]))
        else:
            raise TypeError(f"지원하지 않는 데이터 타입: {type(item)}")

    context["progress"](0.3)

    if join_type == "concat":
        result_df = pd.concat(dfs, ignore_index=True)
    elif join_type == "merge":
        if len(dfs) < 2:
            result_df = dfs[0]
        else:
            # 공통 컬럼을 키로 순차 merge
            result_df = dfs[0]
            for df in dfs[1:]:
                common_cols = list(
                    set(result_df.columns) & set(df.columns)
                )
                if common_cols:
                    result_df = result_df.merge(df, on=common_cols, how="outer")
                else:
                    # 공통 컬럼 없으면 cross join 대신 concat
                    result_df = pd.concat(
                        [result_df, df], axis=1
                    )
    else:
        raise ValueError(f"알 수 없는 병합 방식: {join_type}")

    context["progress"](1.0)

    result = result_df.to_dict("records")
    context["log"](f"병합 완료 ({len(result)}행, {len(result_df.columns)}열)")

    return {"통합표": result}
