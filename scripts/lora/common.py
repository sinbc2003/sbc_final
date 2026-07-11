# -*- coding: utf-8 -*-
"""LoRA 데이터 파이프라인 공용 — 경로·파일명 파싱.

데이터는 리포 밖(D:\\lora_data, PII 포함 가능)에만 둔다. 리포에는 코드만.
파일명 규칙(K-에듀파인 export): "[기관-공문번호 (본문|시행|첨부)] 제목.ext"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_ROOT = Path(r"D:\lora_data")
RAW_DIR = DATA_ROOT / "raw"
MD_DIR = DATA_ROOT / "md"
ANON_DIR = DATA_ROOT / "md_anon"
DATASET_DIR = DATA_ROOT / "dataset"
MANIFEST = DATA_ROOT / "manifest.jsonl"
CONVERT_STATUS = DATA_ROOT / "convert_status.jsonl"
ANON_REPORT = DATA_ROOT / "anon_report.json"

TEXT_EXTS = {".odt", ".hwp", ".hwpx"}

# 기안문: "[기관-번호 (본문)] 제목.ext"
# 접수문: "[기관-번호 (본문) 발신기관 부서] 제목.ext" — (유형) 뒤 발신처 허용
FILENAME_RE = re.compile(
    r"^\[(?P<org>.+?)-(?P<num>\d+(?:-\d+)?)\s*\((?P<kind>[^)]+)\)"
    r"(?P<sender>[^\]]*)\]\s*"
    r"(?P<title>.+?)\s*\.(?P<ext>odt|hwp|hwpx)$",
    re.IGNORECASE,
)


def parse_filename(name: str) -> dict | None:
    """공문 파일명 파싱. 규칙 불일치 시 None."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    d = m.groupdict()
    d["ext"] = d["ext"].lower()
    d["sender"] = (d.get("sender") or "").strip() or None
    return d


def read_jsonl(path: Path) -> list[dict]:
    import json
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
