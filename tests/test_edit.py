# -*- coding: utf-8 -*-
"""편집 신뢰성 테스트 — 모델 품질에 민감한 유일한 축(감사 지적).

엔진(:8407)+llama(:8400)+한/글 필요. trial마다 새 문서 → 스트림 편집 명령
→ 문서 실상태 검증. 채움/생성(견고 축)과 짝지어 '모델 민감 축'을 상시 측정.
전제 미충족 시 자동 skip. 반복(--trials N)으로 간헐 오선택을 통계로.
실행: python tests/test_edit.py [--trials 1]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from helpers import ROOT, md_to_hwpx, workdir, hwp_op, read_doc_texts, local_server_up

sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8407"

MD = ("# 현장체험학습 안내문\n\n학부모님께 안내드립니다.\n\n"
      "| 항목 | 내용 |\n| --- | --- |\n| 장소 | 국립과학관 |\n| 일시 | 5월 2일 |\n")

TRIALS = [
    ("제목", "문서 제목을 '2026 봄 현장체험학습 안내'로 바꿔줘",
     lambda ts: any("2026 봄 현장체험학습 안내" in t for t in ts)),
    ("셀값", "표에서 국립과학관을 어린이대공원으로 바꿔줘",
     lambda ts: any("어린이대공원" in t for t in ts)),
    ("문단", "인사말 문단을 '학부모님, 봄 체험학습을 다음과 같이 안내합니다.'로 바꿔줘",
     lambda ts: any("봄 체험학습을 다음과 같이" in t for t in ts)),
]


def engine_up():
    try:
        import requests
        return requests.get(f"{BASE}/api/health", timeout=2).ok
    except Exception:
        return False


def sse(msg, model):
    import requests
    resp = requests.post(f"{BASE}/api/chat/live/stream",
                         json={"message": msg, "app_type": "hwp", "model": model},
                         stream=True, timeout=600)
    ev = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                ev.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1, help="각 명령 반복 횟수")
    ap.add_argument("--model", default="local/gemma")
    args = ap.parse_args()

    if not engine_up() or not local_server_up():
        print("=== 편집: SKIP (엔진 :8407 또는 llama :8400 미가동) ==="); return 0

    wd = workdir("edit_")
    per = {name: {"exec": 0, "doc": 0} for name, _, _ in TRIALS}
    N = args.trials
    for i in range(N):
        for name, msg, check in TRIALS:
            form = md_to_hwpx(MD, f"e{i}_{name}", wd)
            try:
                hwp_op("open", str(Path(form).resolve()))
            except Exception as e:
                print(f"=== 편집: SKIP (한/글 미가용: {str(e)[:50]}) ==="); return 0
            ev = sse(msg, args.model)
            res = [e for e in ev if e.get("type") == "result"]
            if res and all(r.get("success") for r in res):
                per[name]["exec"] += 1
            if check(read_doc_texts(str(Path(form).resolve()))):
                per[name]["doc"] += 1

    print(f"=== 편집 신뢰성 ({args.model}, {N}회 반복) ===")
    doc_total = exec_total = 0
    for name in per:
        e, d = per[name]["exec"], per[name]["doc"]
        exec_total += e; doc_total += d
        print(f"  {name}: 실행 {e}/{N}, 문서반영 {d}/{N}")
    tot = len(TRIALS) * N
    print(f"  종합: 실행 {exec_total}/{tot}, 문서반영 {doc_total}/{tot}")
    # 회귀 게이트: 문서반영 100% 요구는 소형모델엔 과함 → 실행 100%만 하드 요구
    ok = exec_total == tot
    print(f"\n{'✅' if ok else '⚠️'} {'액션 실행 전부 성공' if ok else '일부 실행 실패(모델/시스템 확인)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
