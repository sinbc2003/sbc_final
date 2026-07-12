# -*- coding: utf-8 -*-
"""전국 공문 시범 PDF → md 변환 (kordoc, 실패 시 PyMuPDF 폴백).

입력: D:\\lora_data\\pilot_pdf\\*.pdf (open.go.kr 결재문서본문)
출력: D:\\lora_data\\pilot_md\\{reg}.md + pilot_convert_status.jsonl
비교 실측(20건): kordoc 평균 996자·표 보존 vs PyMuPDF 661자·표 상실 → kordoc 채택.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import ROOT  # noqa: F401 (sys.path 설정 부수효과)

from nodes.pdf_to_md.main import _convert_with_kordoc  # noqa: E402

PDF_DIR = Path(r"D:\lora_data\pilot_pdf")
MD_DIR = Path(r"D:\lora_data\pilot_md")
STATUS = Path(r"D:\lora_data\pilot_convert_status.jsonl")

sys.stdout.reconfigure(encoding="utf-8")


def _pymupdf(path: Path) -> str:
    import fitz
    doc = fitz.open(str(path))
    return "\n\n".join(page.get_text("text") for page in doc)


def convert_one(p: Path) -> dict:
    out = MD_DIR / (p.stem + ".md")
    if out.exists() and out.stat().st_size > 0:
        return {"reg": p.stem, "ok": True, "method": "cached"}
    try:
        md = _convert_with_kordoc(str(p), "")
        method = "kordoc"
        if not md or not md.strip():
            md = _pymupdf(p)
            method = "pymupdf"
        md = (md or "").strip()
        if not md:
            return {"reg": p.stem, "ok": False, "error": "빈 변환"}
        out.write_text(md, encoding="utf-8")
        return {"reg": p.stem, "ok": True, "method": method, "chars": len(md)}
    except Exception as e:
        return {"reg": p.stem, "ok": False,
                "error": f"{type(e).__name__}: {e}"[:200]}


def main() -> int:
    MD_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(convert_one, p): p for p in pdfs}
        for i, fut in enumerate(as_completed(futs), 1):
            results.append(fut.result())
            if i % 100 == 0:
                ok = sum(1 for r in results if r["ok"])
                print(f"  {i}/{len(pdfs)} (성공 {ok})", flush=True)

    with STATUS.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = sum(1 for r in results if r["ok"])
    from collections import Counter
    methods = Counter(r.get("method") for r in results if r["ok"])
    print(f"변환: {ok}/{len(results)} 성공, 방법 {dict(methods)} → {MD_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
