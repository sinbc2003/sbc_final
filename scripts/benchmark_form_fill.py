# -*- coding: utf-8 -*-
"""채용점수표 자동 채점 벤치마크.

원본 hwpx에 이미 들어있는 데이터(이름·점수·순위)를 정답으로 삼는다.

레벨1 (기계 왕복, 기본):
  데이터 행을 지워 "빈 시험지" 생성 → 그리드 좌표로 복원 → 셀 단위 채점.
  hwpx_grid 모듈(추출·채움·주소 체계)의 회귀 테스트.

레벨2 (LLM, --llm [provider]):
  빈 시험지의 빈칸 스키마 + 명단 텍스트(이름·위원점수만)를 LLM에 주고
  {셀ID: 값} 매핑을 받는다. 소계·평균·순위는 코드가 계산. 채움 후 채점.
  → 로컬 gemma가 "의미 매칭"만 하면 되는 구조의 실측.

사용:
  python scripts/benchmark_form_fill.py                 # 레벨1
  python scripts/benchmark_form_fill.py --llm local     # 레벨2 (로컬 gemma)
  python scripts/benchmark_form_fill.py --llm claude    # 레벨2 (API)
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.hwpml.hwpx_grid import (  # noqa: E402
    parse_hwpx, extract_blank_fields, fill_hwpx_cells,
    find_below_marker, relocate_below_markers,
)

def _resolve_original() -> str:
    """벤치마크 기준 hwpx 위치 — 이식성 있게 해결.

    우선순위: 환경변수 BENCH_HWPX > 프로젝트 내 fixtures 사본 > 노트북 원본 경로.
    """
    env = os.environ.get("BENCH_HWPX")
    if env and Path(env).exists():
        return env
    fixture = ROOT / "data" / "fixtures" / "bench_score.hwpx"
    if fixture.exists():
        return str(fixture)
    return (r"C:\Users\sinbc\OneDrive\바탕 화면"
            r"\2024학년도 기간제 교사 채용 점수 집계표(역사, 체육, 러시아어, 프랑스어).hwpx")


ORIGINAL = _resolve_original()

# "이하 빈칸" 마커 글자 (한 셀에 한 글자씩 흩어져 있음) — LLM 벤치마크에선 제외
MARKER_CHARS = {"이", "하", "빈", "칸"}


def big_tables(doc):
    return [g for g in doc.tables if g.row_cnt >= 10]


def data_region(grid):
    """(시작행, 끝행+1) — 하단 2행(가점/면접·최종)은 데이터 아님."""
    return grid.header_row_count(), grid.row_cnt - 2


def collect_ground_truth(doc) -> dict:
    """큰 표의 '지원자 행'(성명이 있는 행)의 채워진 셀 → {셀ID: 값}.

    '이하빈칸' 마커 행, 이름 없이 관리번호만 미리 매겨진 행은 문서 관례이지
    지원자 데이터가 아니므로 채점 대상에서 제외.
    (마커 자동 복원은 프로덕션 채우기 로직의 TODO)
    """
    gt = {}
    for g in big_tables(doc):
        start, end = data_region(g)
        applicant_rows = set()
        for r in range(start, end):
            name_cell = g.owner(r, 1)
            name = name_cell.text.strip() if name_cell else ""
            if name and name not in MARKER_CHARS:
                applicant_rows.add(r)
        for (r, c), cell in g.cells.items():
            if r in applicant_rows and cell.text.strip():
                gt[f"{g.key}_r{r}_c{c}"] = cell.text
    return gt


def all_cell_texts(doc) -> dict:
    return {
        f"{g.key}_r{r}_c{c}": cell.text
        for g in doc.tables for (r, c), cell in g.cells.items()
    }


def grade(original_doc, result_doc, scope=None) -> tuple:
    """셀 단위 채점. scope가 있으면 해당 셀ID만, 없으면 전체 셀."""
    orig = all_cell_texts(original_doc)
    result = all_cell_texts(result_doc)
    keys = list(scope) if scope else list(orig)
    correct, diffs = 0, []
    for k in keys:
        if orig.get(k, "").strip() == result.get(k, "").strip():
            correct += 1
        else:
            diffs.append((k, orig.get(k, ""), result.get(k, "")))
    return correct, len(keys), diffs


# ── 마커 이동 회귀 테스트 ──────────────────────────

def run_marker_test(workdir: Path, original_doc, gt: dict) -> dict:
    """'이하빈칸' 마커 자동 이동 검증.

    새 양식 시뮬레이션(데이터 클리어 + 마커를 첫 데이터 행으로) → 채움 +
    relocate_below_markers → 마커가 원래 위치(마지막 데이터 행 아래)로
    돌아오는지 전체 셀 채점으로 확인.
    """
    template_map = {k: "" for k in gt}
    marker_tables = 0
    for g in original_doc.tables:
        marker = find_below_marker(g)
        if not marker:
            continue
        marker_tables += 1
        for c, _t in marker["cells"]:
            template_map[f"{g.key}_r{marker['row']}_c{c}"] = ""
        for c, t in marker["cells"]:
            template_map[f"{g.key}_r{g.header_row_count()}_c{c}"] = t

    template_path = workdir / "새양식.hwpx"
    fill_hwpx_cells(ORIGINAL, str(template_path), template_map)
    template_doc = parse_hwpx(str(template_path))

    moves: list[str] = []
    extra = relocate_below_markers(template_doc, gt, log=moves.append)
    merged = {**extra, **gt}  # 데이터가 마커 클리어보다 우선

    out_path = workdir / "마커이동.hwpx"
    fill_hwpx_cells(str(template_path), str(out_path), merged)
    result_doc = parse_hwpx(str(out_path))
    correct, total, diffs = grade(original_doc, result_doc)  # 전체 셀 비교
    return {"marker_tables": marker_tables, "moves": moves,
            "correct": correct, "total": total, "diffs": diffs,
            "result_file": str(out_path)}


# ── 레벨2: LLM 의미 매칭 ────────────────────────────

def build_roster(doc) -> list:
    """원본에서 과목별 명단 재구성 — LLM 입력용 (이름 + 위원 점수만).

    표 구조: 관리번호(0) 성명(1) [1단계점수(2)] 위원1..4 소계 평균 [합계] 순위
    9열 표(1차): 위원=2..5 / 11열 표(2차): 1단계=2, 위원=3..6
    """
    rosters = []
    for g in big_tables(doc):
        start, end = data_region(g)
        first_judge = 3 if g.col_cnt == 11 else 2
        # 맥락 버퍼에 이전 과목 요약이 남아있을 수 있으므로 마지막(최신) 매치 사용
        matches = re.findall(r"(러시아어|프랑스어|역사|체육)", g.context or "")
        subject = matches[-1] if matches else ""
        entries = []
        for r in range(start, end):
            name_cell = g.owner(r, 1)
            name = name_cell.text.strip() if name_cell else ""
            if not name or name in MARKER_CHARS:
                continue
            scores = []
            for j in range(4):
                sc = g.owner(r, first_judge + j)
                scores.append(sc.text.strip() if sc else "")
            stage1 = ""
            if g.col_cnt == 11:
                s1 = g.owner(r, 2)
                stage1 = s1.text.strip() if s1 else ""
            entries.append({"이름": name, "위원점수": scores, "서류점수": stage1})
        if entries:
            rosters.append({"table": g.key, "subject": subject,
                            "cols": g.col_cnt, "entries": entries})
    return rosters


def compute_derived(entries: list, cols: int) -> list:
    """소계·평균·순위(동점 공동순위)·관리번호를 코드로 계산."""
    out = []
    for i, e in enumerate(entries):
        scores = [float(s) for s in e["위원점수"] if s]
        subtotal = sum(scores)
        avg = round(subtotal / len(scores) + 1e-9, 1) if scores else 0
        avg_str = str(int(avg)) if avg == int(avg) else str(avg)
        total = None
        if cols == 11 and e.get("서류점수"):
            t = float(e["서류점수"]) + avg
            t = round(t + 1e-9, 1)
            total = str(int(t)) if t == int(t) else str(t)
        out.append({**e, "관리번호": str(i + 1),
                    "소계": str(int(subtotal)) if subtotal == int(subtotal) else str(subtotal),
                    "평균": avg_str, "합계": total})
    # 순위: 11열 표는 합계, 9열 표는 평균 기준 내림차순, 공동순위(1,2,2,4식)
    rank_key = (lambda e: float(e["합계"])) if cols == 11 else (lambda e: float(e["평균"]))
    sorted_vals = sorted((rank_key(e) for e in out), reverse=True)
    for e in out:
        e["순위"] = str(sorted_vals.index(rank_key(e)) + 1)
    return out


def _make_llm():
    import os
    from engine.llm_manager import LLMManager
    from engine.settings import SettingsManager

    try:
        config = SettingsManager().get_llm_config()
    except Exception:
        config = {}
    for k, env in [("claude_api_key", "ANTHROPIC_API_KEY"),
                   ("openai_api_key", "OPENAI_API_KEY"),
                   ("gemini_api_key", "GEMINI_API_KEY")]:
        if not config.get(k):
            config[k] = os.environ.get(env, "")
    config.setdefault("local_ctx", 8192)
    return LLMManager(models_dir=ROOT / "models", config=config)


ROSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "지원자": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "이름": {"type": "string"},
                    "위원점수": {
                        "type": "array", "items": {"type": "string"},
                        "minItems": 4, "maxItems": 4,
                    },
                    "서류점수": {"type": "string"},
                },
                "required": ["이름", "위원점수"],
            },
        }
    },
    "required": ["지원자"],
}


def llm_parse_roster(llm, provider: str, roster_text: str, has_stage1: bool) -> list:
    """LLM 역할: 비정형 명단 텍스트 → 구조화 JSON.

    행 배치·셀ID·계산은 전부 코드 몫 — LLM 출력은 수백 토큰으로 작다.
    (실제 제품에서 교사가 붙여넣는 명단을 파싱하는 것과 같은 작업)
    """
    stage1_note = "- 서류점수가 있으면 '서류점수'에 넣어라.\n" if has_stage1 else ""
    example = ('{"지원자":[{"이름":"홍길동","위원점수":["36","35","34","36"]'
               + (',"서류점수":"38"' if has_stage1 else "") + "}]}")
    prompt = (
        "다음 명단 텍스트에서 지원자별 정보를 추출해 JSON으로 정리하라.\n"
        "- 각 지원자의 '이름'과 '위원점수'(4명의 심사위원 점수, 순서 유지)를 추출.\n"
        + stage1_note +
        "- 명단에 나온 순서를 유지하라. 점수는 문자열 그대로.\n"
        f"- 출력 예: {example}\n\n"
        f"[명단]\n{roster_text}\n"
    )
    raw = llm.generate(prompt, max_tokens=2048, temperature=0.0,
                       provider=provider, json_schema=ROSTER_SCHEMA)
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
    data = json.loads(raw)
    return data.get("지원자", [])


def roster_to_text(roster: dict) -> str:
    """정답 명단 → 비정형 입력 텍스트 (교사가 붙여넣을 법한 형태)."""
    lines = [f"{roster['subject']} 기간제 지원자 면접 결과입니다."]
    for e in roster["entries"]:
        line = f"{e['이름']} {' '.join(e['위원점수'])}"
        if e.get("서류점수"):
            line += f" (서류 {e['서류점수']})"
        lines.append(line)
    return "\n".join(lines)


def run_level2(provider: str, workdir: Path, original_doc, gt: dict) -> dict:
    """빈 시험지에 [LLM 파싱 → 코드 배치·계산] 파이프라인으로 채우고 채점."""
    blank_path = workdir / "빈시험지.hwpx"
    fill_hwpx_cells(ORIGINAL, str(blank_path), {k: "" for k in gt})

    blank_doc = parse_hwpx(str(blank_path))
    rosters = build_roster(original_doc)
    llm = _make_llm()

    fill_map: dict = {}
    for roster in rosters:
        grid = next(g for g in blank_doc.tables if g.key == roster["table"])
        roster_text = roster_to_text(roster)
        print(f"  LLM 파싱: {roster['table']} ({roster['subject']}, "
              f"{len(roster['entries'])}명)...")
        try:
            entries = llm_parse_roster(llm, provider, roster_text,
                                       has_stage1=(roster["cols"] == 11))
        except Exception as e:
            print(f"    ✗ LLM 실패: {e}")
            continue
        if not entries:
            print("    ✗ 추출 결과 없음")
            continue

        # ── 여기부터 전부 코드: 행 배치, 셀ID, 파생값 계산 ──
        cols = roster["cols"]
        first_judge = 3 if cols == 11 else 2
        derived = compute_derived(
            [{"이름": e.get("이름", ""),
              "위원점수": list(e.get("위원점수", []))[:4],
              "서류점수": e.get("서류점수", "")} for e in entries], cols)
        start, _ = data_region(grid)
        col_map = ({"소계": 7, "평균": 8, "합계": 9, "순위": 10} if cols == 11
                   else {"소계": 6, "평균": 7, "순위": 8})
        for i, d in enumerate(derived):
            r = start + i
            key = roster["table"]
            fill_map[f"{key}_r{r}_c0"] = d["관리번호"]
            fill_map[f"{key}_r{r}_c1"] = d["이름"]
            if cols == 11 and d.get("서류점수"):
                fill_map[f"{key}_r{r}_c2"] = d["서류점수"]
            for j, s in enumerate(d["위원점수"]):
                fill_map[f"{key}_r{r}_c{first_judge + j}"] = s
            for name, c in col_map.items():
                if d.get(name) is not None:
                    fill_map[f"{key}_r{r}_c{c}"] = d[name]

    result_path = workdir / "LLM채움.hwpx"
    filled = fill_hwpx_cells(str(blank_path), str(result_path), fill_map)
    print(f"  주입: {filled}/{len(fill_map)}개")

    result_doc = parse_hwpx(str(result_path))
    correct, total, diffs = grade(original_doc, result_doc, scope=set(gt))
    return {"mode": f"level2:{provider}", "correct": correct, "total": total,
            "accuracy": round(correct / total * 100, 1) if total else 0,
            "diffs": diffs[:30], "result_file": str(result_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", nargs="?", const="local", default=None,
                    help="레벨2: LLM 의미 매칭 (local/claude/openai/gemini)")
    ap.add_argument("--keep", action="store_true", help="중간 파일 보존")
    args = ap.parse_args()

    original_doc = parse_hwpx(ORIGINAL)
    gt = collect_ground_truth(original_doc)
    print(f"정답 셀 {len(gt)}개 (큰 표 {len(big_tables(original_doc))}개의 데이터 행)")

    workdir = Path(tempfile.mkdtemp(prefix="bench_"))
    print(f"작업 폴더: {workdir}")

    # ── 레벨1: 기계 왕복 ──
    blank_path = workdir / "빈시험지.hwpx"
    cleared = fill_hwpx_cells(ORIGINAL, str(blank_path), {k: "" for k in gt})
    print(f"\n[레벨1] 빈 시험지 생성: {cleared}개 셀 클리어")

    blank_doc = parse_hwpx(str(blank_path))
    blank_ids = {f["id"] for f in extract_blank_fields(blank_doc) if f["is_empty"]}
    missing = [k for k in gt if k not in blank_ids]
    print(f"[레벨1] 빈칸 재인식: {len(gt) - len(missing)}/{len(gt)}"
          + (f" — 미인식: {missing[:5]}" if missing else ""))

    restored_path = workdir / "복원.hwpx"
    fill_hwpx_cells(str(blank_path), str(restored_path), gt)
    restored_doc = parse_hwpx(str(restored_path))
    correct, total, diffs = grade(original_doc, restored_doc)  # 전체 셀 — 부수 손상까지 검사
    print(f"[레벨1] 왕복 채점: {correct}/{total} ({correct/total*100:.1f}%)")
    if diffs:
        print("  불일치 샘플:")
        for k, o, r in diffs[:10]:
            print(f"    {k}: 원본='{o}' 결과='{r}'")

    results = {"level1": {"correct": correct, "total": total, "diffs": len(diffs)}}

    # ── 레벨1.7: 마커 이동 ──
    mk = run_marker_test(workdir, original_doc, gt)
    print(f"\n[마커] '이하빈칸' 이동 테스트 — 마커 표 {mk['marker_tables']}개")
    for mv in mk["moves"]:
        print(f"    {mv}")
    print(f"[마커] 채점: {mk['correct']}/{mk['total']}"
          f" ({mk['correct']/mk['total']*100:.1f}%)")
    if mk["diffs"]:
        for k, o, r in mk["diffs"][:10]:
            print(f"    {k}: 원본='{o}' 결과='{r}'")
    results["marker"] = {"marker_tables": mk["marker_tables"], "moves": mk["moves"],
                         "correct": mk["correct"], "total": mk["total"],
                         "diffs": len(mk["diffs"])}
    diffs = diffs + mk["diffs"]

    # ── 레벨2: LLM ──
    if args.llm:
        print(f"\n[레벨2] LLM 의미 매칭 (provider={args.llm})")
        results["level2"] = run_level2(args.llm, workdir, original_doc, gt)
        r2 = results["level2"]
        print(f"[레벨2] 채점: {r2['correct']}/{r2['total']} ({r2['accuracy']}%)")
        for k, o, r in r2["diffs"][:15]:
            print(f"    {k}: 원본='{o}' 결과='{r}'")

    out_json = ROOT / "scripts" / "benchmark_last_result.json"
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out_json}")
    if not args.keep and not args.llm:
        pass  # tempdir는 OS가 정리
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
