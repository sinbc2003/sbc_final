"""
LLM 번역 노드.

입력 텍스트를 지정된 대상 언어로 번역한다.
"""

LANG_NAMES = {
    "영어": "English",
    "한국어": "Korean",
    "일본어": "Japanese",
    "중국어": "Chinese",
}


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs.get("입력텍스트", "")
    if not text or not str(text).strip():
        raise ValueError("입력 '입력텍스트'가 비어 있습니다 — 상류 노드 연결을 확인하세요.")
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    # GPT가 target_language / target_lang 둘 다 쓸 수 있음
    target_lang = params.get("target_lang") or params.get("target_language", "영어")
    # 코드→한글 변환
    LANG_CODES = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어"}
    if target_lang in LANG_CODES:
        target_lang = LANG_CODES[target_lang]

    provider = params.get("provider", "auto")
    lang_en = LANG_NAMES.get(target_lang, target_lang)

    context["progress"](0.1)
    context["log"](f"번역 시작 (대상: {target_lang})")

    prompt = (
        f"다음 텍스트를 {target_lang}({lang_en})로 번역하라.\n\n"
        f"[번역 규칙]\n"
        f"- 원문의 의미를 정확히 전달하라.\n"
        f"- 자연스러운 {target_lang} 표현을 사용하라.\n"
        f"- 번역문만 출력하라. 설명이나 부연을 추가하지 마라.\n\n"
        f"[원문]\n{text}"
    )

    context["progress"](0.3)
    context["log"](f"LLM 호출 (provider={provider})")

    # max_tokens 하한 보장 (짧은 입력에서 0/과소로 API 400·빈 결과 방지)
    result = llm.generate(
        prompt,
        max_tokens=max(256, len(text) * 3),
        temperature=0.3,
        provider=provider,
    )

    context["progress"](1.0)
    context["log"](f"번역 완료 ({len(result)}자)")

    return {"출력텍스트": result}
