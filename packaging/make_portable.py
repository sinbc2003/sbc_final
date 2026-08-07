"""포터블(USB) 배포 조립 — 압축 해제 후 TeacherFlow.exe 더블클릭이 전부.

NSIS 설치본(92MB)은 모델 미포함(단일 파일 2GB 제약) — 포터블은 GGUF까지
전부 담아 인터넷 차단 학교에서도 완결된다(§9 결정).

레이아웃(= tauri release 리소스 구조 그대로, resource_dir=EXE 옆):
  TeacherFlow-portable/
    TeacherFlow.exe
    engine/  nodes/  llama/  presets/  models/  default_settings.json

사용: python packaging/make_portable.py [--zip]
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path


def _rmtree_retry(path: Path, attempts: int = 5, delay: float = 2.0) -> bool:
    """AV가 하위 핸들을 잡아 rmtree가 간헐 실패(stage_bundle과 동일 실측)."""
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except PermissionError:
            if i == attempts - 1:
                return False
            time.sleep(delay)
    return False

REPO = Path(__file__).resolve().parent.parent
RELEASE = Path("E:/sbc_lab/tf_build/cargo_target/release")
BUNDLE = REPO / "packaging" / "bundle"
OUT = Path("E:/sbc_lab/tf_build/TeacherFlow-portable")

RESOURCES = ["engine", "nodes", "llama", "presets", "default_settings.json"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="store_true", help="폴더를 zip으로도 묶기")
    args = ap.parse_args()

    exe = RELEASE / "teacherflow.exe"
    if not exe.exists():
        raise SystemExit(f"먼저 tauri build 필요: {exe} 없음")

    if OUT.exists() and not _rmtree_retry(OUT):
        print("[WARN] 기존 포터블 삭제 실패 — 덮어쓰기로 진행(구 어댑터는 아래서 정리)")
    OUT.mkdir(parents=True, exist_ok=True)

    shutil.copy2(exe, OUT / "TeacherFlow.exe")
    for name in RESOURCES:
        src = RELEASE / name
        if not src.exists():
            print(f"[WARN] 리소스 없음: {src}")
            continue
        if src.is_dir():
            shutil.copytree(src, OUT / name, dirs_exist_ok=True)
        else:
            shutil.copy2(src, OUT / name)

    models = BUNDLE / "models"
    if models.exists():
        print("models 복사(GGUF 수 GB — 시간 소요)...")
        shutil.copytree(models, OUT / "models", dirs_exist_ok=True)
        # 덮어쓰기 경로에서 구버전 어댑터 잔존 방지 — 번들에 없는 gguf 제거
        bundle_loras = {f.name for f in (models / "loras").glob("*.gguf")}
        for f in (OUT / "models" / "loras").glob("*.gguf"):
            if f.name not in bundle_loras:
                f.unlink()
                print(f"구 어댑터 제거: {f.name}")
    else:
        print("[WARN] packaging/bundle/models 없음 — stage_bundle.py --full 먼저")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"OK → {OUT} ({total/1e9:.2f}GB)")

    if args.zip:
        print("zip 생성 중...")
        shutil.make_archive(str(OUT), "zip", OUT.parent, OUT.name)
        print(f"OK → {OUT}.zip")


if __name__ == "__main__":
    main()
