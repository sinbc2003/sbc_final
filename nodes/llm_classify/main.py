"""
LLM 텍스트 분류 노드.

입력 텍스트를 지정된 카테고리 목록 중 하나로 분류하고 신뢰도를 반환한다.
"""

import json
import re


def _parse_response(raw: str, categories: list[str]) -> tuple[str, str]:
    """LLM 응답에서 category와 confidence를 추출한다."""
    # JSON 파싱 시도
    json_match = re.search(r"\{[^}]+\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group())
            category = str(data.get("category", "")).strip()
            confidence = str(data.get("confidence", "0.5")).strip()
            if category:
                return category, confidence
        except json.JSONDecodeError:
            pass

    # JSON 파싱 실패 시 카테고리 이름 직접 매칭
    for cat in categories:
        if cat.strip() in raw:
            return cat.strip(), "0.5"

    return categories[0].strip() if categories else "기타", "0.3"


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs["입력텍스트"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    categories_str = params.get("categories", "수학, 과학, 국어, 영어, 기타")
    categories = [c.strip() for c in categories_str.split(",") if c.strip()]
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

    raw = llm.generate(
        prompt,
        max_tokens=256,
        temperature=0.1,
        provider=provider,
    )

    context["progress"](0.8)
    context["log"]("응답 파싱 중")

    category, confidence = _parse_response(raw, categories)

    context["progress"](1.0)
    context["log"](f"분류 완료: {category} (신뢰도: {confidence})")

    return {"분류결과": category, "신뢰도": confidence}
