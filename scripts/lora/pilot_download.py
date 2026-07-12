# -*- coding: utf-8 -*-
"""전국 공문 시범 다운로드 (Mac1용) — open.go.kr 결재문서본문.pdf 1,000건.

document_craw detail.jsonl에서 고등학교 생산 + 계획/운영/안내류 제목 필터 →
원문 다운로드 3단계 체인(wonmunFileRequest → Response 폴링 → Download) 재현.
문서당 2초 이상 간격(포털 부하 예방), 재실행 시 기존 파일 건너뜀(멱등).

실행: python3 pilot_download.py [--limit 1000]
산출: ~/shared/document_craw/pilot_pdf/{registration_no}.pdf + pilot_manifest.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://www.open.go.kr"
DATA = Path.home() / "shared" / "document_craw" / "data"
OUT = Path.home() / "shared" / "document_craw" / "pilot_pdf"
MANIFEST = OUT / "pilot_manifest.jsonl"

TITLE_RE = re.compile(r"계획|운영|안내|실시|결과 보고|추진")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": BASE + "/othicInfo/infoList/orginlInfoList.do",
    "X-Requested-With": "XMLHttpRequest",
}


PER_ORG_CAP = 60  # 교육청별 상한 — 파일이 지역별로 뭉쳐 있어 다양성 확보


def iter_candidates():
    """detail jsonl 순회 — 제목 필터 × 최근 생산 × 본문 PDF × 교육청별 상한."""
    org_count: dict = {}
    for name in ("education_office_detail.jsonl",
                 "education_office_detail_INCREMENTAL.jsonl"):
        p = DATA / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                df = d.get("detail_fields") or {}

                def _s(v):  # 크롤 데이터 필드가 간혹 list 등 비문자열
                    if isinstance(v, list):
                        return " ".join(map(str, v))
                    return v if isinstance(v, str) else str(v or "")

                org = _s(df.get("기관명"))
                title = _s(df.get("제목"))
                date = _s(df.get("생산일자"))
                if not TITLE_RE.search(title):
                    continue
                if date[:4] < "2024":
                    continue
                key = org.split()[0] if org else "?"
                if org_count.get(key, 0) >= PER_ORG_CAP:
                    continue
                body = next((a for a in (d.get("attachments") or [])
                             if a.get("file_type") == "본문"
                             and a.get("filename", "").endswith(".pdf")), None)
                if not body:
                    continue
                org_count[key] = org_count.get(key, 0) + 1
                yield d, df, body


def _result(j: dict) -> dict:
    """open.go.kr AJAX 응답 언랩 — modelAndView.model.result 중첩 대응."""
    if "modelAndView" in j:
        return ((j.get("modelAndView") or {}).get("model") or {}).get("result") or {}
    return j


def download_one(sess: requests.Session, d: dict, df: dict, body: dict,
                 out_path: Path) -> str:
    dp = body["download_params"]
    p1 = {
        "fileId": dp["fileId"], "esbFileName": dp["esbFileName"],
        "docId": dp.get("docId", ""), "ctDate": dp.get("ctDate", ""),
        "orgCd": dp.get("orgCd", ""),
        "prdnNstRgstNo": dp.get("prdnNstRgstNo", ""),
        "oppSeCd": dp.get("oppSeCd", ""), "isPdf": "Y",
        "chrgDeptNm": df.get("담당부서명", ""),
    }
    r = sess.post(f"{BASE}/util/wonmunUtils/wonmunFileRequest.ajax",
                  data=p1, headers=HEADERS, timeout=30)
    try:
        j = _result(r.json())
    except Exception:
        return f"step1 비JSON({r.status_code})"
    emsg = j.get("error_msg") or ""
    if "실패" in emsg or "문의" in emsg:
        return f"영구실패: {emsg.splitlines()[0][:40]}"
    if str(j.get("error_code", "")) not in ("0", "00"):
        # 스테이징 폴링 (step2) — 원기관에서 파일 가져오는 대기 (최대 ~90초)
        for _ in range(30):
            time.sleep(3)
            p2 = dict(p1)
            p2.update({"esbFilePath": j.get("esbFilePath", ""),
                       "fileName": j.get("fileName", dp["esbFileName"]),
                       "step": "step2"})
            r = sess.post(f"{BASE}/util/wonmunUtils/wonmunFileResponse.ajax",
                          data=p2, headers=HEADERS, timeout=30)
            try:
                j = _result(r.json())
            except Exception:
                return f"step2 비JSON({r.status_code})"
            emsg = j.get("error_msg") or ""
            if "실패" in emsg or "문의" in emsg:
                return f"영구실패: {emsg.splitlines()[0][:40]}"
            if str(j.get("error_code", "")) in ("0", "00"):
                break
        else:
            return f"스테이징 타임아웃({j.get('error_code')})"

    p7 = {
        "esbFilePath": j.get("esbFilePath", ""),
        "esbFileName": j.get("esbFileName", dp["esbFileName"]),
        "fileName": j.get("fileName", dp["esbFileName"]),
        "isPdf": "Y", "prdnNstRgstNo": dp.get("prdnNstRgstNo", ""),
        "prdnDt": dp.get("ctDate", ""), "fileId": dp["fileId"],
        "gubun": "esbFilePath",
    }
    r = sess.post(f"{BASE}/util/wonmunUtils/wonmunFileDownload.down",
                  data=p7, headers={**HEADERS,
                                    "X-Requested-With": ""},
                  timeout=60)
    ct = r.headers.get("Content-Type", "")
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        out_path.write_bytes(r.content)
        return "OK"
    return f"다운로드 실패({r.status_code}, {ct[:30]}, {len(r.content)}b)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    sess = requests.Session()
    sess.get(BASE + "/othicInfo/infoList/orginlInfoList.do",
             headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)

    done = ok = fail = 0
    with MANIFEST.open("a", encoding="utf-8") as mf:
        for d, df, body in iter_candidates():
            if ok >= args.limit:
                break
            reg = d.get("registration_no") or body["file_id"]
            out_path = OUT / f"{reg}.pdf"
            if out_path.exists():
                ok += 1
                continue
            status = download_one(sess, d, df, body, out_path)
            done += 1
            if status == "OK":
                ok += 1
            else:
                fail += 1
            mf.write(json.dumps({
                "reg": reg, "status": status, "title": df.get("제목"),
                "org": df.get("기관명"), "date": df.get("생산일자"),
            }, ensure_ascii=False) + "\n")
            mf.flush()
            if done % 20 == 0:
                print(f"진행 {done} (성공 {ok} / 실패 {fail})", flush=True)
            time.sleep(args.sleep)

    print(f"완료: 성공 {ok} / 실패 {fail} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
