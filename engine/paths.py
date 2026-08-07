"""경로 해석 — dev(리포 실행)와 frozen(PyInstaller 배포) 공용 단일 진실.

dev(지금까지와 동일):
  ROOT     = 리포 루트 (engine/의 부모)
  DATA_DIR = ROOT/data

frozen(PyInstaller onedir + Tauri 동봉):
  ROOT     = TEACHERFLOW_HOME 환경변수 > EXE 옆에서 nodes/를 가진 폴더 탐색
             (레이아웃: resources/engine/engine.exe + resources/nodes/ → ROOT=resources)
  DATA_DIR = TEACHERFLOW_DATA 환경변수 > %LOCALAPPDATA%/TeacherFlow/data
             (설치 폴더는 쓰기 불가 전제 — 사용자 데이터는 항상 앱데이터로)

SKILLS_DIR만 예외적으로 engine 패키지 내부(__file__) 기준 — frozen에서는
PyInstaller datas('engine/skills')로 _internal/engine/skills에 동봉되므로
어느 모드든 같은 식이 유효하다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    env = os.environ.get("TEACHERFLOW_HOME")
    if env:
        return Path(env)
    if IS_FROZEN:
        exe_dir = Path(sys.executable).parent
        for cand in (exe_dir, exe_dir.parent):
            if (cand / "nodes").is_dir():
                return cand
        return exe_dir
    return Path(__file__).parent.parent


def _data_root(root: Path) -> Path:
    env = os.environ.get("TEACHERFLOW_DATA")
    if env:
        return Path(env)
    if IS_FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "TeacherFlow" / "data"
    return root / "data"


ROOT = _resource_root()
DATA_DIR = _data_root(ROOT)
NODES_DIR = ROOT / "nodes"
MODELS_DIR = ROOT / "models"
SKILLS_DIR = Path(__file__).parent / "skills"

# 배포 시드 프리셋(리소스 루트/presets) — dev에는 없으므로 자연 no-op
PRESET_SEED_DIR = ROOT / "presets"


def seed_presets() -> int:
    """번들 프리셋을 사용자 데이터로 1회 복사(이미 있으면 건드리지 않음)."""
    if not PRESET_SEED_DIR.is_dir():
        return 0
    dest = DATA_DIR / "presets"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(PRESET_SEED_DIR.glob("*.json")):
        target = dest / src.name
        if not target.exists():
            target.write_bytes(src.read_bytes())
            copied += 1
    return copied
