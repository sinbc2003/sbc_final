"""
LLM 정보 추출 노드.

입력 텍스트에서 지정된 필드를 추출하여 테이블(2차원 리스트)로 반환한다.
"""

import json
import re


def _parse_to_table(raw: str, fields: list[str]) -> list[list[str]]:
    """LLM 응답(JSON 배열)을 헤더 포함 2차원 리스트로 변환한다."""
    # JSON 배열 파싱 시도
    array_match = re.search(r"\[[\s\S]*\]", raw)
    if array_match:
        try:
            data = json.loads(array_match.group())
            if isinstance(data, list) and len(data) > 0:
                table = [fields]
                for item in data:
                    if isinstance(item, dict):
                        row = [str(item.get(f, "")) for f in fields]
                    elif isinstance(item, list):
                        row = [str(v) for v in item]
                        # 필드 수 맞추기
                        while len(row) < len(fields):
                            row.append("")
                        row = row[: len(fields)]
                    else:
                        continue
                    table.append(row)
                return table
        except json.JSONDecodeError:
            pass

    # 파싱 실패 시 빈 테이블 반환
    return [fields]


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs["입력텍스트"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    fields_str = params.get("fields", "이름, 학번, 점수")
    fields = [f.strip() for f in fields_str.split(",") if f.strip()]
    provider = params.get("provider", "auto")

    context["progress"](0.1)
    context["log"](f"정보 추출 시작 (필드: {fields_str})")

    fields_json = ", ".join(f'"{f}"' for f in fields)
    example_obj = ", ".join(f'"{f}": "값"' for f in fields)

    prompt = (
        f"다음 텍스트에서 정보를 추출하라.\n\n"
        f"[추출 필드]\n{', '.join(fields)}\n\n"
        f"[규칙]\n"
        f"- 응답은 반드시 JSON 배열 형식으로 하라.\n"
        f"- 각 항목은 {{{example_obj}}} 형태의 객체이다.\n"
        f"- 텍스트에서 찾을 수 있는 모든 항목을 추출하라.\n"
        f"- 값이 없으면 빈 문자열로 표시하라.\n"
        f"- JSON 외의 텍스트를 포함하지 마라.\n\n"
        f"[텍스트]\n{text}"
    )

    context["progress"](0.3)
    context["log"](f"LLM 호출 (provider={provider})")

    raw = llm.generate(
        prompt,
        max_tokens=2048,
        temperature=0.1,
        provider=provider,
    )

    context["progress"](0.8)
    context["log"]("응답 파싱 중")

    table = _parse_to_table(raw, fields)

    context["progress"](1.0)
    context["log"](f"추출 완료 ({len(table) - 1}건)")

    return {"추출결과": table}
