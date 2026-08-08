# -*- coding: utf-8 -*-
"""v9 채움 LoRA 학습쌍 합성 — 기작성 양식에서 (빈 양식 + 정답) 자동 생성 (§35).

원리: 크롤 양식 중 이미 채워진 문서의 데이터 셀을 코드로 비우면
(빈 양식, {셀ID: 정답값}) 쌍이 공짜로 나온다. 사람 라벨링 0.

체인: hwpx 파싱 → 기작성 판정(데이터 셀 값 비율) → 데이터 셀 클리어
→ PII 가짜값 치환(성명·전화·이메일·주민번호 — 문서 내 일관 매핑)
→ (그리드 렌더+라벨 목록+지시 → 채움 JSON) 학습쌍 JSONL.

지시문은 1차로 템플릿 합성(정답 나열형·서술형), 2차로 abstractify류
역생성(LLM)을 --abstractify에서 붙인다.

실행: python scripts/lora/make_fill_dataset.py --src D:\lora_data\form_bench\hwpx_converted --out D:\lora_data\fill_v9
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.hwpml.hwpx_grid import parse_hwpx, extract_blank_fields, fill_hwpx_cells

# ── 기작성 판정 ──
# 데이터 영역(헤더 밖) 셀 중 값이 있는 비율이 이 이상이면 "기작성 문서"
FILLED_RATIO = 0.5
MIN_FILLED_CELLS = 4          # 너무 작은 표는 쌍 가치 없음
MAX_VALUE_LEN = 120           # 서술형 장문 셀은 채움 학습 대상에서 제외

# ── 구조 셀(라벨·제목·선택지) 제외 — 데이터 셀만 수확 ──
# 셀 값 전체가 라벨 어휘면 구조물 (빈 양식에 원래 있어야 함)
_LABEL_VOCAB_RE = re.compile(
    r"^(학교명|학교|성\s*명|이름|연락처|전화번호|부서명|부서|담당자명?|담당|일시|날짜|장소|"
    r"대상|인원|서명|직위|직급|소속|학년|반|번호|제목|기간|내용|비고|구분|계|합계|총계|"
    r"신청인|작성자|확인|결재|검토|승인|주소|이메일|순번|연번|항목|현황|명단)$")
_CHECKBOX_RE = re.compile(r"[□■☐☑✓]")

# ── 데이터 형상 포지티브 선별 — 정밀도 우선 (구조물 오염 1쌍이 깨끗한 10쌍보다 해로움) ──
_DATA_SHAPES = [
    re.compile(r"(?:19|20)\d{2}\s*[.\-/년]"),            # 날짜형
    re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}"),   # 전화형
    re.compile(r"^\d[\d,.\s]*\s*(?:명|원|개|권|부|회|시간|분|%|㎡|평)?$"),  # 수량형
    re.compile(r"(?:초등학교|중학교|고등학교|학교|교육청|교육지원청|유치원|대학교)$"),  # 기관명형
    re.compile(r"^[김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노][가-힣]{1,2}$"),  # 인명형
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),               # 이메일
    re.compile(r"^\d+학년|^\d+반|^\d+명$"),               # 학년·반·인원
]


# 견본·템플릿·제목형 — 데이터 형상과 겹쳐도 수확 금지
_ANTI_DATA = [
    re.compile(r"^[*※◦·․]|^예시|견본"),                      # 안내·예시 문구
    re.compile(r"[○◯〇ㅇ](?:\s*[○◯〇ㅇ]){1,}|OO|00원|^0{2,}"),  # 견본 자리표시('○ ○ ○' 띄어쓰기 포함)
    re.compile(r"(?:\d{4}년?\s*)?월\s*일"),                   # '2026년 월 일' 빈 날짜 템플릿
    re.compile(r"20\d{2}\s*\.\s*\.|\(\s*요일\s*\)"),          # '2026. . .( 요일)' 빈 날짜
    re.compile(r"(?:신청서|보고서|계획서|확인서|서약서|조사서|현황|명단|명부|서식)\s*$"),  # 제목형
    re.compile(r"합니다|바랍니다|서약하며|확인하며"),           # 양식 상용문구
]


def _looks_like_data(v: str) -> bool:
    if any(p.search(v) for p in _ANTI_DATA):
        return False
    return any(p.search(v) for p in _DATA_SHAPES)

# ── PII 치환 ──
_FAKE_NAMES = ["김민준", "이서연", "박지호", "최수아", "정도윤", "강하은",
               "조시우", "윤지유", "장예준", "임채원", "한지안", "오건우"]
_NAME_LABEL_RE = re.compile(r"성\s*명|이름|담당자|신청인|작성자|추천인|지도교사|교사명|학생명")
_PHONE_RE = re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}")
_RRN_RE = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# 한국 성씨 상위 + 2~3자 이름 (셀 값 전체가 인명 형태일 때만)
_KNAME_RE = re.compile(r"^[김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노정][가-힣]{1,2}$")


def _fake_phone(rng: random.Random) -> str:
    return f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


class PiiMapper:
    """문서 내 동일 원본값 → 동일 가짜값 (정답·지시문 일관성 보장)."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.names: dict[str, str] = {}
        self.phones: dict[str, str] = {}

    def map_value(self, value: str, label: str) -> str:
        v = value
        for m in _RRN_RE.findall(v):
            v = v.replace(m, "000000-0000000")
        for m in _EMAIL_RE.findall(v):
            v = v.replace(m, "user@example.com")
        for m in _PHONE_RE.findall(v):
            if m not in self.phones:
                self.phones[m] = _fake_phone(self.rng)
            v = v.replace(m, self.phones[m])
        s = v.strip()
        # 인명: 라벨이 인명성이거나 값 자체가 인명 형태일 때만 통째 치환
        if s and (_NAME_LABEL_RE.search(label or "") or _KNAME_RE.match(s)):
            if _KNAME_RE.match(s):
                if s not in self.names:
                    self.names[s] = self.rng.choice(_FAKE_NAMES)
                v = v.replace(s, self.names[s])
        return v


