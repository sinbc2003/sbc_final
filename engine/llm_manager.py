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

        # 로컬 GGUF 모델 스캔
        search_dirs: list[Path] = []
        if self._models_dir:
            search_dirs.append(self._models_dir / "base")
        search_dirs.append(Path("C:/Users/sinbc/models/teacherflow"))
        search_dirs.append(Path("D:/models/teacherflow"))
        for d in search_dirs:
            if not d.exists():
                continue
            for f in d.glob("*.gguf"):
                models.append({
                    "id": f"local/{f.name}",
                    "name": f.name,
                    "provider": "local",
                    "path": str(f),
                    "size_mb": str(round(f.stat().st_size / 1024 / 1024)),
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
            model = self._find_model("q4")
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
    ) -> str:
        """멀티턴 대화. messages: [{role, content}, ...]

        provider/model은 "provider/model" 형태로도 전달 가능 (예: "claude/claude-sonnet-4-6").
        """
        # "provider/model" 형식 파싱
        if "/" in provider:
            provider, model = provider.split("/", 1)

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

        if provider == "local":
            # messages 역할 배열 직통 → 내장 chat 템플릿이 system/user 정확 적용
            return self._generate_local_chat(messages, max_tokens=max_tokens, temperature=temperature)

        # fallback
        prompt = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
        return self.generate(prompt, max_tokens=max_tokens, temperature=temperature, provider=provider)

    def generate_chat_stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        provider: str = "openai",
        model: str = "gpt-4.1",
    ):
        """멀티턴 대화 스트리밍. 텍스트 청크를 yield."""
        if "/" in provider:
            provider, model = provider.split("/", 1)

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
        # API 키가 있으면 API 우선 (Phase 1)
        if self._config.get("claude_api_key"):
            return "claude"
        if self._config.get("openai_api_key"):
            return "openai"
        if self._config.get("gemini_api_key"):
            return "gemini"
        # 로컬 모델 확인
        model = self._find_model("q4")
        if model:
            return "local"
        raise RuntimeError(
            "사용 가능한 LLM이 없습니다. "
            "API 키를 설정하거나 로컬 모델(models/base/*.gguf)을 설치하세요."
        )

    def _ensure_local_server(self) -> str:
        """llama-server 상태 확인, 미실행 시 자동 시작. server_url 반환."""
        import requests as _req

        server_url = "http://127.0.0.1:8400"
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
        return server_url

    def _local_chat_completion(
        self, messages: list[dict], max_tokens: int, temperature: float,
        json_schema: dict | None = None,
    ) -> str:
        """llama-server /v1/chat/completions 호출.

        messages(역할 배열)를 직통 전달 → 모델 내장 chat 템플릿(--jinja)이
        system/user 역할을 정확히 적용. gemma-4 등 사고모델은 --reasoning off로 기동.
        """
        import requests as _req

        server_url = self._ensure_local_server()
        payload: dict = {
            "model": "local",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema:
            # OpenAI 호환 스키마 강제 디코딩 (llama.cpp가 문법으로 강제)
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema},
            }
        resp = _req.post(f"{server_url}/v1/chat/completions", json=payload, timeout=300)
        data = resp.json()

        # 오류 감지 (컨텍스트 초과 등)
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

        return (data["choices"][0]["message"].get("content") or "").strip()

    def _generate_local(
        self, prompt: str, max_tokens: int, temperature: float, lora: str | None,
        json_schema: dict | None = None,
    ) -> str:
        """단일 프롬프트 로컬 생성. 미실행 시 llama-server 자동 시작."""
        return self._local_chat_completion(
            [{"role": "user", "content": prompt}], max_tokens, temperature, json_schema,
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

    def _start_llama_server(self):
        """llama-server를 백그라운드로 시작."""
        profile = get_memory_profile()
        model_path = self._find_model(profile.recommended_quant)
        if not model_path:
            raise FileNotFoundError(
                f"로컬 모델 없음 (권장: {profile.recommended_quant})"
            )

        server_bin = "llama-server"
        for candidate in [
            "C:/Users/sinbc/llama_cpp/llama-server.exe",
            "D:/models/llama_cpp/bin/llama-server.exe",
            "llama-server",
        ]:
            if Path(candidate).exists():
                server_bin = candidate
                break

        # 컨텍스트 크기: 설정값(local_ctx) 우선, 없으면 메모리 프로필 권장값
        ctx = profile.recommended_ctx
        if self._config.get("local_ctx"):
            ctx = int(self._config["local_ctx"])

        # 0.0.0.0 바인딩: goe 요약기(Mac1 cmd센터)가 Tailscale로 같은 서버를 공유.
        # --jinja: 모델 내장 chat 템플릿 사용, --reasoning off: 사고모델 기본 비활성(속도).
        # -np 1: 슬롯 1개. Arc 등 8GB급 GPU에서 다중 슬롯 KV캐시가 VRAM을 초과해
        # Vulkan device-lost로 죽는 것을 방지 (구형 노트북 배포 안정성).
        cmd = [
            server_bin,
            "-m", str(model_path),
            "--host", "0.0.0.0", "--port", "8400",
            "-c", str(ctx),
            "-np", "1",
            "-ngl", "99",
            "--jinja", "--reasoning", "off",
        ]
        self._local_process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

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

    def _find_model(self, quant: str) -> Path | None:
        """models/base/ 및 추가 경로에서 모델 찾기."""
        search_dirs: list[Path] = []
        if self._models_dir:
            search_dirs.append(self._models_dir / "base")
        # 사용자 홈 모델 경로 + D드라이브 모델 경로 (C: 공간 부족 대비)
        search_dirs.append(Path("C:/Users/sinbc/models/teacherflow"))
        search_dirs.append(Path("D:/models/teacherflow"))

        q_lower = quant.lower()
        all_ggufs: list[Path] = []
        for d in search_dirs:
            if not d.exists():
                continue
            for f in d.glob("*.gguf"):
                if q_lower in f.name.lower():
                    return f
                all_ggufs.append(f)
        return all_ggufs[0] if all_ggufs else None

    def _find_lora(self, lora_name: str) -> Path | None:
        """models/loras/에서 LoRA 어댑터 찾기."""
        if not self._models_dir:
            return None
        loras_dir = self._models_dir / "loras"
        if not loras_dir.exists():
            return None
        for f in loras_dir.rglob("*.gguf"):
            if lora_name in f.stem:
                return f
        return None

    def cleanup(self):
        """리소스 정리."""
        if self._local_process:
            self._local_process.terminate()
            self._local_process = None
