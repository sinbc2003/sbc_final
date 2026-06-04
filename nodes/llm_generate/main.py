"""
LLM 텍스트 생성 노드.

프롬프트 템플릿의 {{변수명}}을 입력값으로 치환한 뒤 LLM 호출.
긴 문서는 자동으로 청크 분할 → 개별 처리 → 결과 합치기 (map-reduce).
"""

import re

# 청크 분할 임계치 (글자 수). 이보다 길면 자동 분할.
CHUNK_THRESHOLD = 8000
CHUNK_SIZE = 6000
CHUNK_OVERLAP = 300


def _render_template(template: str, variables: dict) -> str:
    """{{변수명}} 패턴을 실제 값으로 치환."""
    def replacer(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))
    return re.sub(r"\{\{(.+?)\}\}", replacer, template)


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """텍스트를 문장 경계 기준으로 분할."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        # 문장 경계 찾기 (마침표, 줄바꿈)
        boundary = text.rfind("\n", start + chunk_size // 2, end)
        if boundary == -1:
            boundary = text.rfind(". ", start + chunk_size // 2, end)
        if boundary == -1:
            boundary = end
        else:
            boundary += 1
        chunks.append(text[start:boundary])
        start = boundary - overlap
    return chunks


def _find_input_var(template: str) -> str | None:
    """템플릿에서 가장 큰 변수명 찾기 (청킹 대상)."""
    matches = re.findall(r"\{\{(.+?)\}\}", template)
    return matches[0].strip() if matches else None


def execute(inputs: dict, params: dict, context: dict) -> dict:
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    template = params.get("prompt_template", "{{입력텍스트}}")
    variables = dict(inputs)
    variables.update(params)
    prompt = _render_template(template, variables)

    provider = params.get("provider", "auto")
    max_tokens = int(params.get("max_tokens", 2048))
    temperature = float(params.get("temperature", 0.7))
    lora = params.get("lora") or None
    model = params.get("model") if params.get("model") else None

    context["progress"](0.1)

    # 모델 정보
    try:
        info = llm.get_provider_info(provider)
        context["log"](f"AI 모델: {info.get('provider', provider)} / {info.get('model', '?')}")
    except Exception:
        pass

    # ── 긴 문서 자동 분할 (map-reduce) ────────────
    if len(prompt) > CHUNK_THRESHOLD:
        input_var = _find_input_var(template)
        input_text = variables.get(input_var, "") if input_var else ""

        if input_text and len(input_text) > CHUNK_THRESHOLD:
            chunks = _split_text(input_text, CHUNK_SIZE, CHUNK_OVERLAP)
            context["log"](f"문서가 길어 {len(chunks)}개로 나눠서 처리합니다 ({len(input_text)}자)")

            results = []
            for i, chunk in enumerate(chunks):
                context["progress"](0.1 + 0.8 * i / len(chunks))
                context["log"](f"  {i+1}/{len(chunks)} 처리 중...")
                chunk_vars = dict(variables)
                chunk_vars[input_var] = chunk
                chunk_prompt = _render_template(template, chunk_vars)
                try:
                    r = llm.generate(chunk_prompt, max_tokens=max_tokens,
                                     temperature=temperature, lora=lora,
                                     provider=provider, model=model)
                    results.append(r)
                except RuntimeError as e:
                    context["log"](f"  {i+1}/{len(chunks)} 오류: {e}")
                    results.append(f"[처리 실패: {e}]")

            # 결과 합치기
            if len(results) > 1:
                combined = "\n\n---\n\n".join(results)
                # 최종 요약 (결과가 너무 길면)
                if len(combined) > CHUNK_THRESHOLD and "요약" in template:
                    context["log"]("분할 결과를 최종 요약합니다")
                    summary_prompt = f"다음은 긴 문서를 나눠 처리한 결과입니다. 이것을 하나로 통합 요약해주세요:\n\n{combined}"
                    try:
                        combined = llm.generate(summary_prompt, max_tokens=max_tokens,
                                                temperature=temperature, provider=provider, model=model)
                    except Exception:
                        pass
                context["progress"](1.0)
                context["log"](f"완료 ({len(combined)}자, {len(chunks)}개 청크 처리)")
                return {"출력텍스트": combined}
            elif results:
                context["progress"](1.0)
                return {"출력텍스트": results[0]}

    # ── 일반 처리 (짧은 문서) ─────────────────────
    context["log"](f"처리 중... ({len(prompt)}자)")
    context["progress"](0.3)

    try:
        result = llm.generate(prompt, max_tokens=max_tokens, temperature=temperature,
                              lora=lora, provider=provider, model=model)
    except RuntimeError as e:
        context["log"](f"AI 오류: {e}")
        raise

    context["progress"](1.0)
    context["log"](f"완료 ({len(result)}자)")

    return {"출력텍스트": result}
