# -*- coding: utf-8 -*-
"""4단계: 익명화 md → 학습 데이터셋 (train.jsonl / val.jsonl).

v1 = 공문(기안문) 본문 생성 단일턴: {"prompt": 지시문, "completion": md}
- 선택: kind ∈ {본문, 시행}, 같은 (org, num)이면 본문 우선
- 필터: 변환 실패·120자 미만·표 위주(>70%)·8000자 초과(청킹은 2차)
- 지시문: 제목 기반 템플릿(하이엔드 역생성은 2차 레버)
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter

from common import (ANON_DIR, CONVERT_STATUS, DATASET_DIR, MANIFEST,
                    read_jsonl, write_jsonl)

sys.stdout.reconfigure(encoding="utf-8")

MIN_CHARS = 120
MAX_CHARS = 8000  # llm_generate CHUNK_THRESHOLD와 동일
TABLE_RATIO_MAX = 0.7

PROMPT_TEMPLATES = [
    "다음 제목으로 학교 공문(기안문) 본문을 작성하라.\n\n[제목]\n{title}",
    "'{title}' 제목의 공문 본문을 개조식으로 작성하라.",
    "학교 행정 문서 작성: 아래 건의 기안문 본문을 작성하라.\n\n건명: {title}",
]

# v2: 첨부 보고서·계획서 (유형 명시 지시문 — 공문과 한 어댑터에서 유형 구분 학습)
REPORT_PROMPT_TEMPLATES = [
    "다음 제목으로 학교 운영 계획서/보고서 본문을 작성하라.\n\n[제목]\n{title}",
    "'{title}' 계획서(보고서) 문서 본문을 장·절 구조로 작성하라.",
    "학교 내부 문서 작성: 아래 건의 계획·보고 문서 본문을 작성하라.\n\n건명: {title}",
]
REPORT_TITLE_RE = re.compile(r"계획|보고서|결과|운영안|방안|협의록")
REPORT_EXCLUDE_RE = re.compile(r"서식|양식|명부|명단|조사표|점검표|신청서|동의서|가정통신문")


_ESCAPES = [("\\.", "."), ("\\[", "["), ("\\]", "]"), ("\\(", "("),
            ("\\)", ")"), ("\\-", "-"), ("\\'", "'")]


def clean_md(md: str) -> str:
    """pandoc gfm 이스케이프·blockquote 잔재 제거 (공문 원문에 없는 표기)."""
    for a, b in _ESCAPES:
        md = md.replace(a, b)
    lines = [l[2:] if l.startswith("> ") else l for l in md.splitlines()]
    return "\n".join(lines).strip()


def table_ratio(md: str) -> float:
    """md 파이프 표 + hwp 노드가 내는 HTML 표 라인 비율."""
    lines = [l for l in md.splitlines() if l.strip()]
    if not lines:
        return 0.0
    def is_table(l: str) -> bool:
        s = l.lstrip()
        return s.startswith("|") or s.startswith("<t") or s.startswith("</t")
    return sum(1 for l in lines if is_table(l)) / len(lines)


def main() -> int:
    manifest = {r["idx"]: r for r in read_jsonl(MANIFEST)}
    status = {r["idx"]: r for r in read_jsonl(CONVERT_STATUS)}

    # (org, num) 그룹에서 본문 우선 대표 1건
    groups: dict[tuple, dict] = {}
    for idx, row in manifest.items():
        if row["kind"] not in ("본문", "시행") or not row["num"]:
            continue
        if not status.get(idx, {}).get("ok"):
            continue
        key = (row["org"], row["num"])
        cur = groups.get(key)
        if cur is None or (row["kind"] == "본문" and cur["kind"] != "본문"):
            groups[key] = row

    drops = Counter()
    examples = []
    rng = random.Random(42)
    for row in groups.values():
        p = ANON_DIR / f"{row['idx']:05d}.md"
        if not p.exists():
            drops["md없음"] += 1
            continue
        md = clean_md(p.read_text(encoding="utf-8"))
        if len(md) < MIN_CHARS:
            drops["짧음"] += 1
            continue
        if len(md) > MAX_CHARS:
            drops["초과길이"] += 1
            continue
        if table_ratio(md) > TABLE_RATIO_MAX:
            drops["표위주"] += 1
            continue
        tpl = rng.choice(PROMPT_TEMPLATES)
        examples.append({
            "prompt": tpl.format(title=row["title"]),
            "completion": md,
            "meta": {"idx": row["idx"], "kind": row["kind"],
                     "folder": row["folder"], "title": row["title"],
                     "type": "gongmun"},
        })

    # v2: 첨부 보고서·계획서 편입 (유형 명시 지시문)
    n_report = 0
    for idx, row in manifest.items():
        if row["kind"] != "첨부":
            continue
        title = row["title"]
        if not REPORT_TITLE_RE.search(title) or REPORT_EXCLUDE_RE.search(title):
            continue
        if not status.get(idx, {}).get("ok"):
            continue
        p = ANON_DIR / f"{idx:05d}.md"
        if not p.exists():
            drops["보고서:md없음"] += 1
            continue
        md = clean_md(p.read_text(encoding="utf-8"))
        if len(md) < 300:
            drops["보고서:짧음"] += 1
            continue
        if len(md) > MAX_CHARS:
            drops["보고서:초과길이"] += 1
            continue
        if table_ratio(md) > TABLE_RATIO_MAX:
            drops["보고서:표위주"] += 1
            continue
        tpl = rng.choice(REPORT_PROMPT_TEMPLATES)
        examples.append({
            "prompt": tpl.format(title=title),
            "completion": md,
            "meta": {"idx": idx, "kind": "첨부", "folder": row["folder"],
                     "title": title, "type": "report"},
        })
        n_report += 1
    print(f"보고서·계획서 편입: {n_report}쌍")

    # 전국 공문 시범 코퍼스 병합(§25 v3) — pilot_extract 산출물, 스키마 동일.
    # 품질 검증 완료본(523쌍, PII 0·끝. 종결 처리)만 이 파일로 온다.
    national_path = DATASET_DIR / "gongmun_national.jsonl"
    n_national = 0
    if national_path.exists():
        for line in national_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                examples.append(json.loads(line))
                n_national += 1
        print(f"전국 공문 병합: {n_national}쌍")

    # ── v4 변환 (§29 판정 후속: 편향·붙임회피·축약매핑·유형균형) ──
    # 1) 기관-문서번호 placeholder화 — "수원외국어고등학교-1485" 각인이
    #    서식으로 굳어 기관 지정 프롬프트를 이겼다(실측). 제품은 생성 후
    #    {기관명}/{문서번호}를 설정·입력값으로 치환한다(llm_generate 후처리).
    org_num_re = re.compile(
        r"[가-힣A-Za-z0-9·]{2,20}"
        r"(?:교육청|교육지원청|고등학교|중학교|초등학교|대학교|학교|유치원|"
        r"부|과|실|원|센터|담당관)\s?-\s?\d+")
    # 줄임형·원문 오타("고등하교")까지 — 붙임 파일명에서 실측된 변형들
    suwon_re = re.compile(r"수원외국어고등[학하]교|수원외국어고|수원외고")
    for e in examples:
        c = org_num_re.sub("{기관명}-{문서번호}", e["completion"])
        c = suwon_re.sub("{기관명}", c)
        # 결문 표기 규정 복원: 변환기가 공백을 정규화해 "1부. 끝."(한 칸)으로
        # 무너진 것을 규정 표기(두 칸)로 — 다음 학습부터 모델이 직접 배운다.
        c = re.sub(r"([^\s]) ?끝\s*\.\s*$", r"\1  끝.", c.rstrip())
        # 표기 규정(공문서 작성법): 날짜 'YYYY. M. D.'(온점 뒤 1타·선행 0 제거),
        # 관련 문서번호 뒤 '호' 삭제 — 모델이 처음부터 규정대로 쓰게 학습
        c = re.sub(r"((?:19|20)\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?",
                   lambda m: f"{m.group(1)}. {int(m.group(2))}. {int(m.group(3))}.", c)
        c = re.sub(r"\)\s*호(?=[\s,.)]|$)", ")", c, flags=re.M)
        # 관련 문서의 날짜도 placeholder(v9) — 모델이 알 수 없는 값이라 환각
        # 필연(사용자 실측 지적). {관련일자}로 학습 → llm_generate 후처리가
        # 사용자 제공값 또는 ○ 표기로 치환.
        c = re.sub(r"(\{기관명\}-\{문서번호\})\(\s*(?:19|20)\d{2}[.\s]+\d{1,2}[.\s]+\d{1,2}[.\s]*\)",
                   r"\1({관련일자})", c)
        # 담당·문의 라인의 실명·연락처 placeholder(v9) — v8이 '박은비' 등
        # 학습 원문의 실명을 각인·유출한 실측(사용자 라이브 테스트). 인명은
        # 문의 문맥의 직함 뒤 2~3자만 치환(오탐 최소화).
        lines = c.split("\n")
        for li, ln in enumerate(lines):
            if re.search(r"문의|담당|연락", ln):
                ln = re.sub(r"((?:교무기획부장|기획부장|부장|팀장|교장|교감|교사|"
                            r"주무관|장학사|담당자|담당)\s+)[가-힣]{2,3}(?=[)\s,.]|$)",
                            r"\1{담당자명}", ln)
                ln = re.sub(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}", "{연락처}", ln)
                lines[li] = ln
        c = "\n".join(lines)
        e["completion"] = c

    # 1.3) HTML 표 완성문 드롭(v8) — kordoc이 hwp 표를 HTML로 내보낸 잔재가
    #      28% 실측. v7에서 생성 출력에 <table> 쓰레기가 그대로 새는 회귀 확인
    #      — md 파이프 표만 정상 학습 타깃으로 남긴다.
    before = len(examples)
    examples = [e for e in examples
                if "<table" not in e["completion"] and "<tr>" not in e["completion"]]
    drops["v8:HTML표"] = before - len(examples)

    # 1.5) 관련 블록 1줄 정리(v7, §31) — 다항 관련(가.나.다. 나열, 16% 실측)이
    #      생성 시 관련 라인 과잉(v5 6개→v6 3개 잔존)의 학습 원인. 실제 기안
    #      관행대로 첫 참조 1줄로 축약해 "관련은 한 줄"을 학습시킨다.
    rel_block_re = re.compile(r"^1\.\s*관련.*?(?=\n\s*2\.\s)", re.S)
    ref_re = re.compile(r"\{기관명\}-\{문서번호\}(\([^)]*\))?")
    n_rel = 0
    for e in examples:
        c = e["completion"]
        m = rel_block_re.match(c)
        if not m:
            continue
        block = m.group(0)
        refs = ref_re.findall(block)
        if len(refs) < 2:
            continue
        first = ref_re.search(block)
        one_line = f"1. 관련: {first.group(0)}"
        e["completion"] = one_line + c[m.end():]
        n_rel += 1
    print(f"v7: 관련 다항→1줄 축약 {n_rel}쌍")

    # 2) 붙임-회피 본문 필터 — 관련·붙임·끝. 제외 실본문이 80자 미만이면
    #    "붙임과 같이 …합니다" 껍데기(전국 코퍼스 습관). 본문 생성 위축 원인.
    def _body_len(c: str) -> int:
        n = 0
        for l in c.splitlines():
            s = l.strip()
            if (not s or s == "끝." or s.startswith("붙임")
                    or re.match(r"^\d+\.\s*관련", s)):
                continue
            n += len(s)
        return n
    before = len(examples)
    examples = [e for e in examples if _body_len(e["completion"]) >= 80]
    drops["v4:붙임회피"] = before - len(examples)

    # 3) 축약 프롬프트 증강 — 짧은 요청→완결 문서 매핑을 명시 학습
    #    ("기간제 채용 공문작성" 같은 한 줄 요청에 140자 껍데기가 나오던 원인:
    #    이 매핑을 배운 적이 없음).
    terse_templates = ["{t} 공문 작성", "{t} 공문 써줘", "{t} 기안문 작성해줘"]
    gongmun_long = [e for e in examples
                    if e.get("meta", {}).get("type") != "report"
                    and not e.get("meta", {}).get("aug")
                    and len(e["completion"]) >= 400
                    and e.get("meta", {}).get("title")]
    rng.shuffle(gongmun_long)
    aug = []
    for e in gongmun_long[:300]:
        title = e["meta"]["title"]
        short = re.sub(r"\(.*?\)|\[.*?\]|2\d{3}학?년도?\s?", "", title).strip(" .-")
        if len(short) < 4:
            short = title
        aug.append({"prompt": rng.choice(terse_templates).format(t=short),
                    "completion": e["completion"],
                    "meta": {**e["meta"], "aug": "terse"}})
    examples.extend(aug)
    print(f"v4: placeholder화 전체 / 붙임회피 드롭 {drops['v4:붙임회피']} / 축약증강 {len(aug)}쌍")

    # ── v5: 개요→완성문 instruction (§30 역생성) ─────────────────
    # v4까지는 '제목→완성문 창작'이라 개요 준수를 배운 적이 없어 어댑터가
    # 사실 순응을 훼손했다(실측). abstractify.py가 역추출한 개요를
    # instruction으로 삼아 서식+사실 순응을 동시에 학습시킨다.
    # 혼합: 개요 70% / 제목 30% (축약 증강은 별도 유지 — 짧은 요청 대응력).
    outline_templates = [
        "다음 개요로 학교 공문(기안문)을 작성하라.\n\n[개요]\n{o}",
        ("아래 개요의 사실만 사용하여 공문 본문을 개조식으로 작성하라. "
         "개요에 없는 조건·일정·숫자를 지어내지 마라.\n\n[개요]\n{o}"),
        "학교 행정 문서 작성: 다음 개요를 기안문 서식으로 작성하라.\n\n[개요]\n{o}",
    ]
    abstracts_path = DATASET_DIR / "abstracts.jsonl"
    if abstracts_path.exists():
        abstracts = {}
        for line in abstracts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                abstracts[d["key"]] = d["개요"]

        def _key(e: dict) -> str:
            m = e.get("meta", {})
            return str(m.get("reg") or f"idx{m.get('idx')}_{m.get('kind','')}")

        n_outline = 0
        for e in examples:
            m = e.get("meta", {})
            if m.get("aug") or m.get("type") == "report":
                continue
            items = abstracts.get(_key(e))
            if not items or rng.random() >= 0.7:
                continue
            o = "\n".join("- " + s for s in items)
            e["prompt"] = rng.choice(outline_templates).format(o=o)
            e["meta"] = {**m, "instr": "outline"}
            n_outline += 1
        print(f"v5: 개요 instruction 전환 {n_outline}쌍 (역추출 {len(abstracts)}건)")

    # 4) 계획서·보고서 업웨이트 ×2 — 공문 비중 재확대에 따른 유형 혼선 완화
    reports = [e for e in examples if e.get("meta", {}).get("type") == "report"
               and not e.get("meta", {}).get("aug")]
    for e in reports:
        title = e.get("meta", {}).get("title", "")
        examples.append({"prompt": rng.choice(REPORT_PROMPT_TEMPLATES).format(title=title),
                         "completion": e["completion"],
                         "meta": {**e["meta"], "aug": "dup"}})
    print(f"v4: 계획서 업웨이트 +{len(reports)}쌍")

    rng.shuffle(examples)
    n_val = max(1, len(examples) // 20)
    val, train = examples[:n_val], examples[n_val:]

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(DATASET_DIR / "train.jsonl", train)
    write_jsonl(DATASET_DIR / "val.jsonl", val)

    stats = {
        "그룹(공문건)": len(groups), "채택": len(examples),
        "train": len(train), "val": len(val), "드롭": dict(drops),
        "평균길이": (sum(len(e["completion"]) for e in examples)
                  // max(1, len(examples))),
    }
    (DATASET_DIR / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"데이터셋: {stats}")
    print(f"→ {DATASET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
