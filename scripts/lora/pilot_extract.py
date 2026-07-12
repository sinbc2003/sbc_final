# -*- coding: utf-8 -*-
"""전국 공문 md → 본문 추출 → 익명화 → v3 후보 학습쌍.

레이아웃 2유형 실측: ①산문형(제목 라인→본문→"끝."→푸터) = 추출,
②표갇힘형(kordoc이 기안서식 표를 셀 단위로 뒤섞음) = 스킵(순서 파손).

산출: D:\\lora_data\\dataset\\gongmun_national.jsonl
  {"prompt","completion","meta"} — 프롬프트 절반에 "기관:" 컨텍스트 포함
  (기관 지정 생성 능력을 어댑터에 내재화 — 프롬프트 제어 실측에 근거).
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from common import write_jsonl  # noqa: F401 (sys.path 부수효과)
from anonymize import anonymize_text

MD_DIR = Path(r"D:\lora_data\pilot_md")
MANIFEST = Path(r"D:\lora_data\pilot_manifest.jsonl")
OUT = Path(r"D:\lora_data\dataset\gongmun_national.jsonl")

sys.stdout.reconfigure(encoding="utf-8")

END_RE = re.compile(r"끝\s?\.")
FOOTER_RE = re.compile(r"협조자|시행\s|접수\s|^전화\s|^우\d{5}|/http|@.*\.go\.kr")

PROMPTS_ORG = [
    "기관: {org}\n다음 제목으로 위 기관 명의의 공문(기안문) 본문을 작성하라.\n\n[제목]\n{title}",
    "{org}에서 생산하는 공문이다. '{title}' 제목의 기안문 본문을 작성하라.",
]
PROMPTS_PLAIN = [
    "다음 제목으로 학교 공문(기안문) 본문을 작성하라.\n\n[제목]\n{title}",
    "'{title}' 제목의 공문 본문을 개조식으로 작성하라.",
]


def extract_body(md: str) -> str | None:
    lines = md.splitlines()
    start = None
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("제목") and "<" not in s:  # 표갇힘형(<th>제목</th>) 제외
            start = i
            break
    if start is None:
        return None
    body: list[str] = []
    ended = False
    for l in lines[start + 1:]:
        s = l.strip()
        if not s:
            continue
        if FOOTER_RE.search(s) and not END_RE.search(s):
            break  # 푸터 도달(끝. 누락 문서)
        body.append(l.rstrip())
        if END_RE.search(s):
            ended = True
            break
    if not ended or not body:
        return None
    return "\n".join(body).strip()


def truncate_at_end(body: str) -> str:
    """공문은 '끝.'으로 종료가 규범 — 끝. 이후 잔여 마크업/푸터 절단.

    끝.이 표 셀 안에 있던 문서는 마지막 줄에 태그 조각이 남으므로 제거.
    """
    m = END_RE.search(body)
    if m:
        body = body[:m.end()].strip()
    lines = body.splitlines()
    if lines and "<" in lines[-1]:
        lines[-1] = re.sub(r"<[^>]+>", " ", lines[-1])
        lines[-1] = re.sub(r"\s{2,}", " ", lines[-1]).strip()
        body = "\n".join(lines).strip()
    return body


def strip_title_tail(body: str, title: str) -> str:
    """여러 줄로 감긴 제목의 꼬리가 본문 첫 줄에 남는 경우 제거."""
    lines = body.splitlines()
    flat_title = re.sub(r"\s+", "", title)
    while lines:
        head = re.sub(r"\s+", "", lines[0])
        if head and head in flat_title:
            lines.pop(0)
        else:
            break
    return "\n".join(lines).strip()


def main() -> int:
    meta = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("status") == "OK":
            meta[d["reg"]] = d

    rng = random.Random(42)
    rows, skipped_table, skipped_short = [], 0, 0
    stats = {}
    samples = []
    for p in sorted(MD_DIR.glob("*.md")):
        m = meta.get(p.stem)
        if not m:
            continue
        md = p.read_text(encoding="utf-8")
        body = extract_body(md)
        title = (m.get("title") or "").strip()
        if body is not None:
            body = truncate_at_end(strip_title_tail(body, title))
            if len(body) < 80:
                body = None
        if body is None:
            if "<table>" in md.split("제목")[0] or "<th>제목" in md:
                skipped_table += 1
            else:
                skipped_short += 1
            continue
        body = anonymize_text(body, stats, samples)
        org = (m.get("org") or "").strip()
        if not title:
            continue
        if org and rng.random() < 0.5:
            tpl = rng.choice(PROMPTS_ORG)
            prompt = tpl.format(org=org, title=title)
        else:
            tpl = rng.choice(PROMPTS_PLAIN)
            prompt = tpl.format(title=title)
        rows.append({
            "prompt": prompt, "completion": body,
            "meta": {"reg": p.stem, "org": org, "title": title,
                     "type": "gongmun_national"},
        })

    write_jsonl(OUT, rows)
    lens = sorted(len(r["completion"]) for r in rows)
    print(f"추출 성공 {len(rows)} / 표갇힘 스킵 {skipped_table} / 실패 {skipped_short}")
    if lens:
        print(f"본문 길이 중앙값 {lens[len(lens)//2]}자")
    print(f"익명화 치환: {stats}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
