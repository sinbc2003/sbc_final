# -*- coding: utf-8 -*-
"""kordoc 신버전 자동 감지 → 회귀 검증 → 제안 (§40 ⑤).

설계 원칙: **감지·검증은 자동, 적용은 승인.**
외부 의존성 버전을 무인 자동 상향하면 조용한 회귀(우리 v7 HTML표 사건 같은
것)가 배포까지 흘러간다. 그래서 이 스크립트는 신버전을 격리 설치해 우리
벤치를 돌리고, **통과했을 때만 "올려도 된다"고 제안**한다.

검증 항목(우리 실제 사용면 전부):
  1) 변환 동등성 — 실전 양식 N종 hwp→md, 현행 대비 길이·표 손실 비교
  2) lint  — 우리 공문 후처리 산출이 여전히 0건 통과하는가
  3) validate — 우리가 만든 hwpx가 여전히 통과하는가
  4) redact — 구조화 PII 탐지 수가 줄지 않았는가
  5) 오프라인 테스트 스위트(파이썬) 무손상

실행:
  python scripts/kordoc_watch.py            # 감지만 (신버전 없으면 즉시 종료)
  python scripts/kordoc_watch.py --verify   # 신버전 격리 설치 후 회귀 검증
  python scripts/kordoc_watch.py --notify   # 결과를 텔레그램으로
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "data" / "kordoc_watch.json"
SAMPLES_DIR = Path(r"D:\lora_data\form_v9\hwpx")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 우리 공문 후처리 산출 표본 — lint가 계속 0건이어야 한다
GONGMUN_SAMPLE = """1. 관련: (학교명)-○○○○(○○○○. ○. ○.)
2. 2026학년도 체육대회를 다음과 같이 실시하고자 합니다.
  가. 일시: 2026. 5. 2.(토) 09:00
  나. 장소: 본교 운동장
붙임  체육대회 운영 계획 1부.  끝."""


def _run(args, cwd=None, timeout=600, stdin_text=None):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, cwd=cwd,
                          input=stdin_text, creationflags=_NO_WINDOW)


def installed_version() -> str | None:
    from engine import kordoc  # 리포 고정본
    return kordoc.version()


def latest_version() -> str | None:
    """npm 레지스트리에서 latest 태그 조회 (npm CLI 없이 HTTP)."""
    try:
        with urllib.request.urlopen(
                "https://registry.npmjs.org/kordoc/latest", timeout=30) as r:
            return json.load(r).get("version")
    except Exception as e:
        print(f"[경고] 레지스트리 조회 실패: {e}")
        return None


def release_notes(version: str) -> str:
    """해당 버전 배포 메타에서 설명 추출(있으면). 없으면 빈 문자열."""
    try:
        with urllib.request.urlopen(
                f"https://registry.npmjs.org/kordoc/{version}", timeout=30) as r:
            d = json.load(r)
        return (d.get("description") or "")[:300]
    except Exception:
        return ""


def _isolated_install(version: str, workdir: Path) -> str | None:
    """신버전을 임시 디렉토리에 격리 설치 → 실행 파일 경로. 현행 환경 불변."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "package.json").write_text('{"name":"kordoc-probe","private":true}',
                                          encoding="utf-8")
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    r = _run([npm, "install", "--no-audit", "--no-fund", "--save-exact",
              f"kordoc@{version}"], cwd=str(workdir), timeout=900)
    if r.returncode != 0:
        print(f"[실패] 격리 설치: {(r.stderr or '')[-300:]}")
        return None
    for name in ("kordoc.cmd", "kordoc"):
        p = workdir / "node_modules" / ".bin" / name
        if p.exists():
            return str(p)
    return None


def _probe(binpath: str, samples: list[Path]) -> dict:
    """신버전 바이너리로 우리 사용면 4종 측정."""
    out = {"convert": [], "lint_issues": None, "validate_ok": None, "redact_hits": None}
    # 1) 변환 — 표본별 md 길이·표 마커 수
    for p in samples:
        r = _run([binpath, str(p), "--format", "markdown", "--silent"], timeout=180)
        md = r.stdout or ""
        out["convert"].append({
            "file": p.name, "chars": len(md),
            "tables": md.count("<table") + md.count("\n|"),
        })
    # 2) lint — 우리 후처리 산출
    r = _run([binpath, "lint", "-", "--json"], timeout=120, stdin_text=GONGMUN_SAMPLE)
    try:
        out["lint_issues"] = len(json.loads(r.stdout or "{}").get("findings", []))
    except Exception:
        out["lint_issues"] = -1
    # 3) validate — 우리가 만든 hwpx
    if samples:
        r = _run([binpath, "validate", str(samples[0]), "--json"], timeout=120)
        try:
            out["validate_ok"] = bool(
                json.loads(r.stdout or "{}").get("summary", {}).get("ok", r.returncode == 0))
        except Exception:
            out["validate_ok"] = r.returncode == 0
    # 4) redact — 구조화 PII 탐지 수
    if samples:
        r = _run([binpath, "redact", str(samples[0]), "--dry-run", "--json", "--silent"],
                 timeout=180)
        try:
            out["redact_hits"] = len(json.loads(r.stdout or "{}").get("hits", []))
        except Exception:
            out["redact_hits"] = -1
    return out


