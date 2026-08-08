"""
LLM 텍스트 생성 노드.

프롬프트 템플릿의 {{변수명}}을 입력값으로 치환한 뒤 LLM 호출.
긴 문서는 자동으로 청크 분할 → 개별 처리 → 결과 합치기 (map-reduce).
"""

import re
from datetime import date

# LoRA 명시적 미사용 값 — 설정 기본 어댑터 자동 폴백을 끄고 베이스로 생성한다.
_LORA_OFF = {"none", "off", "없음", "-"}

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


def _fill_placeholders(text: str, context: dict) -> str:
    """LoRA v4가 학습한 {기관명}/{문서번호} placeholder 치환.

    어댑터가 특정 학교명·관련번호를 각인하는 대신 placeholder를 내도록
    학습됐다(편향 제거) — 학교명은 설정(general.school_name)으로, 관련
    문서번호는 교사가 채울 표시(○○○○)로 바꾼다.
    """
    if "{기관명}" in text or "{문서번호}" in text:
        school = (context.get("config", {}).get("school_name") or "").strip() or "(학교명)"
        text = text.replace("{기관명}", school).replace("{문서번호}", "○○○○")
    # 공문 결문 표기 규정: 마지막 글자 뒤 두 칸 띄고 "끝." — 변환 파이프라인이
    # 공백을 정규화해 학습 데이터 99%가 한 칸이었다(사용자 지적, 실측 2,873:22).
    # 모델 출력과 무관하게 규정 표기로 정규화한다.
    text = re.sub(r"([^\s])[ \t]*끝\s*\.\s*$", r"\1  끝.", text.rstrip())
    if re.match(r"^\s*1\.\s*관련", text):
        text = _normalize_gongmun_notation(text)
    text = _format_gongmun_layout(text)
    return text


def _normalize_gongmun_notation(text: str) -> str:
    """공문 표기 규정 정규화 — 경기도교육청 「한 곳에 정리한 공문서 작성법」
    (행정업무규정 제7조·행안부 편람 근거). 결정론 규정은 코드가 보장한다.

    - 날짜: 연.월.일 → 'YYYY. M. D.' (온점 뒤 1타, 월·일 선행 0 미표기)
    - 관련 문서번호 뒤 '호' 삭제
    """
    def _date(m):
        return f"{m.group(1)}. {int(m.group(2))}. {int(m.group(3))}."
    text = re.sub(r"((?:19|20)\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?",
                  _date, text)
    text = re.sub(r"\)\s*호(?=[\s,.)]|$)", ")", text, flags=re.M)
    return text


# 항목 기호 단계(행정업무 관행): 1. → 가. → 1)/(1) → 가)/(가) → -·○
_ITEM_LEVELS = [
    (re.compile(r"^\d+\.\s"), 0),
    (re.compile(r"^[가-힣]\.\s"), 1),
    (re.compile(r"^\(?\d+\)\s"), 2),
    (re.compile(r"^\(?[가-힣]\)\s"), 3),
    (re.compile(r"^[-○·•]\s"), 4),
]
_NBSP = " "  # 마크다운 4칸 코드블록 오인 없이 들여쓰기를 보존
# 붙임 연속행 정렬(규정: 붙임 뒤 2타) — 한글 폰트에서 전각 공백(U+3000)이
# 글자와 같은 폭이라 '붙임(전각2)+2타' 들여쓰기로 '1.' 밑에 '2.'가 정확히 온다.
_ATTACH_INDENT = "　　" + _NBSP * 2
# 라인이 이 문자로 안 끝나면 다음 비항목 라인은 이어진 문장으로 병합
_SENT_END = tuple(".:)」]?!…")


