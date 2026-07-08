"""
LLM 정보 추출 노드.

입력 텍스트에서 지정된 필드를 추출하여 표(records: list of dict)로 반환한다.
소형 로컬 모델도 안정적으로 쓰도록 JSON 스키마 강제 디코딩을 사용한다.
"""

import json
import re


def _build_schema(fields: list[str]) -> dict:
    """추출 필드로 JSON 배열 스키마를 구성한다.

    llama-server(GBNF)가 문법 차원에서 강제하므로 소형 모델도 형식을 못 틀린다.
    각 항목은 지정 필드를 문자열 값으로 갖는 객체.
    """
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
            "required": fields,
            "additionalProperties": False,
        },
    }


def _extract_json_array(raw: str) -> list | None:
    """LLM 응답에서 JSON 배열을 견고하게 추출한다.

    반환: 파싱된 list (실패 시 None). 빈 결과(정상적으로 0건)와 파싱 실패를
    구분하기 위해 실패는 None으로 알린다.
    """
    if not raw:
        return None
    text = raw.strip()

    # 코드펜스 제거 (```json ... ```)
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    # 1) 전체가 JSON인 경우
    for candidate in (text,):
        try:
            data = json.loads(candidate)
            return _coerce_list(data)
        except (json.JSONDecodeError, TypeError):
            pass

    # 2) 객체 배열 우선 (비탐욕) — 앞뒤 잡음 텍스트 무시
    obj_arr = re.search(r"\[\s*\{[\s\S]*\}\s*\]", text)
    if obj_arr:
        try:
            return _coerce_list(json.loads(obj_arr.group()))
        except json.JSONDecodeError:
            pass

    # 3) 일반 배열 (탐욕 최소화 실패 시 최후)
    any_arr = re.search(r"\[[\s\S]*\]", text)
    if any_arr:
        try:
            return _coerce_list(json.loads(any_arr.group()))
        except json.JSONDecodeError:
            pass

    return None


def _coerce_list(data) -> list | None:
    """파싱 결과를 항목 리스트로 정규화. dict 래퍼({key: [...]})도 흡수."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 단일 객체 또는 {"결과": [...]} 형태
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data]
    return None


def _to_records(items: list, fields: list[str]) -> list[dict]:
    """LLM 항목 리스트를 records(list of dict)로 변환. 키 = 필드명."""
    records: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            records.append({f: str(item.get(f, "")) for f in fields})
        elif isinstance(item, (list, tuple)):
            vals = [str(v) for v in item]
            records.append({f: (vals[i] if i < len(vals) else "") for i, f in enumerate(fields)})
        # 그 외 타입은 건너뜀
    return records


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs.get("입력텍스트")
    if text is None or (isinstance(text, str) and not text.strip()):
        raise ValueError("입력 '입력텍스트'가 연결되지 않았거나 비어 있습니다. 텍스트 출력 노드를 연결하세요.")

    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    fields_str = params.get("fields", "이름, 학번, 점수")
    fields = [f.strip() for f in fields_str.split(",") if f.strip()]
    if not fields:
        raise ValueError("추출 필드가 비어 있습니다. '추출 필드'에 쉼표로 구분된 필드명을 입력하세요.")
    provider = params.get("provider", "auto")

    context["progress"](0.1)
    context["log"](f"정보 추출 시작 (필드: {fields_str})")

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

    # JSON 스키마 강제 디코딩: 로컬은 GBNF 문법으로 강제, API는 소프트 강제
    schema = _build_schema(fields)
    raw = llm.generate(
        prompt,
        max_tokens=2048,
        temperature=0.1,
        provider=provider,
        json_schema=schema,
    )

    context["progress"](0.8)
    context["log"]("응답 파싱 중")

    items = _extract_json_array(raw)
    if items is None:
        # 무음 실패 방지: 파싱 실패를 명시적으로 알린다
        snippet = (raw or "").strip().replace("\n", " ")[:200]
        context["log"](f"[WARN] LLM 응답을 JSON으로 파싱하지 못했습니다. 원문 일부: {snippet}")
        records: list[dict] = []
    else:
        records = _to_records(items, fields)

    context["progress"](1.0)
    context["log"](f"추출 완료 ({len(records)}건)")

    return {"추출결과": records}
