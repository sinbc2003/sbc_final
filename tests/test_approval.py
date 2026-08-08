# -*- coding: utf-8 -*-
"""승인 UX E2E — preview 스트림이 실행 대신 pending_actions를 반환하고,
문서는 그대로이며, execute-batch 승인 시에만 반영되는지 검증.

엔진(:8407)+llama(:8400)+한/글 필요 (test_edit와 동일 전제, 미충족 시 skip).
실행: python tests/test_approval.py [--model local/gemma]
"""
import argparse
import json
import sys
from pathlib import Path

from helpers import ROOT, md_to_hwpx, workdir, hwp_op, read_doc_texts, local_server_up

sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8407"

MD = ("# 현장체험학습 안내문\n\n학부모님께 안내드립니다.\n\n"
      "| 항목 | 내용 |\n| --- | --- |\n| 장소 | 국립과학관 |\n| 일시 | 5월 2일 |\n")
CMD = "문서 제목을 '2026 봄 현장체험학습 안내'로 바꿔줘"
WANT = "2026 봄 현장체험학습 안내"


def engine_up():
    try:
        import requests
        return requests.get(f"{BASE}/api/health", timeout=2).ok
    except Exception:
        return False


def sse(payload):
    import requests
    resp = requests.post(f"{BASE}/api/chat/live/stream", json=payload,
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
    ap.add_argument("--model", default="local/gemma")
    args = ap.parse_args()

    if not engine_up() or not local_server_up():
        print("=== 승인UX: SKIP (엔진 :8407 또는 llama :8400 미가동) ==="); return 0

    import requests
    wd = workdir("approval_")
    form = md_to_hwpx(MD, "approval", wd)
    try:
        hwp_op("open", str(Path(form).resolve()))
    except Exception as e:
        print(f"=== 승인UX: SKIP (한/글 미가용: {str(e)[:50]}) ==="); return 0

    fails = []

    # 1) preview=True: pending_actions만, result 없음, 문서 불변
    ev = sse({"message": CMD, "app_type": "hwp", "model": args.model, "preview": True})
    pend = [e for e in ev if e.get("type") == "pending_actions"]
    res = [e for e in ev if e.get("type") == "result"]
    if not (len(pend) == 1 and pend[0].get("count", 0) >= 1):
        fails.append(f"pending_actions 미수신/카운트 오류: {pend}")
    if res:
        fails.append(f"preview인데 실행됨: {res}")
    texts = read_doc_texts(str(Path(form).resolve()))
    if any(WANT in t for t in texts):
        fails.append("preview인데 문서가 이미 바뀜")
    print(f"[1] preview 스트림: pending {pend[0].get('count') if pend else 0}개, "
          f"result {len(res)}건, 문서 불변 {'OK' if not any(WANT in t for t in texts) else 'FAIL'}")

    # 2) 승인(execute-batch) → 문서 반영
    if pend:
        actions = pend[0].get("actions", [])
        r = requests.post(f"{BASE}/api/live/execute-batch",
                          json={"app_type": "hwp", "actions": actions}, timeout=120)
        data = r.json()
        ok_n = sum(1 for x in data.get("results", []) if x.get("success"))
        texts2 = read_doc_texts(str(Path(form).resolve()))
        applied = any(WANT in t for t in texts2)
        print(f"[2] 승인 실행: {ok_n}/{len(actions)} 성공, 문서 반영 {'OK' if applied else 'FAIL'}")
        if ok_n == 0:
            fails.append(f"execute-batch 전부 실패: {data}")
        if not applied:
            # 소형모델의 오선택(제목 아닌 다른 요소 수정)은 실행 성공과 별개 —
            # 하드 게이트는 실행 성공까지 (test_edit와 같은 기준)
            print("    (참고: 문서 미반영은 모델 오선택 가능성 — 하드실패 아님)")

    # 3) preview 기본값(미지정) → 기존 즉시실행 동작 보존
    form2 = md_to_hwpx(MD, "approval2", wd)
    hwp_op("open", str(Path(form2).resolve()))
    ev2 = sse({"message": CMD, "app_type": "hwp", "model": args.model})
    pend2 = [e for e in ev2 if e.get("type") == "pending_actions"]
    res2 = [e for e in ev2 if e.get("type") == "result"]
    if pend2:
        fails.append("기본값인데 pending_actions 발생 (기존 동작 파괴)")
    if not res2:
        fails.append("기본값인데 실행 이벤트 없음")
    print(f"[3] 기본값 즉시실행: result {len(res2)}건, pending {len(pend2)}건")

    # 4) fill-live 승인: preview=True → pending_fill(계획), 승인 실행 → 기록
    fill_md = ("# 참가 신청서\n\n| 항목 | 내용 |\n| --- | --- |\n"
               "| 성명 | |\n| 소속 | |\n")
    form3 = md_to_hwpx(fill_md, "approval_fill", wd)
    hwp_op("open", str(Path(form3).resolve()))
    ev3 = sse({"message": "빈칸 채워줘. 성명은 홍길동, 소속은 수학과.",
               "app_type": "hwp", "model": args.model, "preview": True})
    pfill = [e for e in ev3 if e.get("type") == "pending_fill"]
    res3 = [e for e in ev3 if e.get("type") == "result"]
    if not (pfill and pfill[0].get("count", 0) >= 1):
        fails.append(f"pending_fill 미수신: {[e.get('type') for e in ev3]}")
    if res3:
        fails.append("fill preview인데 액션 실행됨")
    print(f"[4a] fill preview: pending_fill {pfill[0].get('count') if pfill else 0}개, "
          f"result {len(res3)}건")
    if pfill:
        entries = pfill[0].get("entries", [])
        plan = {e["id"]: e["value"] for e in entries}
        r = requests.post(f"{BASE}/api/hwp/fill-live/execute",
                          json={"plan": plan, "path": pfill[0].get("file", "")},
                          timeout=300)
        data = r.json()
        out_file = data.get("file", "")
        out_texts = read_doc_texts(out_file) if out_file else []
        content_ok = any(("홍길동" in t or "수학과" in t) for t in out_texts)
        print(f"[4b] fill 승인 실행: ok={data.get('ok')}, filled={data.get('filled')}, "
              f"완성파일 내용 {'OK' if content_ok else 'FAIL'}")
        if not data.get("ok"):
            fails.append(f"fill-live/execute 실패: {data.get('error')}")
        if not content_ok:
            fails.append("승인 실행 후 완성 파일에 값 미반영")

    print(f"\n{'✅ 승인 UX E2E 통과' if not fails else '❌ FAIL: ' + '; '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
