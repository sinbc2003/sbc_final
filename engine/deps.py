"""
공유 의존성 모듈 — 싱글턴 인스턴스, COM 스레드 풀, 헬퍼 함수.

모든 라우터가 이 모듈에서 공유 객체를 임포트한다.
"""

from __future__ import annotations

import asyncio
import os
import concurrent.futures as _cf
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent

# ── 싱글턴 인스턴스 ──

from engine.loader import NodeRegistry
from engine.llm_manager import LLMManager
from engine.storage import DataStore
from engine.settings import SettingsManager
from engine.node_marketplace import NodeMarketplace
from engine.vector_store import VectorStore

registry = NodeRegistry()
llm_manager: LLMManager | None = None
store = DataStore(ROOT / "data")
settings_mgr = SettingsManager(ROOT / "data")
marketplace = NodeMarketplace(
    nodes_dir=ROOT / "nodes",
    data_dir=ROOT / "data",
    registry_url=settings_mgr.get("nodes", "marketplace_url", ""),
)
vector_store: VectorStore | None = None

UPLOADS_DIR = ROOT / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ── COM 단일 스레드 풀 ──

_com_pool = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="com")


async def run_on_com(func, *args):
    """COM 전용 스레드에서 함수 실행 (async)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_com_pool, func, *args)


# ── HWP / Live 싱글턴 ──

_live = None
_hwp_ctrl_instance = None


def get_live():
    global _live
    if _live is None:
        from engine.live_controller import LiveController
        _live = LiveController()
    return _live


def get_hwp():
    global _hwp_ctrl_instance
    if _hwp_ctrl_instance is None:
        from engine.live_controller import _get_hwp_ctrl
        _hwp_ctrl_instance = _get_hwp_ctrl()
    return _hwp_ctrl_instance


def create_fresh_hwp():
    """Fresh Hwp() 인스턴스 생성 (makepy 오류 시 gencache 초기화 후 재시도)."""
    import pythoncom
    pythoncom.CoInitialize()
    try:
        from pyhwpx import Hwp
        return Hwp(visible=True)
    except Exception:
        try:
            import win32com.client, shutil
            gen_path = win32com.client.gencache.GetGeneratePath()
            if gen_path and os.path.exists(gen_path):
                shutil.rmtree(gen_path, ignore_errors=True)
                os.makedirs(gen_path, exist_ok=True)
        except Exception:
            pass
        from pyhwpx import Hwp
        return Hwp(visible=True)


# ── 초기화 ──

def initialize():
    """앱 시작 시 호출. 레지스트리 로드, LLM 매니저 초기화."""
    global llm_manager, vector_store

    # win32com gencache 초기화
    try:
        import win32com.client, shutil
        gen_path = win32com.client.gencache.GetGeneratePath()
        if gen_path and os.path.exists(gen_path):
            shutil.rmtree(gen_path, ignore_errors=True)
            os.makedirs(gen_path, exist_ok=True)
            print("[Engine] win32com gencache 초기화 완료")
    except Exception:
        pass

    # pandas 순환 import 방지: 노드 로드 전 미리 import
    try:
        import pandas  # noqa: F401
    except ImportError:
        pass

    loaded = registry.load_all(ROOT / "nodes")

    # LLM config
    llm_config = settings_mgr.get_llm_config()
    for k, env in [("claude_api_key", "ANTHROPIC_API_KEY"), ("openai_api_key", "OPENAI_API_KEY"), ("gemini_api_key", "GEMINI_API_KEY")]:
        if not llm_config.get(k):
            llm_config[k] = os.environ.get(env, "")
    llm_manager = LLMManager(models_dir=ROOT / "models", config=llm_config)

    # RAG 벡터스토어
    rag_settings = settings_mgr.get_all().get("rag", {})
    raw_rag = {}
    for k in ("enabled", "collection_name", "embedding_model", "chunk_size", "chunk_overlap", "sync_enabled", "sync_url"):
        raw_rag[k] = settings_mgr.get("rag", k, rag_settings.get(k))
    vector_store = VectorStore(data_dir=ROOT / "data", settings=raw_rag)

    stats = store.get_stats()
    print(f"[Engine] 노드 {len(loaded)}개, 워크플로우 {stats['workflow_count']}개, 히스토리 {stats['history_count']}개")


def reinit_llm():
    """설정 변경 후 LLM 매니저 재초기화."""
    global llm_manager
    llm_config = settings_mgr.get_llm_config()
    for k, env in [("claude_api_key", "ANTHROPIC_API_KEY"), ("openai_api_key", "OPENAI_API_KEY"), ("gemini_api_key", "GEMINI_API_KEY")]:
        if not llm_config.get(k):
            llm_config[k] = os.environ.get(env, "")
    llm_manager = LLMManager(models_dir=ROOT / "models", config=llm_config)
