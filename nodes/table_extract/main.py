"""
표 추출 노드.

마크다운 텍스트에서 | 로 구분된 표를 파싱하여
JSON(list of dict) 형태로 반환한다.
"""

import re


def _parse_md_tables(text: str) -> list[list[dict]]:
    """마크다운 텍스트에서 모든 표를 파싱하여 리스트로 반환."""
    tables = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 표 시작 감지: | 로 시작하고 끝나는 줄
        if re.match(r"^\|.*\|$", line):
            table_lines = []
            while i < len(lines) and re.match(r"^\|.*\|$", lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) >= 2:
                table_data = _parse_single_table(table_lines)
                if table_data:
                    tables.append(table_data)
            continue

        i += 1

    return tables


def _parse_single_table(table_lines: list[str]) -> list[dict]:
    """단일 마크다운 표를 list of dict로 변환."""
    # 헤더 파싱
    header_cells = [c.strip() for c in table_lines[0].strip("|").split("|")]

    # 구분선(---|---) 찾기 및 건너뛰기
    data_start = 1
    if len(table_lines) > 1:
        second_line = table_lines[1].strip("|")
        cells = [c.strip() for c in second_line.split("|")]
        if all(re.match(r"^[-:]+$", c) for c in cells):
            data_start = 2

    # 데이터 행 파싱
    rows = []
    for line in table_lines[data_start:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        row = {}
        for j, header in enumerate(header_cells):
            row[header] = cells[j] if j < len(cells) else ""
        rows.append(row)

    return rows


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs["텍스트"]
    table_index = int(params.get("table_index", 0))

    context["progress"](0.1)
    context["log"]("표 추출 시작")

    tables = _parse_md_tables(text)

    if not tables:
        context["log"]("표를 찾지 못했습니다")
        return {"표데이터": []}

    context["log"](f"총 {len(tables)}개 표 발견")

    if table_index == -1:
        # 모든 표를 하나로 합치기
        result = []
        for t in tables:
            result.extend(t)
    else:
        if table_index >= len(tables):
            raise IndexError(
                f"표 번호 {table_index}이 범위를 벗어남 "
                f"(총 {len(tables)}개 표)"
            )
        result = tables[table_index]

    context["progress"](1.0)
    context["log"](f"추출 완료 ({len(result)}행)")

    return {"표데이터": result}
