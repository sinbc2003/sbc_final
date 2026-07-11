# -*- coding: utf-8 -*-
"""3단계: md 익명화 → D:\\lora_data\\md_anon.

정규식 기반 PII 치환(전화·주민번호·이메일·계좌·생년월일·라벨 기반 이름).
치환 통계·표본은 anon_report.json — 학습 전 육안 확인용.
학습셋에는 md_anon만 사용한다(원본 md 금지).
"""
from __future__ import annotations

import json
import re
import sys

from common import ANON_DIR, ANON_REPORT, MD_DIR

sys.stdout.reconfigure(encoding="utf-8")

# 알려진 실명(작성자 본인 등) — 전역 치환
KNOWN_NAMES = ["신병철"]

# 이름 오탐 방지: 라벨 뒤 2~4자 한글이라도 이 단어면 치환 안 함
NAME_STOPWORDS = {
    "부서", "학교", "교사", "선생", "정보", "없음", "본인", "확인", "서명",
    "직인", "생략", "소속", "직위", "직급", "연락", "전화", "이름", "성명",
}

PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("주민번호", re.compile(r"(?<!\d)\d{6}\s*[-–]\s*[1-4]\d{6}(?!\d)"),
     "000000-0000000"),
    ("전화번호", re.compile(
        r"(?<!\d)0\d{1,2}[-.)\s]\s?\d{3,4}[-.\s]\d{4}(?!\d)"),
     "010-0000-0000"),
    ("이메일", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "user@example.com"),
    ("계좌번호", re.compile(
        r"((?:계좌|입금|예금)\s*(?:번호)?\s*[:：]?\s*)[\d][\d\-\s]{7,}\d"),
     r"\g<1>000-000000-00000"),
    ("생년월일", re.compile(
        r"((?:생년월일|생일)\s*[:：]?\s*)[\d]{2,4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}일?"),
     r"\g<1>2000.01.01."),
]

NAME_LABEL_RE = re.compile(
    r"((?:기안자|담당자|작성자|검토자|결재자|담임|지도교사|성명|담당)\s*[:：]?\s*)"
    r"([가-힣]{2,4})(?![가-힣])")


def anonymize_text(text: str, stats: dict, samples: list) -> str:
    for name in KNOWN_NAMES:
        n = text.count(name)
        if n:
            stats["실명(지정)"] = stats.get("실명(지정)", 0) + n
            text = text.replace(name, "홍길동")

    for label, pat, repl in PATTERNS:
        def _cap(m, _label=label):
            if len(samples) < 30:
                samples.append({"유형": _label, "원문": m.group(0)[:40]})
            return m.expand(repl) if "\\" in repl or "\\g" in repl else repl
        text, n = pat.subn(_cap, text)
        if n:
            stats[label] = stats.get(label, 0) + n

    def _name(m):
        if m.group(2) in NAME_STOPWORDS:
            return m.group(0)
        stats["이름(라벨)"] = stats.get("이름(라벨)", 0) + 1
        if len(samples) < 30:
            samples.append({"유형": "이름(라벨)", "원문": m.group(0)[:40]})
        return m.group(1) + "홍길동"
    text = NAME_LABEL_RE.sub(_name, text)
    return text


def main() -> int:
    ANON_DIR.mkdir(parents=True, exist_ok=True)
    stats: dict = {}
    samples: list = []
    files = sorted(MD_DIR.glob("*.md"))
    for i, p in enumerate(files, 1):
        out = ANON_DIR / p.name
        text = p.read_text(encoding="utf-8")
        out.write_text(anonymize_text(text, stats, samples), encoding="utf-8")
        if i % 200 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    ANON_REPORT.write_text(
        json.dumps({"files": len(files), "치환": stats, "표본": samples},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"익명화 완료: {len(files)}건 → {ANON_DIR}")
    print(f"  치환 통계: {stats}")
    print(f"  보고서: {ANON_REPORT} (학습 전 표본 육안 확인)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
