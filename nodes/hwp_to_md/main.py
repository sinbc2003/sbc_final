"""
HWP → 마크다운 변환 노드.

구현 우선순위:
1. kordoc CLI (설치되어 있으면)
2. olefile (fallback)
"""

import shutil
import subprocess
from pathlib import Path


def _convert_with_kordoc(hwp_path: str) -> str | None:
    """kordoc CLI로 변환 시도."""
    # Windows에서 CreateProcess가 npx.cmd를 실행하려면 확장자 포함 전체 경로 필요
    npx = shutil.which("npx")
    if not npx:
        return None

    try:
        cmd = [npx, "kordoc", hwp_path, "--format", "json"]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            parsed = json.loads(result.stdout)
            md = parsed.get("markdown") if isinstance(parsed, dict) else None
            if isinstance(md, str) and md.strip():
                return md
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


def _convert_with_fallback(hwp_path: str) -> str:
    """olefile로 HWP 텍스트 추출."""
    try:
        import olefile

        ole = olefile.OleFileIO(hwp_path)
        parts = []

        # HWP 본문 스트림 탐색
        for stream in ole.listdir():
            stream_path = "/".join(stream)
            if "BodyText" in stream_path or "Section" in stream_path:
                try:
                    data = ole.openstream(stream).read()
                    # HWP 바이너리에서 텍스트 추출 시도
                    # 압축된 경우 zlib 해제
                    try:
                        import zlib
                        data = zlib.decompress(data, -15)
                    except Exception:
                        pass

                    # UTF-16LE로 디코딩 시도 후 제어문자 제거
                    try:
                        text = data.decode("utf-16-le", errors="ignore")
                        # 제어 문자 제거 (HWP 특수 코드)
                        cleaned = ""
                        for ch in text:
                            if ord(ch) >= 32 or ch in ("\n", "\r", "\t"):
                                cleaned += ch
                        cleaned = cleaned.strip()
                        if cleaned:
                            parts.append(cleaned)
                    except Exception:
                        pass
                except Exception:
                    continue

        ole.close()

        if parts:
            return "\n\n".join(parts)
        raise RuntimeError("본문 텍스트를 추출할 수 없음")

    except ImportError:
        raise RuntimeError(
            "olefile 미설치. pip install olefile 후 다시 시도하세요."
        )


def execute(inputs: dict, params: dict, context: dict) -> dict:
    hwp_path = inputs["파일"]

    if not Path(hwp_path).exists():
        raise FileNotFoundError(f"HWP 파일 없음: {hwp_path}")

    context["progress"](0.1)
    context["log"]("HWP 변환 시작")

    # kordoc 먼저 시도, 실패하면 olefile
    result = _convert_with_kordoc(hwp_path)
    if result is None:
        context["log"]("kordoc 미설치, olefile로 변환")
        result = _convert_with_fallback(hwp_path)

    context["progress"](1.0)
    context["log"](f"변환 완료 ({len(result)} 글자)")

    return {"텍스트": result}
