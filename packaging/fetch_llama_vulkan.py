"""배포용 llama.cpp Vulkan+CPU 빌드 다운로드 → D:/models/llama_cpp/vulkan.

교사 PC는 GPU가 제각각(Intel iGPU/Arc/AMD/NVIDIA)이라 CUDA 빌드(605MB,
NVIDIA 전용)는 부적합 — Vulkan 빌드는 ~34MB, 미지원 GPU에서는 CPU 백엔드로
자동 폴백된다. 개발 장비(이 Desktop)는 계속 D:/models/llama_cpp/bin(CUDA) 사용.

사용: python packaging/fetch_llama_vulkan.py [--tag b10298]
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.request
import zipfile
from pathlib import Path

DEST = Path("D:/models/llama_cpp/vulkan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="", help="릴리스 태그(빈값=latest)")
    args = ap.parse_args()

    api = ("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
           if not args.tag else
           f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{args.tag}")
    with urllib.request.urlopen(api, timeout=30) as r:
        rel = json.load(r)
    asset = next(a for a in rel["assets"]
                 if "win-vulkan-x64" in a["name"] and a["name"].endswith(".zip"))
    print(f"{rel['tag_name']} / {asset['name']} ({asset['size']/1e6:.1f}MB)")

    with urllib.request.urlopen(asset["browser_download_url"], timeout=300) as r:
        data = r.read()
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(DEST)
    # zip 루트가 build/bin/이면 평탄화
    exe = list(DEST.rglob("llama-server.exe"))
    if exe and exe[0].parent != DEST:
        for f in exe[0].parent.iterdir():
            f.rename(DEST / f.name)
    (DEST / "VERSION.txt").write_text(rel["tag_name"], encoding="utf-8")
    print(f"OK → {DEST} ({sum(f.stat().st_size for f in DEST.glob('*'))/1e6:.0f}MB)")


if __name__ == "__main__":
    main()
