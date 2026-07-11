# -*- coding: utf-8 -*-
"""E2E 테스트 — 엔진(:8407) + llama-server(:8400) + 한/글 필요.

채팅 스트림 실경로 3종: 채움(fill-live 라우팅) / 편집(envelope+캘리브레이션) / 질문.
전제 미충족(서버 down 등) 시 자동 skip.
실행: python tests/test_e2e.py
"""
import json
import sys
import time
from pathlib import Path

from helpers import ROOT, md_to_hwpx, workdir, hwp_op, read_doc_texts, local_server_up

sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8407"
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}")


def engine_up() -> bool:
    try:
        import requests
        return requests.get(f"{BASE}/api/health", timeout=2).ok
    except Exception:
        return False


def sse(msg, app="hwp"):
    import requests
    resp = requests.post(f"{BASE}/api/chat/live/stream",
                         json={"message": msg, "app_type": app, "model": "local/gemma"},
                         stream=True, timeout=600)
    ev = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                ev.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return ev


MD = ("# 봉사활동 확인서\n\n학부모님께 안내드립니다.\n\n"
      "| 항목 | 내용 |\n| --- | --- |\n| 학생명 | ○○○ |\n| 활동기관 | ○○○ |\n")


def main():
    if not engine_up():
        print("=== E2E: SKIP (엔진 :8407 미가동) ==="); return 0
    if not local_server_up():
        print("=== E2E: SKIP (llama-server :8400 미가동) ==="); return 0

    wd = workdir("e2e_")
    form = md_to_hwpx(MD, "확인서", wd)
    try:
        hwp_op("open", str(Path(form).resolve()))
    except Exception as e:
        print(f"=== E2E: SKIP (한/글 미가용: {str(e)[:60]}) ==="); return 0

    # 1) 채움
    print("[채움]")
    ev = sse("김도윤 학생이 행복요양원에서 봉사했어. 확인서 빈칸 채워줘")
    reply = next((e.get("content") for e in ev if e.get("type") == "reply_done"), "")
    done = next((e.get("summary") for e in ev if e.get("type") == "done"), "")
    check("fill-live 라우팅+채움", "채웠습니다" in reply and "채움" in done)

    # 2) 편집 (envelope + 캘리브레이션)
    print("[편집]")
    ev = sse("문서 제목을 '2026 봉사활동 확인서'로 바꿔줘")
    res = [e for e in ev if e.get("type") == "result"]
    check("편집 액션 실행", bool(res) and all(r.get("success") for r in res))
    texts = read_doc_texts(str(Path(wd / "봉사활동 확인서_완성.hwpx"))) if False else read_doc_texts(str(Path(form).resolve()))
    check("제목 실변경", any("2026 봉사활동 확인서" in t for t in texts))

    # 3) 질문
    print("[질문]")
    ev = sse("이 문서 제목이 뭐야?")
    reply = next((e.get("content") for e in ev if e.get("type") == "reply_done"), "")
    no_act = not any(e.get("type") == "actions" for e in ev)
    check("질문(액션0)+정답", no_act and ("봉사" in reply or "확인서" in reply))

    print(f"\n=== E2E: {len(PASS)} PASS, {len(FAIL)} FAIL ===")
    if FAIL:
        print("실패:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