def _format_gongmun_layout(text: str) -> str:
    """공문 개조식 들여쓰기 정형화(사용자 지적 — 규칙이 명확하니 후처리).

    - 하위 항목은 상위보다 2타씩 들여쓰기(1.→가.→(1) …)
    - 붙임 목록 2. 이하는 '붙임 ' 폭(5타)만큼 들여 첫 항목 1.과 줄 맞춤
    - 모델이 흘리는 순수 '>' 인용 잔재 라인 제거
    공문 산출(첫 항목이 '1. 관련')에만 적용한다.
    """
    if not re.match(r"^\s*1\.\s*관련", text):
        return text
    out = []
    in_attach = False
    for raw in text.splitlines():
        line = re.sub(r"^>\s?", "", raw).rstrip()
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        if s.startswith("붙임"):
            in_attach = True
            # 규정: 붙임 뒤 2타 ("붙임VV1.V…")
            out.append("붙임" + _NBSP * 2 + s[2:].lstrip())
            continue
        if in_attach:
            if re.match(r"^\d+\.\s", s):
                out.append(_ATTACH_INDENT + s)
                continue
            in_attach = False
        for pat, depth in _ITEM_LEVELS:
            if pat.match(s):
                out.append(_NBSP * (2 * depth) + s)
                break
        else:
            # 항목 기호 없는 라인: 직전 라인이 문장 중간에서 끊겼으면 병합
            if (out and out[-1].strip()
                    and not out[-1].rstrip().endswith(_SENT_END)):
                out[-1] = out[-1].rstrip() + " " + s
            else:
                out.append(s)
    # 규정: 첨부물이 하나면 숫자 '1.' 미표기
    attach_lines = [i for i, l in enumerate(out)
                    if l.startswith("붙임") or l.startswith(_ATTACH_INDENT)]
    if len(attach_lines) == 1:
        i = attach_lines[0]
        out[i] = re.sub("^(붙임" + _NBSP + "{2})1\\.\\s*", r"\1", out[i])
    return "\n".join(out)


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


def _find_input_var(template: str, variables: dict) -> str | None:
    """템플릿 변수 중 값이 가장 긴 변수명 찾기 (청킹 대상).

    첫 변수가 아니라 실제 값 길이 기준으로 골라야 긴 입력이 청킹 대상이 된다.
    (param 변수 {{temperature}} 등이 먼저 와도 오선정하지 않음)
    """
    keys = [m.strip() for m in re.findall(r"\{\{(.+?)\}\}", template)]
    if not keys:
        return None
    return max(keys, key=lambda k: len(str(variables.get(k, ""))))


