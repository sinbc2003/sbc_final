# -*- coding: utf-8 -*-
"""2단계: manifest → md 변환 (D:\\lora_data\\md\\{idx:05d}.md).

- odt: pypandoc(gfm)
- hwpx/hwp: nodes.hwpx_to_md / nodes.hwp_to_md (kordoc → 내장 폴백)
재실행 시 기존 md는 건너뜀(멱등). 결과는 convert_status.jsonl.
"""
from __future__ import annotations

import re
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import CONVERT_STATUS, MANIFEST, MD_DIR, read_jsonl, write_jsonl

sys.stdout.reconfigure(encoding="utf-8")

_CTX = {"progress": lambda x: None, "log": lambda m: None}
_SPAN_RE = re.compile(r"</?span[^>]*>")


def _pandoc_path() -> str:
    import pypandoc
    return pypandoc.get_pandoc_path()


def _odt_to_md(path: str) -> str:
    # pypandoc.convert_file은 경로를 glob으로 해석 → 파일명의 [ ]가 깨짐.
    # pandoc 직접 호출로 우회.
    r = subprocess.run(
        [_pandoc_path(), path, "-f", "odt", "-t", "gfm", "--wrap=none"],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"pandoc rc={r.returncode}: {r.stderr[:150]}")
    return _SPAN_RE.sub("", r.stdout)


def _to_md(row: dict) -> dict:
    out = MD_DIR / f"{row['idx']:05d}.md"
    if out.exists() and out.stat().st_size > 0:
        return {"idx": row["idx"], "ok": True, "method": "cached",
                "chars": out.stat().st_size}
    try:
        ext = row["ext"]
        if ext == "odt":
            md = _odt_to_md(row["src"])
            method = "pandoc"
        elif ext == "hwpx":
            from nodes.hwpx_to_md.main import execute as _hwpx
            md = _hwpx({"파일": row["src"]}, {}, dict(_CTX))["텍스트"]
            method = "hwpx_node"
        elif ext == "hwp":
            from nodes.hwp_to_md.main import execute as _hwp
            md = _hwp({"파일": row["src"]}, {}, dict(_CTX))["텍스트"]
            method = "hwp_node"
        else:
            return {"idx": row["idx"], "ok": False, "error": f"미지원: {ext}"}

        md = (md or "").strip()
        if not md:
            return {"idx": row["idx"], "ok": False, "error": "빈 변환 결과"}
        out.write_text(md, encoding="utf-8")
        return {"idx": row["idx"], "ok": True, "method": method, "chars": len(md)}
    except Exception as e:
        return {"idx": row["idx"], "ok": False,
                "error": f"{type(e).__name__}: {e}"[:300]}


def main() -> int:
    rows = read_jsonl(MANIFEST)
    if not rows:
        print("manifest 없음 — inventory.py 먼저"); return 1
    MD_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_to_md, r): r for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                results.append(fut.result())
            except Exception:
                results.append({"idx": futs[fut]["idx"], "ok": False,
                                "error": traceback.format_exc()[-200:]})
            if i % 100 == 0:
                ok = sum(1 for r in results if r["ok"])
                print(f"  {i}/{len(rows)} (성공 {ok})", flush=True)

    results.sort(key=lambda r: r["idx"])
    write_jsonl(CONVERT_STATUS, results)
    ok = sum(1 for r in results if r["ok"])
    from collections import Counter
    methods = Counter(r.get("method") for r in results if r["ok"])
    print(f"변환 완료: {ok}/{len(results)} 성공 → {MD_DIR}")
    print(f"  방법: {dict(methods)}")
    fails = [r for r in results if not r["ok"]]
    if fails:
        from collections import Counter
        top = Counter(r["error"].split(":")[0] for r in fails).most_common(5)
        print(f"  실패 {len(fails)}건, 상위 원인: {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
