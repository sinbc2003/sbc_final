"""kordoc CLI 단일 래퍼 — 결정론 문서 레이어(파싱·검수·마스킹·검증) 위임.

원칙(사용자 미션): 프론티어=설계, 로컬 LLM=추론/의미, **나머지 결정론은 검증된
코드(kordoc)에 위임**. 손으로 만든 후처리를 재발명·유지보수하는 대신 흡수한다.

버전 고정: 리포 node_modules의 kordoc(package.json devDep, --save-exact)을
우선 사용 → 재현성 보장. 없으면 npx 온디맨드 → 그래도 없으면 None(호출측 폴백).

frozen(배포) 시 node_modules가 번들에 없으면 kordoc 경로는 자동 비활성 —
호출측은 항상 폴백(내장 파서/후처리)을 가진다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 리포 루트(engine/의 부모) 하위 node_modules에 고정 설치된 kordoc
_REPO = Path(__file__).resolve().parent.parent


def _local_bin() -> str | None:
    """리포 고정 kordoc 실행 파일 경로(있으면). Windows는 .cmd."""
    base = _REPO / "node_modules" / ".bin"
    for name in ("kordoc.cmd", "kordoc"):
        p = base / name
        if p.exists():
            return str(p)
    return None


def _resolve_cmd() -> list[str] | None:
    """kordoc 실행 커맨드 프리픽스. 고정본 우선, 없으면 npx, 둘 다 없으면 None."""
    local = _local_bin()
    if local:
        return [local]
    npx = shutil.which("npx")
    if npx:
        return [npx, "kordoc"]
    return None


def available() -> bool:
    return _resolve_cmd() is not None


def version() -> str | None:
    cmd = _resolve_cmd()
    if not cmd:
        return None
    try:
        r = subprocess.run(cmd + ["--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60,
                           creationflags=_NO_WINDOW)
        return r.stdout.strip() or None
    except Exception:
        return None


def _run(args: list[str], timeout: int = 120,
         stdin_text: str | None = None) -> subprocess.CompletedProcess | None:
    """kordoc 서브프로세스 실행. 실패 시 None(호출측 폴백)."""
    cmd = _resolve_cmd()
    if not cmd:
        return None
    try:
        return subprocess.run(
            cmd + args, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            input=stdin_text, creationflags=_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


# ── 변환 ──

def to_markdown(path: str, extra: list[str] | None = None,
                timeout: int = 120) -> str | None:
    """문서 → 마크다운. JSON 경로로 받아 markdown 필드 추출."""
    r = _run([path, "--format", "json", *(extra or [])], timeout=timeout)
    if not r or r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        parsed = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    md = parsed.get("markdown") if isinstance(parsed, dict) else None
    return md if isinstance(md, str) and md.strip() else None


def to_chunks(path: str, timeout: int = 120) -> list[dict] | None:
    """RAG용 구조 청크 — 헤딩 위계 breadcrumb + 표 독립 청크. 큰 문서 슬라이싱용."""
    r = _run([path, "--format", "chunks", "--silent"], timeout=timeout)
    if not r or r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        parsed = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    for key in ("chunks", "data"):
        if isinstance(parsed, dict) and isinstance(parsed.get(key), list):
            return parsed[key]
    return None


# ── 검수·검증 (결정론 게이트) ──

def lint(md_or_txt: str, timeout: int = 60) -> dict | None:
    """행정업무운영 편람 표기법 검수 — 날짜·시간·금액·붙임 등.

    stdin('-')으로 텍스트 전달. 반환: {ok, issues:[...], raw}.
    kordoc lint는 error 있으면 exit 1 — returncode로 판정하지 않고 출력 파싱.
    """
    r = _run(["lint", "-", "--json"], timeout=timeout, stdin_text=md_or_txt)
    if r is None:
        return None
    return _parse_findings(r, ok_default=r.returncode == 0)


def _parse_findings(r, ok_default: bool) -> dict:
    """kordoc --json 공통 형태 {findings:[{line,match,rule,severity,message,suggest}],
    summary:{total,errors,ok}} 정규화. 비-JSON 출력은 줄 목록으로 폴백."""
    out = (r.stdout or "").strip()
    if not out:
        return {"ok": ok_default, "issues": [], "raw": ""}
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": ok_default,
                "issues": [ln for ln in out.splitlines() if ln.strip()], "raw": out}
    if isinstance(parsed, list):
        return {"ok": not parsed, "issues": parsed, "raw": out}
    # lint=findings / redact=hits / 기타=issues
    issues = (parsed.get("findings") or parsed.get("hits")
              or parsed.get("issues") or [])
    if not isinstance(issues, list):
        issues = []
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
    ok = summary.get("ok", parsed.get("ok", parsed.get("valid", ok_default)))
    return {"ok": bool(ok), "issues": issues, "summary": summary, "raw": out}


def validate_hwpx(path: str, timeout: int = 60) -> dict:
    """HWPX 구조 검증 — ZIP·mimetype·필수 파일·XML 웰폼드·manifest 참조.

    한컴독스 거부 요인 사전 차단(저장 후 게이트). kordoc 없으면 available=False로
    표시하고 통과 취급(게이트가 기능을 막지 않는다)."""
    r = _run(["validate", path, "--json"], timeout=timeout)
    if r is None:
        return {"available": False, "ok": True, "issues": []}
    res = _parse_findings(r, ok_default=r.returncode == 0)
    return {"available": True, "ok": res["ok"], "issues": res["issues"]}


def redact(path: str, out_path: str, timeout: int = 120) -> dict:
    """개인정보 서식보존 마스킹 — 주민번호·전화·이메일·카드·계좌.

    HWPX/HWP는 원본 서식 유지 patch. 자동 검출 보조 — 사람 최종 확인 필요.
    반환: {available, ok, out}."""
    r = _run(["redact", path, "-o", out_path, "--json", "--silent"], timeout=timeout)
    if r is None:
        return {"available": False, "ok": False, "out": None, "found": []}
    found = _parse_findings(r, ok_default=True)["issues"]
    ok = r.returncode == 0 and Path(out_path).exists()
    return {"available": True, "ok": ok, "out": out_path if ok else None,
            "found": found, "stderr": (r.stderr or "")[-300:]}


def redact_report(path: str, timeout: int = 120) -> dict:
    """탐지만(파일 미생성) — 우리 마스킹과 A/B 비교용."""
    r = _run(["redact", path, "--dry-run", "--json", "--silent"], timeout=timeout)
    if r is None:
        return {"available": False, "found": []}
    return {"available": True, "found": _parse_findings(r, ok_default=True)["issues"]}
