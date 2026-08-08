"""배포 번들 스테이징 — tauri.conf.json resources가 참조하는 폴더를 조립한다.

산출(리포/packaging/bundle/):
  nodes/                  리포 nodes/ 클린 사본(__pycache__ 제외)
  llama/llama-server.exe  Vulkan+CPU 범용 빌드(교사 PC — CUDA 금지, 605MB→~90MB)
  models/base/*.gguf      번들 모델(기본 E2B Q4_K_M)
  models/loras/*.gguf     공문 LoRA(모델 패밀리 일치본만)
  default_settings.json   첫 실행 시드(engine/paths.seed_settings)

사용:
  python packaging/stage_bundle.py            # nodes+설정만(가벼움)
  python packaging/stage_bundle.py --full     # 모델·llama까지(설치본/USB용)

모델 동봉 없이 NSIS를 만들면 로컬 LLM은 '모델 팩' 복사 전까지 비활성 —
NSIS 단일 파일 2GB 제약 때문에 GGUF는 포터블 ZIP/USB 경로가 기본이다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def _rmtree_retry(path: Path, attempts: int = 5, delay: float = 2.0) -> None:
    """AV 실시간 검사(AhnLab)가 방금 접근한 폴더 핸들을 잠깐 잡아
    rmtree가 간헐 WinError 5로 죽는다(실측) — 짧은 백오프 재시도."""
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO / "packaging" / "bundle"

# 이 장비의 소스 위치 (다른 장비는 인자/수정으로)
LLAMA_VULKAN_DIR = Path("D:/models/llama_cpp/vulkan")   # fetch_llama_vulkan.py가 채움
GGUF_BASE = Path("D:/models/teacherflow/e2b/gemma-4-E2B-it-Q4_K_M.gguf")
LORA = Path("D:/models/loras/gongmun_g4e2b_v9.gguf")

DEFAULT_SETTINGS = {
    "llm": {
        "default_provider": "local",
        "local_model": "E2B",              # 부분일치 — 번들 GGUF
        # v9 = 멀티태스크(공문+채움 3배)·관련일자/실명 placeholder (§35b A/B 채택)
        "local_lora": "gongmun_g4e2b_v9",
        "local_server_host": "127.0.0.1",
        "local_gpu_layers": 99,
        "local_parallel": 1,
        "local_reasoning": "off",
    },
    "general": {
        "check_updates": False,            # 차단망 — 조용한 타임아웃 방지
        "school_name": "",                 # 설치 후 설정에서 입력 — {기관명} 치환(v4)
    },
    "nodes": {
        "auto_update_nodes": False,
    },
}


def stage_nodes() -> int:
    dest = BUNDLE / "nodes"
    if dest.exists():
        try:
            _rmtree_retry(dest)
        except PermissionError:
            # 외부 프로세스가 하위 폴더 핸들을 오래 잡는 경우(실측:
            # column_mapping) — 삭제 포기하고 덮어쓰기. 노드는 파일 삭제가
            # 드물어 의미상 안전하나, 노드를 '지운' 배포가 필요하면 잠금
            # 프로세스 종료 후 재실행할 것.
            print("[WARN] nodes 삭제 실패 — 덮어쓰기로 진행")
    shutil.copytree(
        REPO / "nodes", dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )
    return len([d for d in dest.iterdir() if d.is_dir()])


def stage_settings() -> None:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    (BUNDLE / "default_settings.json").write_text(
        json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def stage_llama() -> bool:
    if not (LLAMA_VULKAN_DIR / "llama-server.exe").exists():
        print(f"[SKIP] Vulkan llama-server 없음: {LLAMA_VULKAN_DIR} "
              "(packaging/fetch_llama_vulkan.py 먼저 실행)")
        return False
    dest = BUNDLE / "llama"
    if dest.exists():
        try:
            _rmtree_retry(dest)
        except PermissionError:
            print("[WARN] llama 삭제 실패 — 덮어쓰기로 진행")
    shutil.copytree(LLAMA_VULKAN_DIR, dest, dirs_exist_ok=True)
    return True


def stage_models() -> bool:
    ok = True
    base = BUNDLE / "models" / "base"
    loras = BUNDLE / "models" / "loras"
    base.mkdir(parents=True, exist_ok=True)
    loras.mkdir(parents=True, exist_ok=True)
    for src, dest_dir in [(GGUF_BASE, base), (LORA, loras)]:
        if not src.exists():
            print(f"[SKIP] 없음: {src}")
            ok = False
            continue
        dest = dest_dir / src.name
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            print(f"copy {src.name} ({src.stat().st_size/1e9:.2f}GB)...")
            shutil.copy2(src, dest)
    # 어댑터 버전 교체 시 구버전 잔존 방지 — 지정본 외 gguf 제거
    # (bundle/은 누적 디렉토리라 v8→v9 교체 때 v8이 NSIS까지 실려간 실측)
    for f in loras.glob("*.gguf"):
        if f.name != LORA.name:
            f.unlink()
            print(f"구 어댑터 제거: {f.name}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="모델·llama까지 스테이징")
    args = ap.parse_args()

    stage_settings()
    n = stage_nodes()
    print(f"nodes {n}개, default_settings.json OK")
    if args.full:
        l = stage_llama()
        m = stage_models()
        print(f"llama: {'OK' if l else 'SKIP'}, models: {'OK' if m else '일부 SKIP'}")


if __name__ == "__main__":
    sys.exit(main())