def _current_probe(samples: list[Path]) -> dict:
    from engine import kordoc
    cmd = kordoc._resolve_cmd()
    return _probe(cmd[0] if len(cmd) == 1 else cmd[0], samples) if cmd else {}


def verify(new_version: str, n_samples: int = 5) -> dict:
    """신버전 격리 설치 후 현행과 비교. 반환: {pass, diffs, detail}."""
    samples = sorted(SAMPLES_DIR.glob("*.hwpx"))[:n_samples]
    if not samples:
        return {"pass": False, "diffs": ["표본 없음 — SAMPLES_DIR 확인"], "detail": {}}

    print(f"표본 {len(samples)}종으로 현행 측정...")
    cur = _current_probe(samples)
    with tempfile.TemporaryDirectory(prefix="kordoc_probe_") as td:
        print(f"kordoc@{new_version} 격리 설치...")
        binpath = _isolated_install(new_version, Path(td))
        if not binpath:
            return {"pass": False, "diffs": ["격리 설치 실패"], "detail": {}}
        print("신버전 측정...")
        new = _probe(binpath, samples)

    diffs = []
    # 변환 회귀: 길이 20% 이상 감소 or 표 마커 감소
    for a, b in zip(cur.get("convert", []), new.get("convert", [])):
        if b["chars"] < a["chars"] * 0.8:
            diffs.append(f"변환 축소 {a['file'][:30]}: {a['chars']}→{b['chars']}자")
        if b["tables"] < a["tables"]:
            diffs.append(f"표 손실 {a['file'][:30]}: {a['tables']}→{b['tables']}")
    if new.get("lint_issues", 0) > (cur.get("lint_issues") or 0):
        diffs.append(f"lint 신규 지적: {cur.get('lint_issues')}→{new['lint_issues']}건 "
                     "(우리 후처리 규칙 갱신 필요 신호)")
    if cur.get("validate_ok") and not new.get("validate_ok"):
        diffs.append("validate 회귀: 통과하던 문서가 실패")
    if (cur.get("redact_hits") or 0) > (new.get("redact_hits") or 0):
        diffs.append(f"redact 탐지 감소: {cur.get('redact_hits')}→{new.get('redact_hits')}")

    # 파이썬 오프라인 스위트(현행 코드 무손상 확인 — 신버전과 무관하지만 기준선)
    r = _run([sys.executable, "tests/test_offline.py"], cwd=str(REPO), timeout=900)
    offline_ok = "0 FAIL" in (r.stdout or "")
    if not offline_ok:
        diffs.append("오프라인 스위트 실패 — 현행 코드 문제 (버전 무관)")

    return {"pass": not diffs, "diffs": diffs,
            "detail": {"current": cur, "new": new, "offline_ok": offline_ok}}


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(d: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="신버전 격리 검증까지")
    ap.add_argument("--notify", action="store_true", help="결과 텔레그램 전송")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    cur = installed_version()
    latest = latest_version()
    print(f"현재 {cur} / 최신 {latest}")
    if not latest:
        return 1

    state = load_state()
    if latest == cur:
        state["last_check_version"] = latest
        save_state(state)
        print("신버전 없음.")
        return 0

    notes = release_notes(latest)
    lines = [f"kordoc 신버전 감지: {cur} → {latest}"]
    if notes:
        lines.append(f"설명: {notes}")

    if args.verify:
        res = verify(latest, args.samples)
        lines.append("")
        if res["pass"]:
            lines.append("회귀 검증 통과 — 업그레이드 권장")
            lines.append(f"적용: npm i --save-exact kordoc@{latest}")
        else:
            lines.append("회귀 검증 실패 — 업그레이드 보류")
            lines += [f"  - {d}" for d in res["diffs"][:6]]
        state["last_verified"] = {"version": latest, "pass": res["pass"],
                                  "diffs": res["diffs"]}

    state["last_seen_version"] = latest
    save_state(state)
    report = "\n".join(lines)
    print("\n" + report)

    if args.notify:
        try:
            sys.path.insert(0, str(REPO / "scripts"))
            from kordoc_notify import send  # 선택적 헬퍼
            send(report)
        except Exception as e:
            print(f"[경고] 알림 실패: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
