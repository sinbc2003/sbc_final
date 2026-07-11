"""
TeacherFlow 설정 관리.

설정은 data/settings.json에 저장.
API 키는 별도 data/.secrets.json에 저장 (gitignore 대상).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS = {
    "general": {
        "language": "ko",
        "theme": "light",
        "auto_save_interval": 30,
        "check_updates": True,
        "update_channel": "stable",  # stable | beta
        "output_dir": "",  # 출력 파일 저장 경로 (빈값 = 바탕화면)
    },
    "llm": {
        "default_provider": "auto",  # auto | local | claude | openai | gemini
        "local_model": "",  # GGUF 파일명(부분일치 가능). 빈값이면 quant 자동 선택
        "local_context_size": 0,  # 0 = 자동(메모리 프로필)
        "default_temperature": 0.7,
        "default_max_tokens": 2048,
        # ── 로컬 런타임(llama-server) 배포 설정 — 다른 GGUF/장비로 일반화 ──
        "models_dirs": [],           # 추가 GGUF 탐색 경로(ROOT/models/base는 항상 포함)
        "llama_server_bin": "",      # llama-server 실행 파일 경로(빈값이면 자동 탐색)
        "local_server_host": "127.0.0.1",
        "local_server_port": 8400,
        "local_gpu_layers": 99,      # -ngl (전체 오프로드=99, CPU-only는 0)
        "local_reasoning": "off",    # llama.cpp 추론: off|on|auto | ""(플래그 생략). 비사고 모델은 auto
        "local_parallel": 1,         # -np (8GB급 GPU는 1 권장)
    },
    "rag": {
        "enabled": False,
        "collection_name": "teacherflow",
        "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "sync_enabled": False,
        "sync_url": "",  # 공유 컬렉션 동기화 URL
    },
    "live": {
        "plan_model": "auto",       # 기획 모델: auto | claude | openai | gemini
        "execute_model": "openai",   # 실행 모델: openai | gemini | local
        "plan_temperature": 0.7,
        "execute_temperature": 0.3,  # 낮을수록 기획서 충실
        "auto_connect": True,        # Excel/PPT 자동 COM 연결
    },
    "nodes": {
        "marketplace_url": "https://nodes.teacherflow.com/api",
        "auto_update_nodes": True,
        "installed_extra": [],  # 마켓플레이스에서 설치한 추가 노드 ID 목록
    },
}

# API 키 기본값 (별도 파일)
DEFAULT_SECRETS = {
    "claude_api_key": "",
    "openai_api_key": "",
    "gemini_api_key": "",
    "mathpix_app_id": "",
    "mathpix_app_key": "",
}


class SettingsManager:
    """설정 파일 관리자."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._settings_path = data_dir / "settings.json"
        self._secrets_path = data_dir / ".secrets.json"
        self._settings: dict[str, Any] = {}
        self._secrets: dict[str, str] = {}
        self._load()

    def _load(self):
        """설정 파일 로드. 없으면 기본값 생성."""
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # settings.json
        if self._settings_path.exists():
            try:
                self._settings = json.loads(self._settings_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                self._settings = {}
        # 기본값 병합 (새로운 키가 추가됐을 때)
        self._settings = _deep_merge(DEFAULT_SETTINGS, self._settings)

        # .secrets.json
        if self._secrets_path.exists():
            try:
                self._secrets = json.loads(self._secrets_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                self._secrets = {}
        for k, v in DEFAULT_SECRETS.items():
            self._secrets.setdefault(k, v)

    def _save_settings(self):
        self._settings_path.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2), "utf-8"
        )

    def _save_secrets(self):
        self._secrets_path.write_text(
            json.dumps(self._secrets, ensure_ascii=False, indent=2), "utf-8"
        )

    # ── 공개 API ──────────────────────────────────────

    def get_all(self) -> dict[str, Any]:
        """모든 설정 반환 (API 키는 마스킹)."""
        result = json.loads(json.dumps(self._settings))
        result["api_keys"] = {}
        for k, v in self._secrets.items():
            if v:
                # 마스킹: 앞 4자 + ***
                result["api_keys"][k] = v[:4] + "***" + v[-4:] if len(v) > 8 else "****"
            else:
                result["api_keys"][k] = ""
        return result

    def update(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        """특정 섹션 업데이트."""
        if section == "api_keys":
            # API 키는 secrets에 저장
            for k, v in values.items():
                if k in self._secrets and v and "***" not in v:
                    self._secrets[k] = v
            self._save_secrets()
        elif section in self._settings:
            self._settings[section].update(values)
            self._save_settings()
        else:
            raise KeyError(f"Unknown section: {section}")
        return self.get_all()

    def get_secrets_raw(self) -> dict[str, str]:
        """API 키 원본 (엔진 내부용, API 노출 안 됨)."""
        return dict(self._secrets)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """특정 설정값 가져오기."""
        return self._settings.get(section, {}).get(key, default)

    def get_llm_config(self) -> dict[str, Any]:
        """LLM Manager에 전달할 설정."""
        return {
            **self._settings.get("llm", {}),
            **self._secrets,
        }


def _deep_merge(base: dict, override: dict) -> dict:
    """base에 override를 깊은 병합."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