def harvest_doc(path: Path, seed: int) -> dict | None:
    """기작성 hwpx → {blank_map, answers[{id,label,value}], render} 또는 None."""
    try:
        doc = parse_hwpx(str(path))
    except Exception:
        return None
    fields = extract_blank_fields(doc, include_filled=True)
    # 데이터 영역의 값 있는 text 셀 (부분 슬롯·빈 셀 제외)
    data_cells = [f for f in fields if f["value_type"] == "text"]

    # 다른 셀의 라벨(행/열 헤더)로 쓰인 텍스트 = 구조 셀 → 수확 금지
    header_texts: set[str] = set()
    for f in data_cells:
        for h in (f.get("row_header"), f.get("col_header")):
            if h:
                for part in re.split(r"[×/|]", h):
                    part = part.strip()
                    if part:
                        header_texts.add(part)

    def _is_data_cell(f: dict) -> bool:
        v = f["current_value"].strip()
        if not v or len(v) > MAX_VALUE_LEN:
            return False
        if not (f.get("row_header") or f.get("col_header")):
            return False          # 라벨 관계 없는 셀(제목·독립 셀)은 구조물
        if v in header_texts:
            return False          # 다른 셀의 라벨로 쓰임 = 라벨 셀
        if _LABEL_VOCAB_RE.match(v):
            return False          # 값 자체가 라벨 어휘
        if _CHECKBOX_RE.search(v):
            return False          # 선택지 셀(클리어하면 양식 훼손)
        if not _looks_like_data(v):
            return False          # 데이터 형상이 아니면 수확 안 함 (정밀도 우선)
        return True

    filled = [f for f in data_cells if _is_data_cell(f)]
    # 포지티브 선별이 품질을 보장하므로 비율 게이트 없음 — 개수 하한만
    if len(filled) < MIN_FILLED_CELLS:
        return None

    pii = PiiMapper(seed)
    answers = []
    for f in filled:
        val = pii.map_value(f["current_value"].strip(), f.get("label", ""))
        answers.append({"id": f["id"], "label": f.get("label", ""), "value": val})

    return {
        "file": path.name,
        "blank_ids": [a["id"] for a in answers],
        "answers": answers,
        "tables": len(doc.tables),
    }


