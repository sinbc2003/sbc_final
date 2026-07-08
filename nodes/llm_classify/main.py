"""
LLM 텍스트 분류 노드.

입력 텍스트를 지정된 카테고리 목록 중 하나로 분류하고 신뢰도를 반환한다.
"""

import json
import re


def _match_category(value: str, categories: list[str]) -> str | None:
    """LLM이 낸 값을 카테고리 목록에 맞춘다. 완전일치 → 부분일치 → None."""
    v = (value or "").strip()
    if not v:
        return None
    for c in categories:  # 완전 일치
        if v == c.strip():
            return c.strip()
    for c in categories:  # 부분 일치 (양방향 포함)
        cs = c.strip()
        if cs and (cs in v or v in cs):
            return cs
    return None


def _parse_response(raw: str, categories: list[str]) -> tuple[str, str]:
    """LLM 응답에서 category와 confidence를 추출하고 목록에 대조한다."""
    # JSON 파싱 시도
    json_match = re.search(r"\{[^}]+\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group())
            confidence = str(data.get("confidence", "0.5")).strip()
            matched = _match_category(str(data.get("category", "")), categories)
            if matched:
                return matched, confidence
        except json.JSONDecodeError:
            pass

    # JSON 파싱 실패/목록 밖 값 → 원문에서 카테고리 이름 직접 매칭
    for cat in categories:
        if cat.strip() in raw:
            return cat.strip(), "0.5"

    # 최후: 목록 밖 값이므로 첫 카테고리로 강등(낮은 신뢰도)
    return (categories[0].strip() if categories else "기타"), "0.3"


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs.get("입력텍스트")
    if text is None or (isinstance(text, str) and not text.strip()):
        raise ValueError("입력 '입력텍스트'가 연결되지 않았거나 비어 있습니다.")
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    categories_str = params.get("categories", "수학, 과학, 국어, 영어, 기타")
    categories = [c.strip() for c in categories_str.split(",") if c.strip()]
    if not categories:
        raise ValueError("카테고리 목록이 비어 있습니다.")
    provider = params.get("provider", "auto")

    context["progress"](0.1)
    context["log"](f"분류 시작 (카테고리: {categories_str})")

    prompt = (
        f"다음 텍스트를 아래 카테고리 중 하나로 분류하라.\n\n"
        f"[카테고리 목록]\n{', '.join(categories)}\n\n"
        f"[규칙]\n"
        f"- 반드시 위 카테고리 중 하나만 선택하라.\n"
        f"- 응답은 반드시 JSON 형식으로 하라.\n"
        f'- 형식: {{"category": "선택한 카테고리", "confidence": 0.0~1.0}}\n'
        f"- JSON 외의 텍스트를 포함하지 마라.\n\n"
        f"[텍스트]\n{text}"
    )

    context["progress"](0.3)
    context["log"](f"LLM 호출 (provider={provider})")

    # JSON 스키마 강제: category를 enum으로 제한 → 로컬 모델이 목록 밖 값을 못 냄
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories},
            "confidence": {"type": "number"},
        },
        "required": ["category", "confidence"],
        "additionalProperties": False,
    }
    raw = llm.generate(
        prompt,
        max_tokens=256,
        temperature=0.1,
        provider=provider,
        json_schema=schema,
    )

    context["progress"](0.8)
    context["log"]("응답 파싱 중")

    category, confidence = _parse_response(raw, categories)

    context["progress"](1.0)
    context["log"](f"분류 완료: {category} (신뢰도: {confidence})")

    return {"분류결과": category, "신뢰도": confidence}
