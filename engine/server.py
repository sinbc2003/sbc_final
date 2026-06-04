"""
TeacherFlow 엔진 API 서버.

사용법:
  python -m engine.server
  uvicorn engine.server:app --port 8406 --reload
"""

from __future__ import annotations
import logging
import os
from pathlib import Path

# 엔진 로거 레벨 설정 (DEBUG까지 출력)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("engine").setLevel(logging.DEBUG)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine import deps

# ── 앱 생성 ──

app = FastAPI(title="TeacherFlow Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 초기화 ──

@app.on_event("startup")
async def startup():
    deps.initialize()


# ── 라우터 등록 ──

from engine.routes import system, workflows, execution, files, settings, chat, rag, live, hwp, form_assist

for router_module in [system, workflows, execution, files, settings, chat, rag, live, hwp, form_assist]:
    app.include_router(router_module.router)


# ── 엔트리포인트 ──

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("ENGINE_PORT", "8406"))
    uvicorn.run("engine.server:app", host="127.0.0.1", port=port, reload=True,
                reload_dirs=[str(Path(__file__).parent)])