def make_blank_form(src: Path, out: Path, blank_ids: list[str]) -> bool:
    try:
        n = fill_hwpx_cells(str(src), str(out), {i: "" for i in blank_ids})
        return n >= len(blank_ids) * 0.8
    except Exception:
        return False


def render_blank_grid(blank_path: Path) -> str | None:
    """빈 양식의 그리드 렌더 + 라벨 목록 (모델 입력)."""
    try:
        doc = parse_hwpx(str(blank_path))
    except Exception:
        return None
    parts = [doc.render_text(mark_blanks=True)[:4000]]
    fields = [f for f in extract_blank_fields(doc) if f["is_empty"]]
    lines = [f"- {f['id']} : {f.get('label', '')}" for f in fields]
    parts.append("### 채워야 할 빈칸\n" + "\n".join(lines[:120]))
    return "\n\n".join(parts)


def synth_instruction(answers: list[dict], rng: random.Random) -> str:
    """1차 템플릿 지시문 — 정답을 자연어로 흩뿌린다 (나열형/서술형/축약형)."""
    pairs = [(a["label"] or a["id"], a["value"]) for a in answers]
    style = rng.randint(0, 2)
    if style == 0:  # 나열형
        body = ", ".join(f"{l.split('—')[0].strip()}은(는) {v}" for l, v in pairs)
        return f"빈칸 채워줘. {body}."
    if style == 1:  # 서술형
        body = " ".join(f"{l.split('—')[0].strip()}: {v}." for l, v in pairs)
        return f"다음 내용으로 양식을 작성해줘. {body}"
    # 축약형 — 일부만 지시(나머지는 모델이 생략해야 정답)
    k = max(2, len(pairs) * 2 // 3)
    sub = rng.sample(pairs, k)
    body = ", ".join(f"{l.split('—')[0].strip()} {v}" for l, v in sub)
    return f"{body} 로 채워줘", [a for a in answers
                                if (a["label"] or a["id"]).split("—")[0].strip()
                                in {l.split("—")[0].strip() for l, _ in sub}]


# ── 값 합성 모드 (--synth) — 빈 양식 + 라벨 조건 값 생성 = 구성상 확정 정답 ──
# 크롤 실측: 기작성 문서(명단·현황 수합본)는 대부분 '비공개 파일'이라 수확 불가.
# 대신 공개인 빈 서식에 우리가 값을 만들어 넣으면 PII 0·견본 혼동 0.
_SCHOOLS = ["대한중학교", "한빛고등학교", "푸른초등학교", "샛별중학교", "동산고등학교",
            "미래초등학교", "청람중학교", "해솔고등학교", "새봄초등학교", "가온중학교"]
_SUBJECTS = ["수학", "국어", "영어", "과학", "사회", "체육", "음악", "미술", "정보"]

_LABEL_GEN = [
    (re.compile(r"성\s*명|이름|담당자|신청인|작성자|교사명|학생명|강사명"),
     lambda r: r.choice(_FAKE_NAMES)),
    (re.compile(r"연락처|전화|휴대폰|핸드폰"), _fake_phone),
    (re.compile(r"이메일|메일|e-?mail", re.I),
     lambda r: f"{r.choice(['kim', 'lee', 'park', 'choi'])}{r.randint(1, 99)}@example.com"),
    (re.compile(r"일시|날짜|일자|기간"),
     lambda r: f"2026. {r.randint(3, 12)}. {r.randint(1, 28)}."),
    (re.compile(r"학교명|학교|기관명|기관|소속"), lambda r: r.choice(_SCHOOLS)),
    (re.compile(r"학년"), lambda r: f"{r.randint(1, 6)}학년"),
    (re.compile(r"반$|반\b"), lambda r: f"{r.randint(1, 12)}반"),
    (re.compile(r"인원|명수|참가자\s*수|학생\s*수"), lambda r: f"{r.randint(5, 120)}명"),
    (re.compile(r"금액|예산|비용|원$"), lambda r: f"{r.randint(1, 900) * 10000:,}원"),
    (re.compile(r"직위|직급"), lambda r: r.choice(["교사", "부장교사", "교감", "주무관"])),
    (re.compile(r"과목|교과|분야"), lambda r: r.choice(_SUBJECTS)),
    (re.compile(r"장소"), lambda r: r.choice(["시청각실", "본교 강당", "과학실", "도서관", "운동장"])),
]


def synth_values(blank_path: Path, seed: int) -> list[dict] | None:
    """빈 양식의 라벨을 읽어 그럴듯한 값을 생성 — 인식 가능한 라벨만 (정밀도 우선)."""
    try:
        doc = parse_hwpx(str(blank_path))
    except Exception:
        return None
    fields = [f for f in extract_blank_fields(doc) if f["is_empty"]]
    rng = random.Random(seed)
    out = []
    for f in fields:
        label = f.get("label", "")
        for pat, gen in _LABEL_GEN:
            if pat.search(label):
                out.append({"id": f["id"], "label": label, "value": gen(rng)})
                break
    if len(out) < 3:
        return None
    # 대형 양식(수백 빈칸)은 지시문이 폭발 — 쌍당 40개 샘플 (시드 결정적)
    if len(out) > 40:
        out = rng.sample(out, 40)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"D:\lora_data\form_bench\hwpx_converted")
    ap.add_argument("--out", default=r"D:\lora_data\fill_v9")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--synth", action="store_true",
                    help="빈 양식 + 값 합성 모드 (기작성 수확 대신)")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    (out / "blank_forms").mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    pairs_path = out / "fill_pairs.jsonl"
    n_docs = n_pairs = 0
    skipped = []

    with pairs_path.open("w", encoding="utf-8") as pf:
        for i, p in enumerate(sorted(src.glob("*.hwpx"))):
            if args.synth:
                # 값 합성: 빈 양식 그대로 + 라벨 조건 생성값 = 확정 정답
                vals = synth_values(p, seed=args.seed + i)
                if not vals:
                    skipped.append(p.name)
                    continue
                h = {"answers": vals}
                grid = render_blank_grid(p)
                if not grid:
                    skipped.append(p.name + " (렌더 실패)")
                    continue
            else:
                h = harvest_doc(p, seed=args.seed + i)
                if not h:
                    skipped.append(p.name)
                    continue
                blank = out / "blank_forms" / p.name
                if not make_blank_form(p, blank, h["blank_ids"]):
                    skipped.append(p.name + " (클리어 실패)")
                    continue
                grid = render_blank_grid(blank)
                if not grid:
                    skipped.append(p.name + " (렌더 실패)")
                    continue

            # 스타일별 지시문 3종 → 쌍 3개 (같은 양식, 다른 지시)
            for style_seed in range(3):
                srng = random.Random(args.seed + i * 10 + style_seed)
                inst = synth_instruction(h["answers"], srng)
                answers = h["answers"]
                if isinstance(inst, tuple):  # 축약형: 지시된 것만 정답
                    inst, answers = inst
                completion = {"채움": [{"id": a["id"], "값": a["value"]}
                                     for a in answers]}
                pf.write(json.dumps({
                    "file": p.name,
                    "instruction": inst,
                    "grid": grid,
                    "output": completion,
                }, ensure_ascii=False) + "\n")
                n_pairs += 1
            n_docs += 1

    print(f"기작성 양식 {n_docs}종 → 학습쌍 {n_pairs}개 → {pairs_path}")
    print(f"스킵 {len(skipped)}종 (미기작성/소형/실패)")
    for s in skipped[:10]:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
