# -*- coding: utf-8 -*-
"""hwp → hwpx 일괄 변환 (COM 배치) — §32 잔여 자동화, v9 데이터 체인용.

단일 Hwp 인스턴스로 Open→SaveAs("HWPX")→반복. §19 처방(Hwp.exe 선실행 후
COM)과 §20(프로세스당 EnsureDispatch 1회)을 따른다. 파일별 예외 격리,
연속 실패 시 인스턴스 재생성. 멱등(기존 출력 스킵).

실행: python scripts/lora/convert_hwp_batch.py --src D:\lora_data\form_v9\raw --out D:\lora_data\form_v9\hwpx
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _launch_hwp_exe():
    """한/글 프로세스 선실행 — 콜드 COM 기동 실패(CO_E_SERVER_EXEC_FAILURE) 회피."""
    import psutil
    if any(p.name().lower() == "hwp.exe" for p in psutil.process_iter(["name"])):
        return
    candidates = [
        r"C:\Program Files (x86)\Hnc\Office 2024\HOffice130\Bin\Hwp.exe",
        r"C:\Program Files (x86)\Hnc\Office 2020\HOffice110\Bin\Hwp.exe",
    ]
    import glob as _g
    for pat in (r"C:\Program Files (x86)\Hnc\**\Hwp.exe", r"C:\Program Files\Hnc\**\Hwp.exe"):
        candidates += _g.glob(pat, recursive=True)
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe])
            # 워킹셋이 자리 잡을 때까지 대기 (§19: WS>100MB)
            for _ in range(40):
                time.sleep(1)
                for p in psutil.process_iter(["name", "memory_info"]):
                    try:
                        if p.info["name"].lower() == "hwp.exe" and \
                                p.info["memory_info"].rss > 100 * 1024 * 1024:
                            return
                    except Exception:
                        pass
            return


def _new_hwp():
    from pyhwpx import Hwp
    return Hwp(visible=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [p for p in sorted(src.glob("*.hwp"))
            if not (out / (p.stem + ".hwpx")).exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"변환 대상 {len(todo)}건", flush=True)
    if not todo:
        return 0

    _launch_hwp_exe()
    hwp = _new_hwp()
    ok = fail = streak = 0
    for i, p in enumerate(todo):
        dst = out / (p.stem + ".hwpx")
        try:
            hwp.Open(str(p.resolve()))
            hwp.SaveAs(str(dst.resolve()), "HWPX")
            if dst.exists() and dst.stat().st_size > 1000:
                ok += 1
                streak = 0
            else:
                fail += 1
                streak += 1
        except Exception as e:
            fail += 1
            streak += 1
            print(f"  실패 {p.name[:50]}: {str(e)[:60]}", flush=True)
        if streak >= 5:
            print("연속 실패 5 — Hwp 인스턴스 재생성", flush=True)
            try:
                hwp.quit()
            except Exception:
                pass
            time.sleep(3)
            hwp = _new_hwp()
            streak = 0
        if (i + 1) % 25 == 0:
            print(f"진행 {i+1}/{len(todo)} (성공 {ok} / 실패 {fail})", flush=True)
    try:
        hwp.quit()
    except Exception:
        pass
    print(f"완료: 성공 {ok} / 실패 {fail} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
