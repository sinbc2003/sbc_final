# -*- coding: utf-8 -*-
"""표 하드벤치용 실전 양식 첨부 수집 (Mac1용) — §31 ① 재료.

detail jsonl의 '첨부' 중 양식성 파일명(서식·양식·신청서·명단·조사표·현황·명부)
× 확장자(hwpx/hwp/xlsx)를 원문 다운로드 체인으로 수집한다.
pilot_download.py와 같은 3단계 체인·간격·멱등. 교육청별 상한으로 다양성 확보.

실행: python3 pilot_download_forms.py [--limit 500] [--dry]
산출: ~/shared/document_craw/form_attach/{registration_no}_{safe_filename}
      + form_manifest.jsonl
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
OUT = Path.home() / "shared" / "document_craw" / "form_attach"
MANIFEST = OUT / "form_manifest.jsonl"

FORM_RE = re.compile(r"서식|양식|신청서|명단|조사표|현황|명부")
EXTS = (".hwpx", ".hwp", ".xlsx")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": BASE + "/othicInfo/infoList/orginlInfoList.do",
    "X-Requested-With": "XMLHttpRequest",
}
PER_ORG_CAP = 40


def _s(v):
    if isinstance(v, list):
        return " ".join(map(str, v))
    return v if isinstance(v, str) else str(v or "")


def iter_candidates(per_org_cap: int):
    org_count: dict = {}
    for name in ("education_office_detail_INCREMENTAL.jsonl",
                 "education_office_detail.jsonl"):
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
                date = _s(df.get("생산일자"))
                if date[:4] < "2024":
                    continue
                org = _s(df.get("기관명"))
                key = org.split()[0] if org else "?"
                for a in (d.get("attachments") or []):
                    fn = a.get("filename", "")
                    if a.get("file_type") != "첨부":
                        continue
                    if not fn.lower().endswith(EXTS):
                        continue
                    if not FORM_RE.search(fn):
                        continue
                    if not a.get("download_params"):
                        continue
                    if org_count.get(key, 0) >= per_org_cap:
                        continue
                    org_count[key] = org_count.get(key, 0) + 1
                    yield d, df, a


def _result(j: dict) -> dict:
    if "modelAndView" in j:
        return ((j.get("modelAndView") or {}).get("model") or {}).get("result") or {}
    return j


def download_one(sess, d, df, a, out_path: Path) -> str:
    dp = a["download_params"]
    p1 = {
        "fileId": dp["fileId"], "esbFileName": dp["esbFileName"],
        "docId": dp.get("docId", ""), "ctDate": dp.get("ctDate", ""),
        "orgCd": dp.get("orgCd", ""),
        "prdnNstRgstNo": dp.get("prdnNstRgstNo", ""),
        "oppSeCd": dp.get("oppSeCd", ""), "isPdf": "N",
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
        "isPdf": "N", "prdnNstRgstNo": dp.get("prdnNstRgstNo", ""),
        "prdnDt": dp.get("ctDate", ""), "fileId": dp["fileId"],
        "gubun": "esbFilePath",
    }
    r = sess.post(f"{BASE}/util/wonmunUtils/wonmunFileDownload.down",
                  data=p7, headers={**HEADERS, "X-Requested-With": ""},
                  timeout=60)
    if r.status_code == 200 and len(r.content) > 2000 and b"<html" not in r.content[:200].lower():
        out_path.write_bytes(r.content)
        return "OK"
    return f"다운로드 실패({r.status_code}, {len(r.content)}b)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--per-org-cap", type=int, default=PER_ORG_CAP)
    ap.add_argument("--dry", action="store_true", help="후보 수만 집계")
    args = ap.parse_args()

    if args.dry:
        from collections import Counter
        c = Counter()
        n = 0
        for d, df, a in iter_candidates(args.per_org_cap):
            n += 1
            c[a["filename"].rsplit(".", 1)[-1].lower()] += 1
            if n >= 20000:
                break
        print(f"후보 {n}건 (상한 내) — 확장자 {dict(c)}")
        return 0

    OUT.mkdir(exist_ok=True)
    sess = requests.Session()
    sess.get(BASE + "/othicInfo/infoList/orginlInfoList.do",
             headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)

    ok = fail = 0
    with MANIFEST.open("a", encoding="utf-8") as mf:
        for d, df, a in iter_candidates(args.per_org_cap):
            if ok >= args.limit:
                break
            reg = d.get("registration_no") or a["file_id"]
            safe = re.sub(r'[<>:"/\\|?*\s]+', "_", a["filename"])[:80]
            out_path = OUT / f"{reg}_{safe}"
            if out_path.exists():
                ok += 1
                continue
            status = download_one(sess, d, df, a, out_path)
            if status == "OK":
                ok += 1
            else:
                fail += 1
            mf.write(json.dumps({
                "reg": reg, "file": a["filename"], "org": _s(df.get("기관명")),
                "title": _s(df.get("제목")), "status": status,
            }, ensure_ascii=False) + "\n")
            mf.flush()
            if (ok + fail) % 50 == 0:
                print(f"진행 {ok+fail} (성공 {ok} / 실패 {fail})", flush=True)
            time.sleep(args.sleep)
    print(f"완료: 성공 {ok} / 실패 {fail} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
