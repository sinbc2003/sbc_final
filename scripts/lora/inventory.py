# -*- coding: utf-8 -*-
"""1단계: D:\\lora_data\\raw 순회 → manifest.jsonl.

행: {idx, src, folder, org, num, kind, title, ext, size}
파일명 규칙 불일치는 kind=None, title=파일명(확장자 제외)으로 보존.
"""
from __future__ import annotations

import sys

from common import MANIFEST, RAW_DIR, TEXT_EXTS, parse_filename, write_jsonl

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    rows = []
    for p in sorted(RAW_DIR.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        folder = p.relative_to(RAW_DIR).parts[0]  # 기안문 | 접수문
        meta = parse_filename(p.name)
        rows.append({
            "idx": len(rows),
            "src": str(p),
            "folder": folder,
            "org": meta["org"] if meta else None,
            "num": meta["num"] if meta else None,
            "kind": meta["kind"] if meta else None,
            "sender": meta.get("sender") if meta else None,
            "title": meta["title"] if meta else p.stem,
            "ext": p.suffix.lower().lstrip("."),
            "size": p.stat().st_size,
        })

    write_jsonl(MANIFEST, rows)

    from collections import Counter
    kinds = Counter(r["kind"] for r in rows)
    folders = Counter(r["folder"] for r in rows)
    exts = Counter(r["ext"] for r in rows)
    print(f"총 {len(rows)}건 → {MANIFEST}")
    print(f"  폴더: {dict(folders)}")
    print(f"  유형: {dict(kinds)}")
    print(f"  확장자: {dict(exts)}")
    unmatched = sum(1 for r in rows if r["kind"] is None)
    print(f"  파일명 규칙 불일치: {unmatched}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
