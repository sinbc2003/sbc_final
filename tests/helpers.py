# -*- coding: utf-8 -*-
"""테스트 공용 헬퍼 — 경로 이식성, 픽스처, HWP COM 서브프로세스."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH = ROOT / "data" / "fixtures" / "bench_score.hwpx"
HWP_OP = Path(__file__).resolve().parent / "hwp_op.py"


def have_bench() -> bool:
    return BENCH.exists()


def local_server_up(url: str = "http://127.0.0.1:8400") -> bool:
    try:
        import requests
        return requests.get(f"{url}/health", timeout=2).ok
    except Exception:
        return False


def make_llm(local_ctx: int = 8192):
    """로컬 gemma LLMManager (llama-server가 이미 떠 있어야 함)."""
    from engine.llm_manager import LLMManager
    return LLMManager(models_dir=ROOT / "models", config={"local_ctx": local_ctx})


def md_to_hwpx(md: str, name: str, workdir: Path) -> str:
    from nodes.md_to_hwpx.main import execute as _md2hwpx
    r = _md2hwpx({"텍스트": md}, {"output_name": name},
                 {"temp_dir": str(workdir), "progress": lambda x: None, "log": lambda m: None})
    return r.get("파일")


def inject_section_body(base_hwpx: str, out_hwpx: str, body_xml: str) -> str:
    """section0.xml 끝(</hs:sec> 앞)에 본문 XML 주입 — 본문 블랭크 테스트용."""
    with zipfile.ZipFile(base_hwpx) as zin, \
            zipfile.ZipFile(out_hwpx, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if "section0.xml" in it.filename:
                d = d.decode("utf-8").replace("</hs:sec>", body_xml + "</hs:sec>").encode("utf-8")
            zout.writestr(it, d)
    return out_hwpx


def hwp_op(*args, timeout: int = 180) -> str:
    """COM 단일 작업(서브프로세스) — open <path> | read <path>.

    같은 프로세스 2회째 EnsureDispatch가 깨지는 gencache 이슈 우회
    (핸드오프 §20). 작업당 새 프로세스 + 전용 gen_py.
    """
    r = subprocess.run([sys.executable, str(HWP_OP), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=timeout, env={**os.environ, "PYTHONUTF8": "1"})
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "")[-400:])
    return r.stdout.strip()


def read_doc_texts(path: str) -> list:
    return json.loads(hwp_op("read", path))


def workdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
