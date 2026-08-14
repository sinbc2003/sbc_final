"""
LLM 관리자 — llama.cpp 관리, LoRA 핫스왑, API 폴백.

Phase 1: API 호출 + 프롬프트 템플릿 기반.
Phase 2: llama.cpp 로컬 모델 통합.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .memory_manager import check_available_memory, get_memory_profile

_GONGMUN_FEWSHOT_CACHE: str | None = None


def _load_gongmun_fewshot() -> str:
    """공문 few-shot 서식 스킬(engine/skills/gongmun_fewshot.md) — API 경로용.

    LoRA를 못 붙이는 API provider에서 공문 서식을 보장하는 대체 수단
    (§31 실측: 예시 2개면 서식 동급). 파일 없으면 빈 문자열(무해 폴백).
    """
    global _GONGMUN_FEWSHOT_CACHE
    if _GONGMUN_FEWSHOT_CACHE is None:
        try:
            _GONGMUN_FEWSHOT_CACHE = (
                Path(__file__).parent / "skills" / "gongmun_fewshot.md"
            ).read_text(encoding="utf-8").strip()
        except OSError:
            _GONGMUN_FEWSHOT_CACHE = ""
    return _GONGMUN_FEWSHOT_CACHE


class LLMManager:
    """LLM 호출 관리자."""

    def __init__(self, models_dir: Path | None = None, config: dict | None = None):
        self._models_dir = models_dir
        self._config = config or {}
        self._local_process = None
        self._local_model: str | None = None

    def list_available_models(self) -> list[dict[str, str]]:
        """사용 가능한 모든 모델 목록."""
        models: list[dict[str, str]] = []

        # 로컬 GGUF 모델 스캔 (ROOT/models/base + 설정 models_dirs)
        active = (self._config.get("local_model") or "").strip().lower()
        for f in self._all_local_ggufs():
            models.append({
                "id": f"local/{f.name}",
                "name": f.name,
                "provider": "local",
                "path": str(f),
                "size_mb": str(round(f.stat().st_size / 1024 / 1024)),
                "active": bool(active and active in f.name.lower()),
            })

        # API 모델 (키 유무 표시, 전부 노출)
        has_openai = bool(self._config.get("openai_api_key"))
        has_claude = bool(self._config.get("claude_api_key"))
        has_gemini = bool(self._config.get("gemini_api_key"))

        for mid, name in [
            ("openai/gpt-4.1-nano", "GPT-4.1 Nano"),
            ("openai/gpt-4.1-mini", "GPT-4.1 Mini"),
            ("openai/gpt-4.1", "GPT-4.1"),
            ("openai/o3-mini", "o3-mini"),
        ]:
            models.append({"id": mid, "name": name, "provider": "openai", "path": "", "available": has_openai})

        for mid, name in [
            ("claude/claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
            ("claude/claude-sonnet-4-6", "Claude Sonnet 4.6"),
            ("claude/claude-opus-4-6", "Claude Opus 4.6"),
        ]:
            models.append({"id": mid, "name": name, "provider": "claude", "path": "", "available": has_claude})

        for mid, name in [
            ("gemini/gemini-2.0-flash", "Gemini 2.0 Flash"),
            ("gemini/gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("gemini/gemini-2.5-pro", "Gemini 2.5 Pro"),
        ]:
            models.append({"id": mid, "name": name, "provider": "gemini", "path": "", "available": has_gemini})

        return models

    def get_provider_info(self, provider: str = "auto") -> dict[str, str]:
        """현재 사용될 프로바이더와 모델 정보."""
        if provider == "auto":
            provider = self._pick_provider()
        info: dict[str, str] = {"provider": provider}
        if provider == "local":
            model = self._find_local_model()
            info["model"] = model.name if model else "(없음)"
        elif provider == "claude":
            info["model"] = "claude-sonnet-4-6"
        elif provider == "openai":
            info["model"] = "gpt-4.1-mini"
        elif provider == "gemini":
            info["model"] = "gemini-2.0-flash"
        return info

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        lora: str | None = None,
        provider: str = "auto",
        model: str | None = None,
        json_schema: dict | None = None,
    ) -> str:
        """텍스트 생성. provider: auto | local | claude | openai | gemini

        json_schema가 주어지면: 로컬은 llama-server 스키마 강제 디코딩,
        API는 프롬프트에 스키마 지시를 덧붙이는 소프트 강제.
        """
        # provider가 "모델ID/모델명" 형식이면 파싱
        if provider and "/" in provider:
            parts = provider.split("/", 1)
            provider = parts[0]
            if not model:
                model = parts[1]

        if provider == "auto" or not provider:
            provider = self._pick_provider()

        VALID = {"local", "claude", "openai", "gemini"}
        if provider not in VALID:
            provider = self._pick_provider()

        if provider == "local":
            return self._generate_local(prompt, max_tokens, temperature, lora, json_schema=json_schema)

        # 공문 어댑터 요청이 API provider로 흐르면(LoRA는 로컬 전용) few-shot
        # 서식 스킬로 대체한다 — 실측(§31): 예시 2개면 서식 동급이고, 어댑터를
        # 못 붙이는 API 경로에는 이것이 정답. provider별 최적 경로 분담.
        if lora and "gongmun" in str(lora).lower():
            fs = _load_gongmun_fewshot()
            if fs:
                prompt = fs + "\n\n" + prompt

        # API provider: json_schema 소프트 강제 (네이티브 스키마 기능은 미사용)
        if json_schema:
            prompt = (
                prompt
                + "\n\n반드시 다음 JSON 스키마에 맞는 JSON만 출력하라(설명·마크다운 금지):\n"
                + json.dumps(json_schema, ensure_ascii=False)
            )

        if provider == "claude":
            return self._generate_claude(prompt, max_tokens, temperature)
        elif provider == "openai":
            return self._generate_openai(prompt, max_tokens, temperature, model=model)
        elif provider == "gemini":
            return self._generate_gemini(prompt, max_tokens, temperature)
        else:
            return self._generate_openai(prompt, max_tokens, temperature, model=model)

    def generate_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        provider: str = "openai",
        model: str = "gpt-4.1",
        json_schema: dict | None = None,
    ) -> str:
        """멀티턴 대화. messages: [{role, content}, ...]

        provider/model은 "provider/model" 형태로도 전달 가능 (예: "claude/claude-sonnet-4-6").

        json_schema가 주어지면: 로컬은 llama-server가 GBNF로 강제 디코딩(못 틀림),
        API는 마지막 user 메시지에 스키마 지시를 덧붙이는 소프트 강제.
        """
        # "provider/model" 형식 파싱
        if "/" in provider:
            provider, model = provider.split("/", 1)

        # 로컬: 역할 배열 직통 + GBNF 스키마 강제
        if provider == "local":
            return self._generate_local_chat(
                messages, max_tokens=max_tokens, temperature=temperature,
                json_schema=json_schema,
            )

        # API: 스키마 소프트 강제 (원본 messages 불변 — 복사본에 지시 덧붙임)
        if json_schema:
            hint = (
                "\n\n반드시 아래 JSON 스키마에 맞는 JSON만 출력하라"
                "(설명·마크다운·코드펜스 금지):\n"
                + json.dumps(json_schema, ensure_ascii=False)
            )
            messages = [dict(m) for m in messages]
            for m in reversed(messages):
                if m.get("role") == "user":
                    m["content"] = (m.get("content") or "") + hint
                    break
            else:
                messages.append({"role": "user", "content": hint.strip()})

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=self._config.get("openai_api_key"))
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content

        if provider == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=self._config.get("claude_api_key"))
            # Claude API: system은 별도 파라미터
            system_text = ""
            chat_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_text += m["content"] + "\n"
                else:
                    chat_msgs.append({"role": m["role"], "content": m["content"]})
            kwargs: dict = {
                "model": model or "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": chat_msgs,
                "temperature": temperature,
            }
            if system_text.strip():
                kwargs["system"] = system_text.strip()
            response = client.messages.create(**kwargs)
            return response.content[0].text

        if provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=self._config.get("gemini_api_key"))
            gm = genai.GenerativeModel(model or "gemini-2.0-flash")
            # Gemini: system → first user message에 합침
            parts = []
            for m in messages:
                role = "user" if m["role"] in ("system", "user") else "model"
                parts.append({"role": role, "parts": [m["content"]]})
            response = gm.generate_content(parts, generation_config={"max_output_tokens": max_tokens, "temperature": temperature})
            return response.text

        # fallback (local은 위에서 이미 처리)
        prompt = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
        return self.generate(prompt, max_tokens=max_tokens, temperature=temperature,
                             provider=provider, json_schema=json_schema)

    def generate_chat_stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        provider: str = "openai",
        model: str = "gpt-4.1",
        json_schema: dict | None = None,
    ):
        """멀티턴 대화 스트리밍. 텍스트 청크를 yield.

        json_schema는 로컬에서만 GBNF 강제(단일 청크로 반환 — llama-server의
        문법 강제 스트리밍 대신 완성 응답을 한 번에 yield).
        """
        if "/" in provider:
            provider, model = provider.split("/", 1)

        if provider == "local":
            yield self._generate_local_chat(
                messages, max_tokens=max_tokens, temperature=temperature,
                json_schema=json_schema,
            )
            return

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=self._config.get("openai_api_key"))
            response = client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
                stream=True,
            )
            for chunk in response:
                delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                if delta:
                    yield delta

        elif provider == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=self._config.get("claude_api_key"))
            system_text = ""
            chat_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_text += m["content"] + "\n"
                else:
                    chat_msgs.append({"role": m["role"], "content": m["content"]})
            kwargs: dict = {
                "model": model or "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": chat_msgs,
                "temperature": temperature,
            }
            if system_text.strip():
                kwargs["system"] = system_text.strip()
            with client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    yield text

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=self._config.get("gemini_api_key"))
            gm = genai.GenerativeModel(model or "gemini-2.0-flash")
            parts = []
            for m in messages:
                role = "user" if m["role"] in ("system", "user") else "model"
                parts.append({"role": role, "parts": [m["content"]]})
            response = gm.generate_content(
                parts,
                generation_config={"max_output_tokens": max_tokens, "temperature": temperature},
                stream=True,
            )
            for chunk in response:
                if chunk.text:
                    yield chunk.text

        else:
            # fallback — non-streaming
            yield self.generate_chat(messages, max_tokens=max_tokens,
                                     temperature=temperature, provider=provider, model=model)

    def _pick_provider(self) -> str:
        """사용 가능한 최적 provider 선택."""
        # 배포자가 명시한 기본 provider 존중 (죽어있던 설정 배선)
        forced = self._config.get("default_provider")
        if forced and forced != "auto":
            if forced == "local" and self._find_local_model():
                return "local"
            if forced in ("claude", "openai", "gemini") and self._config.get(f"{forced}_api_key"):
                return forced
            # 지정 provider가 불가하면 아래 폴백 체인으로
        # API 키가 있으면 API 우선 (Phase 1)
        if self._config.get("claude_api_key"):
            return "claude"
        if self._config.get("openai_api_key"):
            return "openai"
        if self._config.get("gemini_api_key"):
            return "gemini"
        # 로컬 모델 확인
        if self._find_local_model():
            return "local"
        raise RuntimeError(
            "사용 가능한 LLM이 없습니다. "
            "API 키를 설정하거나 로컬 모델(models/base/*.gguf)을 설치하세요."
        )

    def _ensure_local_server(self) -> str:
        """llama-server 상태 확인, 미실행 시 자동 시작. server_url 반환."""
        import requests as _req

        host = self._config.get("local_server_host") or "127.0.0.1"
        if host == "0.0.0.0":
            host = "127.0.0.1"  # 클라이언트 접속은 루프백으로
        port = self._config.get("local_server_port") or 8400
        server_url = f"http://{host}:{port}"
        try:
            _req.get(f"{server_url}/health", timeout=2)
        except Exception:
            self._start_llama_server()
            import time
            for _ in range(30):  # 최대 30초 대기
                time.sleep(1)
                try:
                    if _req.get(f"{server_url}/health", timeout=2).ok:
                        break
                except Exception:
                    pass
            else:
                raise RuntimeError("llama-server 시작 실패 (30초 타임아웃)")

        # 서버(재사용 포함)에 프리로드된 LoRA 어댑터 유무 — per-request 스케일 적용 조건
        try:
            r = _req.get(f"{server_url}/lora-adapters", timeout=2)
            self._lora_loaded = bool(r.ok and r.json())
        except Exception:
            self._lora_loaded = False
        return server_url

    def _local_chat_completion(
        self, messages: list[dict], max_tokens: int, temperature: float,
        json_schema: dict | None = None, lora_scale: float | None = None,
    ) -> str:
        """llama-server /v1/chat/completions 호출.

        messages(역할 배열)를 직통 전달 → 모델 내장 chat 템플릿(--jinja)이
        system/user 역할을 정확히 적용. gemma-4 등 사고모델은 --reasoning off로 기동.
        lora_scale: 서버에 프리로드된 어댑터(기본 scale 0)를 이 요청만 켬(1.0).
        """
        import requests as _req

        server_url = self._ensure_local_server()

        def _post(with_schema: bool, temp: float | None = None,
                  dry_multiplier: float = 0.8):
            payload: dict = {
                "model": "local", "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature if temp is None else temp,
            }
            # gemma-4 계열은 json_schema가 사고를 각성시켜 content를 0자로 삼킨다(§41f).
            # 서버 플래그(--reasoning off/budget 0)만으로 부족해 템플릿 변수로도 끈다.
            # b10338+ 만 이 kwarg를 존중(b10298은 무시 — 무해).
            if self._config.get("local_reasoning", "off") == "off":
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            if lora_scale is not None and getattr(self, "_lora_loaded", False):
                # 항상 전체 어댑터 목록을 명시(부분 지정의 상태 잔류 방지, §41h)
                pl = [{"id": 0, "scale": lora_scale}]
                if getattr(self, "_fill_lora_loaded", False):
                    pl.append({"id": 1, "scale": 0.0})
                payload["lora"] = pl
            elif lora_scale is None and getattr(self, "_fill_lora_loaded", False)                     and getattr(self, "_fill_request", False):
                # 채움 요청: 공문 off + 채움 on
                payload["lora"] = [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
            if not (with_schema and json_schema):
                # 소형모델 자유 생성의 반복 루프 방어(E2B·E4B 실측, §41h).
                # ⚠ repeat_penalty는 프롬프트(제목) 토큰까지 억제해 주제 이탈 유발
                # (실측: 독서캠프→퇴직수당) → 시퀀스 반복만 잡는 DRY 샘플러 사용.
                # 어댑터 유무와 무관하게 자유 생성 전체에 적용(무어댑터 채팅도 루프
                # 영향권). JSON 채움·추출은 문법(maxItems·enum)이 반복을 구조적으로
                # 차단하고, 정당한 반복 구조({"id":..}열)라 DRY 제외.
                payload["dry_multiplier"] = dry_multiplier
                payload["dry_allowed_length"] = 4
            if with_schema and json_schema:
                # OpenAI 호환 스키마 강제 디코딩 (llama.cpp가 문법으로 강제)
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": json_schema},
                }
            return _req.post(f"{server_url}/v1/chat/completions", json=payload, timeout=300)

        resp = _post(with_schema=True)
        data = resp.json()

        # GBNF 샘플러 초기화 실패(일부 모델 토크나이저 비호환, 예: Phi-3.5) →
        # 스키마 지시를 프롬프트에 실어 소프트 강제로 우아하게 강등(하드 보장은 상실).
        if json_schema and (resp.status_code != 200 or data.get("error")):
            emsg = (data.get("error", {}) or {}).get("message", "") if isinstance(data.get("error"), dict) else ""
            if "grammar" in (emsg + resp.text).lower() or "sampler" in (emsg + resp.text).lower():
                import json as _json
                messages = [dict(m) for m in messages] + [{
                    "role": "user",
                    "content": ("반드시 다음 JSON 스키마에 맞는 JSON만 출력하라(설명·마크다운 금지):\n"
                                + _json.dumps(json_schema, ensure_ascii=False)),
                }]
                json_schema = None  # 재귀 방지: 이 호출은 소프트 강제로만
                resp = _post(with_schema=False)
                data = resp.json()

        # 오류 감지 (컨텍스트 초과 등)
        if resp.status_code != 200 or data.get("error"):
            err = data.get("error", {})
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
            if "context" in msg.lower() or "exceed" in msg.lower():
                # 컨텍스트 초과 → 히스토리 축소 재시도. 라이브 채팅에서 문서
                # CVD+결과로그 히스토리가 한도를 넘어 "오류"가 연발로 고정되던
                # 실측(15.7K/8K) 대응 — 실패 고정 대신 오래된 대화를 버리고 살린다.
                # (system=스킬+문서는 보존 — 자르면 액션 계약이 깨짐.)
                import logging as _logging
                sys_msgs = [m for m in messages if m.get("role") == "system"]
                rest = [m for m in messages if m.get("role") != "system"]
                for keep in (4, 1):
                    if len(rest) <= keep:
                        continue
                    messages = sys_msgs + rest[-keep:]
                    resp = _post(with_schema=bool(json_schema))
                    data = resp.json()
                    if resp.status_code == 200 and not data.get("error"):
                        _logging.getLogger(__name__).info(
                            f"컨텍스트 초과 → 히스토리 {len(rest)}→{keep}개 축소 재시도 성공")
                        break
        if resp.status_code != 200 or data.get("error"):
            err = data.get("error", {})
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
            if "context" in msg.lower() or "exceed" in msg.lower():
                model_name = self._local_model or "로컬 모델"
                raise RuntimeError(
                    f"컨텍스트 크기 초과: {msg}. "
                    f"모델({model_name})의 컨텍스트가 부족합니다. "
                    f"텍스트를 줄이거나, 설정에서 컨텍스트 크기를 늘리거나, API LLM을 사용하세요."
                )
            raise RuntimeError(f"llama-server 오류: {resp.status_code} {resp.text[:300]}")

        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()

        # finish=length는 대부분 반복 루프의 예산 소진(§41 실측: 소형모델은
        # 불확실할수록 직전 패턴을 복사하며 EOS 확률이 낮아짐) —
        # 온도·DRY를 올려 1회 루프브레이크 재시도. 소예산 호출(분류 등)은 제외.
        if choice.get("finish_reason") == "length" and max_tokens >= 256:
            try:
                retry = _post(with_schema=bool(json_schema),
                              temp=max(temperature, 0.4), dry_multiplier=1.2)
                rdata = retry.json()
                if retry.status_code == 200 and not rdata.get("error"):
                    rchoice = rdata["choices"][0]
                    rcontent = (rchoice["message"].get("content") or "").strip()
                    if rcontent and rchoice.get("finish_reason") != "length":
                        return rcontent
            except Exception:
                pass  # 재시도 실패 시 원본으로 진행
            # 재시도도 절단 → 자유 텍스트만 마지막 미완 행 제거(JSON은 원형 유지 —
            # 파서의 관대 파싱·재시도가 상류에서 처리)
            if not json_schema and "\n" in content:
                content = content.rsplit("\n", 1)[0].rstrip()

        return content

    def _generate_local(
        self, prompt: str, max_tokens: int, temperature: float, lora: str | None,
        json_schema: dict | None = None,
    ) -> str:
        """단일 프롬프트 로컬 생성. 미실행 시 llama-server 자동 시작.

        lora가 지정되면 프리로드 어댑터를 이 요청만 scale 1.0으로 활성화
        (생성 전용 — 추출·분류·라이브 채팅은 lora 미지정 = 베이스 그대로).
        """
        return self._local_chat_completion(
            [{"role": "user", "content": prompt}], max_tokens, temperature, json_schema,
            lora_scale=(1.0 if lora else None),
        )

    def _generate_local_chat(
        self, messages: list[dict], max_tokens: int, temperature: float,
        json_schema: dict | None = None,
    ) -> str:
        """멀티턴 로컬 생성 — system/user 역할을 보존해 chat 템플릿에 정확히 전달.

        (기존 fallback은 messages를 '[role] content' 문자열로 뭉개 단일 user로 보내
        스킬 시스템 프롬프트의 역할 구분이 사라졌음 — 소형 모델 품질 저하 원인.)
        """
        return self._local_chat_completion(messages, max_tokens, temperature, json_schema)

    def _find_llama_server_bin(self) -> str:
        """llama-server 실행 파일 — 설정값 > 번들 리소스 > 알려진 개발 경로 > PATH."""
        configured = self._config.get("llama_server_bin")
        if configured and Path(configured).exists():
            return configured
        from engine.paths import ROOT
        # ⚠ 순서 주의: `llama_cpp/bin/`은 2026-04 CUDA 구빌드로 --reasoning off가
        # 먹지 않아 사고 토큰이 응답을 삼킨다(content 0자) → 최후 폴백으로만 둔다.
        # 개발기 검증 빌드는 b10338 vulkan.
        for candidate in [
            str(ROOT / "llama" / "llama-server.exe"),  # 배포 번들(리소스 루트/llama)
            "C:/Users/sinbc/llama_cpp/llama-server.exe",
            "E:/sbc_lab/llama_test/b10338/llama-server.exe",
            "D:/models/llama_cpp/vulkan/llama-server.exe",
            "D:/models/llama_cpp/bin/llama-server.exe",
            "llama-server",
        ]:
            if Path(candidate).exists():
                return candidate
        return "llama-server"  # PATH 폴백

    def _local_ctx(self) -> int:
        """컨텍스트 크기 — 설정값 우선(신·구 키 모두 수용), 없으면 메모리 프로필."""
        for key in ("local_context_size", "local_ctx"):  # 구 키(local_ctx) 하위호환
            v = self._config.get(key)
            if v:  # 0/None/"" 이면 자동
                return int(v)
        return get_memory_profile().recommended_ctx

    def _start_llama_server(self):
        """llama-server를 백그라운드로 시작 — 배포 설정(모델/포트/GPU/추론)으로 조립."""
        model_path = self._find_local_model()
        if not model_path:
            raise FileNotFoundError(
                "로컬 GGUF 모델을 찾지 못했습니다. models/base/ 또는 설정 models_dirs에 두거나 "
                "settings.llm.local_model을 지정하세요."
            )
        self._local_model = Path(model_path).name  # 오류 메시지·로깅에 실제 모델명

        host = self._config.get("local_server_host") or "0.0.0.0"
        port = str(self._config.get("local_server_port") or 8400)
        ngl = str(self._config.get("local_gpu_layers", 99))
        npar = str(self._config.get("local_parallel", 1))

        # --jinja: 모델 내장 chat 템플릿(모델 무관). -np: 슬롯 수(8GB GPU는 1로 VRAM 보호).
        cmd = [
            self._find_llama_server_bin(),
            "-m", str(model_path),
            "--host", host, "--port", port,
            "-c", str(self._local_ctx()),
            "-np", npar,
            "-ngl", ngl,
            "--jinja",
        ]
        # 추론 토글(llama.cpp: on|off|auto). 사고모델(gemma-4/Qwen3)은 off로 content
        # 확보, 비사고 모델은 auto(템플릿 자동감지). ""이면 플래그 생략.
        reasoning = self._config.get("local_reasoning", "off")
        if reasoning in ("off", "on", "auto"):
            cmd += ["--reasoning", reasoning]
        # ⚠ --reasoning off 단독으로는 새 빌드(b10338)에서 사고가 완전히 안 꺼진다.
        # 검증 프로토콜과 동일하게 예산 0을 함께 준다(§42 벤치 기준).
        if reasoning == "off":
            cmd += ["--reasoning-budget", "0"]

        # LoRA 어댑터 프리로드 — 기본 스케일 0(OFF): 추출·분류·벤치는 베이스 그대로,
        # 생성 요청만 per-request lora scale=1.0으로 활성화(가이드 §5 배선).
        # ⚠ llama-server는 ANSI argv라 한글 경로가 깨짐(실측) → 어댑터는 ASCII 경로
        # (예: D:\models\loras)에 둘 것.
        lora_path = self._resolve_lora_path()
        lora_cwd = None
        if lora_path:
            # 이 llama.cpp 빌드는 --lora-scaled를 'FNAME:SCALE' 단일 인자로 받고
            # FNAME의 첫 ':'에서 분리한다 → Windows 드라이브 문자 'D:'와 충돌(콜론 2개).
            # cwd를 어댑터 폴더로 두고 콜론 없는 파일명만 넘겨 회피(실측).
            lora_arg = f"{lora_path.name}:0.0"
            # 채움 전용 어댑터(§42f v12+) — 설정 fill_lora가 있으면 id 1로 동시
            # 프리로드(둘 다 scale 0). 요청별로 생성=id0, 채움=id1만 켠다.
            fill_name = (self._config.get("fill_lora") or "").strip()
            self._fill_lora_loaded = False
            if fill_name:
                fp = lora_path.parent / (fill_name if fill_name.endswith(".gguf")
                                         else fill_name + ".gguf")
                if fp.exists():
                    lora_arg += f",{fp.name}:0.0"
                    self._fill_lora_loaded = True
            cmd += ["--lora-scaled", lora_arg]
            lora_cwd = str(lora_path.parent)

        # 기동 실패 진단을 위해 출력을 로그 파일로 남긴다(기존 DEVNULL은
        # '30초 타임아웃' 외 아무 단서도 없었음). windowed 배포에서 검은
        # 콘솔 창이 뜨지 않도록 CREATE_NO_WINDOW.
        from engine.paths import DATA_DIR
        log_f = subprocess.DEVNULL
        try:
            log_dir = DATA_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_f = open(log_dir / "llama-server.log", "ab")
            log_f.write(f"\n=== start {cmd} ===\n".encode("utf-8", "replace"))
        except OSError:
            pass
        try:
            self._local_process = subprocess.Popen(
                cmd, stdout=log_f, stderr=subprocess.STDOUT if log_f is not subprocess.DEVNULL else subprocess.DEVNULL,
                cwd=lora_cwd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            # WinError 2 원문에는 무엇을 못 찾았는지 없다 — 교사 PC 원격지원 불가 수준
            raise RuntimeError(
                f"llama-server 실행 파일을 찾을 수 없습니다: {cmd[0]} "
                "(설정 llm.llama_server_bin 또는 번들 llama/ 폴더 확인)"
            )
        if log_f is not subprocess.DEVNULL:
            log_f.close()  # 자식이 핸들 상속 — 부모 쪽은 닫아도 기록 지속

    def _generate_claude(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Claude API 호출."""
        import anthropic

        client = anthropic.Anthropic(
            api_key=self._config.get("claude_api_key")
        )
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return message.content[0].text

    def _generate_openai(
        self, prompt: str, max_tokens: int, temperature: float,
        *, model: str | None = None,
    ) -> str:
        """OpenAI API 호출."""
        from openai import OpenAI

        client = OpenAI(api_key=self._config.get("openai_api_key"))
        response = client.chat.completions.create(
            model=model or "gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content

    def _generate_gemini(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Gemini API 호출."""
        import google.generativeai as genai

        genai.configure(api_key=self._config.get("gemini_api_key"))
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        return response.text

    def _search_dirs(self) -> list[Path]:
        """GGUF 탐색 경로 — ROOT/models/base + 설정 models_dirs + 레거시 기본값."""
        dirs: list[Path] = []
        if self._models_dir:
            dirs.append(self._models_dir / "base")
        for d in (self._config.get("models_dirs") or []):
            dirs.append(Path(d))
        # 레거시 기본값(이 장비 배포 경로) — 설정이 없을 때만 유효
        dirs.append(Path("C:/Users/sinbc/models/teacherflow"))
        dirs.append(Path("D:/models/teacherflow"))
        return dirs

    def _all_local_ggufs(self) -> list[Path]:
        seen: set = set()
        out: list[Path] = []
        for d in self._search_dirs():
            if not d.exists():
                continue
            for f in sorted(d.glob("*.gguf")):
                if f.name not in seen:
                    seen.add(f.name)
                    out.append(f)
        return out

    def _find_local_model(self) -> Path | None:
        """구동할 로컬 GGUF 결정.

        우선순위: 설정 local_model(파일명 부분일치) > 메모리 프로필 quant 매칭 >
        단일 GGUF면 그것 > 여러 개면 첫 번째(경고). '어느 모델' knob이 살아있게 배선.
        """
        ggufs = self._all_local_ggufs()
        if not ggufs:
            return None
        wanted = (self._config.get("local_model") or "").strip().lower()
        if wanted:
            for f in ggufs:
                if wanted in f.name.lower():
                    return f
            # 명시했는데 없으면 자동선택으로 폴백(경고는 호출부 로깅에 위임)
        return self._find_model(get_memory_profile().recommended_quant)

    def _find_model(self, quant: str) -> Path | None:
        """quant 부분일치로 GGUF 찾기 (없으면 첫 번째). 자동선택 폴백용."""
        q_lower = quant.lower()
        ggufs = self._all_local_ggufs()
        for f in ggufs:
            if q_lower in f.name.lower():
                return f
        return ggufs[0] if ggufs else None

    def _lora_dirs(self) -> list[Path]:
        """LoRA 어댑터 탐색 경로 — 설정 loras_dirs > ASCII 기본(D:) > 리포 models/loras."""
        dirs = [Path(d) for d in (self._config.get("loras_dirs") or [])]
        dirs.append(Path("D:/models/loras"))  # ASCII 경로(한글 경로 argv 깨짐 회피)
        if self._models_dir:
            dirs.append(self._models_dir / "loras")
        return dirs

    def list_loras(self) -> list[dict[str, Any]]:
        """설치된 LoRA 어댑터 목록. UI 드롭다운·안내용.

        노드의 lora 파라미터가 자유 텍스트라 오타 시 조용히 베이스로 실행되던
        문제 때문에 만들었다. active = 설정 기본 어댑터(local_lora)와 일치하는 것.
        """
        active = (self._config.get("local_lora") or "").strip().lower()
        # 채움 어댑터(fill_lora)는 사용자가 고르는 값이 아니라 채움 요청에서 코드가
        # 자동으로 켜는 id1이다(§42f). UI에 전혀 안 보여 "적용되고 있는지" 확인할
        # 길이 없었으므로 role/fill_active로 함께 알린다.
        fill = (self._config.get("fill_lora") or "").strip().lower()
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for d in self._lora_dirs():
            if not d.exists():
                continue
            for f in sorted(d.rglob("*.gguf")):
                key = str(f.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    size_mb = round(f.stat().st_size / 1024 / 1024)
                except OSError:
                    size_mb = 0
                stem = f.stem.lower()
                is_gen = bool(active and (active in stem or active in str(f).lower()))
                is_fill = bool(fill and (fill in stem or fill in str(f).lower()))
                result.append({
                    "name": f.stem,
                    "file": f.name,
                    "path": str(f),
                    "size_mb": size_mb,
                    "active": is_gen,
                    "fill_active": is_fill,
                    # 생성=공문 어댑터(요청별 scale 1.0), 채움=표 채우기 전용
                    "role": "채움" if is_fill else ("생성" if is_gen else ""),
                })
        return result

    def _find_lora(self, lora_name: str) -> Path | None:
        """이름 부분일치로 LoRA 어댑터(gguf) 찾기."""
        for d in self._lora_dirs():
            if not d.exists():
                continue
            for f in d.rglob("*.gguf"):
                if lora_name in f.stem:
                    return f
        return None

    def _resolve_lora_path(self) -> Path | None:
        """설정 local_lora(경로 또는 이름) → 서버 프리로드할 어댑터 파일."""
        name = (self._config.get("local_lora") or "").strip()
        if not name:
            return None
        p = Path(name)
        if p.suffix.lower() == ".gguf" and p.exists():
            return p
        return self._find_lora(name)

    def cleanup(self):
        """리소스 정리."""
        if self._local_process:
            self._local_process.terminate()
            self._local_process = None