def execute(inputs: dict, params: dict, context: dict) -> dict:
    llm = context.get("llm")
    if llm is None:
        raise RuntimeError("LLM 관리자가 설정되지 않았습니다")

    template = params.get("prompt_template", "{{입력텍스트}}")
    variables = dict(inputs)
    variables.update(params)
    # 오늘 날짜를 템플릿 변수로 제공 — 소형모델은 학습 시점 연도(2024 등)를
    # 가정해 공문·가정통신문의 날짜를 틀리게 쓴다. 프롬프트에 주입해야 맞는다.
    # (params가 우선하므로 사용자가 덮어쓸 수 있다.)
    _t = date.today()
    for k, v in (("오늘", _t.isoformat()), ("올해", str(_t.year)),
                 ("오늘한글", f"{_t.year}년 {_t.month}월 {_t.day}일")):
        variables.setdefault(k, v)
    prompt = _render_template(template, variables)

    provider = params.get("provider", "auto")
    max_tokens = int(params.get("max_tokens", 2048))
    temperature = float(params.get("temperature", 0.7))
    lora = params.get("lora") or None
    model = params.get("model") if params.get("model") else None

    # 'none' 등은 어댑터 명시적 미사용 — 이 값이 없으면 설정 기본 어댑터
    # (공문 LoRA)가 가정통신문·계획서 생성에도 끼어들어 문체가 공문으로 쏠린다.
    lora_off = isinstance(lora, str) and lora.strip().lower() in _LORA_OFF

    # LoRA: 서버에 프리로드된 어댑터(settings.llm.local_lora, 기본 scale 0)를
    # 이 생성 요청만 scale 1.0으로 활성화(로컬 provider 한정 — llm_manager §5 배선).
    # 노드에 미지정이면 설정 기본 어댑터를 따름 — 채팅으로 만든 워크플로우도
    # "생성 = 어댑터 ON" UX가 되도록. (추출·분류 노드는 lora 미전달 = 베이스 그대로)
    if lora_off:
        lora = None
        context["log"]("LoRA 미사용 지정 — 베이스 모델로 생성합니다")
    elif not lora and provider in ("auto", "local"):
        cfg_lora = (getattr(llm, "_config", {}) or {}).get("local_lora")
        if cfg_lora:
            lora = cfg_lora
            context["log"](f"설정 기본 LoRA 적용: '{lora}'")
    elif lora:
        context["log"](f"LoRA 어댑터 요청: '{lora}' (로컬 서버 프리로드 시 생성에 적용)")

    # 현재 배선은 **서버 기동 시 프리로드한 어댑터 1개**를 요청별로 켜고 끄는
    # 방식이다(요청별 교체 미지원). 이름을 잘못 적으면 조용히 다른 어댑터가
    # 적용되거나 베이스로 실행되어 품질 저하 원인을 못 찾는다 → 명시적으로 알린다.
    if lora and provider in ("auto", "local"):
        try:
            loaded = llm._resolve_lora_path()
        except Exception:
            loaded = None
        loaded_name = loaded.stem if loaded else ""
        if not loaded_name:
            context["log"](
                f"[WARN] 어댑터 '{lora}'를 요청했지만 서버에 로드된 LoRA가 없습니다 "
                f"— 베이스 모델로 실행됩니다(설정 > local_lora 확인)"
            )
        elif (lora.lower() not in loaded_name.lower()
              and loaded_name.lower() not in lora.lower()):
            context["log"](
                f"[WARN] 요청한 어댑터 '{lora}'와 서버에 로드된 '{loaded_name}'가 "
                f"다릅니다 — 로드된 어댑터가 적용됩니다(요청별 교체 미지원)"
            )

    context["progress"](0.1)

    # 모델 정보
    try:
        info = llm.get_provider_info(provider)
        context["log"](f"AI 모델: {info.get('provider', provider)} / {info.get('model', '?')}")
    except Exception:
        pass

    # ── 긴 문서 자동 분할 (map-reduce) ────────────
    if len(prompt) > CHUNK_THRESHOLD:
        input_var = _find_input_var(template, variables)
        input_text = str(variables.get(input_var, "")) if input_var else ""

        if input_text and len(input_text) > CHUNK_THRESHOLD:
            chunks = _split_text(input_text, CHUNK_SIZE, CHUNK_OVERLAP)
            context["log"](f"문서가 길어 {len(chunks)}개로 나눠서 처리합니다 ({len(input_text)}자)")

            results = []
            failures = 0
            for i, chunk in enumerate(chunks):
                context["progress"](0.1 + 0.8 * i / len(chunks))
                context["log"](f"  {i+1}/{len(chunks)} 처리 중...")
                chunk_vars = dict(variables)
                chunk_vars[input_var] = chunk
                chunk_prompt = _render_template(template, chunk_vars)
                try:
                    # API SDK 예외(RateLimit 등)도 잡아야 청크 단위 복구가 동작
                    r = llm.generate(chunk_prompt, max_tokens=max_tokens,
                                     temperature=temperature, lora=lora,
                                     provider=provider, model=model)
                    results.append(r)
                except Exception as e:
                    failures += 1
                    context["log"](f"  {i+1}/{len(chunks)} 오류: {e}")
                    results.append(f"[처리 실패: {e}]")

            # 무음 실패 방지: 전부 실패면 중단, 일부 실패면 경고
            if failures == len(chunks):
                raise RuntimeError(
                    f"모든 청크({len(chunks)}개) 처리 실패 — 마지막 오류: {results[-1]}"
                )
            if failures:
                context["log"](
                    f"[WARN] {failures}/{len(chunks)}개 청크 처리 실패 — "
                    f"결과에 '[처리 실패]' 표시가 포함됩니다. 최종 문서를 확인하세요."
                )

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
                return {"출력텍스트": _fill_placeholders(combined, context)}
            elif results:
                context["progress"](1.0)
                return {"출력텍스트": _fill_placeholders(results[0], context)}

    # ── 일반 처리 (짧은 문서) ─────────────────────
    context["log"](f"처리 중... ({len(prompt)}자)")
    context["progress"](0.3)

    try:
        result = llm.generate(prompt, max_tokens=max_tokens, temperature=temperature,
                              lora=lora, provider=provider, model=model)
    except Exception as e:
        # API SDK 예외(RateLimit·인증 등)도 로그로 표면화 후 전파
        context["log"](f"AI 오류: {e}")
        raise

    context["progress"](1.0)
    context["log"](f"완료 ({len(result)}자)")

    return {"출력텍스트": _fill_placeholders(result, context)}
