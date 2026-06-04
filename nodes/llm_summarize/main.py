"""
LLM 텍스트 요약 노드.

입력 텍스트를 스타일(bullet/paragraph/oneliner)에 따라 요약한다.
"""

STYLE_INSTRUCTIONS = {
    "bullet": "글머리 기호(- )를 사용하여 핵심 내용을 항목별로 요약하라.",
    "paragraph": "하나의 문단으로 핵심 내용을 자연스럽게 요약하라.",
    "oneliner": "한 문장으로 핵심을 요약하라.",
}


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs["입력텍스트"]
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    style = params.get("style", "bullet")
    max_length = int(params.get("max_length", 500))
    provider = params.get("provider", "auto")

    context["progress"](0.1)
    context["log"](f"요약 시작 (스타일={style}, 최대 {max_length}자)")

    style_instruction = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["bullet"])

    prompt = (
        f"다음 텍스트를 요약하라.\n\n"
        f"[요약 규칙]\n"
        f"- {style_instruction}\n"
        f"- 최대 {max_length}자 이내로 작성하라.\n"
        f"- 원문에 없는 내용을 추가하지 마라.\n\n"
        f"[원문]\n{text}"
    )

    context["progress"](0.3)
    context["log"](f"LLM 호출 (provider={provider})")

    result = llm.generate(
        prompt,
        max_tokens=max_length * 2,
        temperature=0.3,
        provider=provider,
    )

    context["progress"](1.0)
    context["log"](f"요약 완료 ({len(result)}자)")

    return {"출력텍스트": result}
