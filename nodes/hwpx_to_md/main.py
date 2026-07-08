"""
HWPX → 마크다운 변환 노드.

구현 우선순위:
1. kordoc CLI (설치되어 있으면)
2. ZIP + XML 파싱 (fallback)
"""

import shutil
import subprocess
import zipfile
import re
from pathlib import Path
from xml.etree import ElementTree as ET


def _convert_with_kordoc(hwpx_path: str) -> str | None:
    """kordoc CLI로 변환 시도."""
    # Windows에서 CreateProcess가 npx.cmd를 실행하려면 확장자 포함 전체 경로 필요
    # (["npx", ...]는 .exe만 탐색해 FileNotFoundError → 항상 폴백으로 강등됨)
    npx = shutil.which("npx")
    if not npx:
        return None

    try:
        cmd = [npx, "kordoc", hwpx_path, "--format", "json"]
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


def _extract_text_from_xml(xml_content: bytes) -> str:
    """HWPX section XML에서 텍스트 추출."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return ""

    # 모든 텍스트 노드 수집 (네임스페이스 무시)
    texts = []
    for elem in root.iter():
        # <hp:t> 또는 <t> 태그에서 텍스트 추출
        tag = elem.tag
        local_name = tag.split("}")[-1] if "}" in tag else tag

        if local_name == "t" and elem.text:
            texts.append(elem.text)
        elif local_name == "p" and texts:
            # 문단 구분
            texts.append("\n")

    return "".join(texts).strip()


def _convert_with_fallback(hwpx_path: str) -> str:
    """ZIP 열어서 Contents/section*.xml에서 텍스트 추출."""
    try:
        with zipfile.ZipFile(hwpx_path, "r") as zf:
            # section 파일 목록 수집
            section_files = sorted([
                name for name in zf.namelist()
                if re.match(r"Contents/section\d*\.xml", name, re.IGNORECASE)
                or re.match(r"Contents/Section\d*\.xml", name)
            ])

            if not section_files:
                # Contents 폴더 내 모든 xml 시도
                section_files = sorted([
                    name for name in zf.namelist()
                    if name.startswith("Contents/") and name.endswith(".xml")
                ])

            if not section_files:
                raise RuntimeError(
                    "HWPX 내부에서 section XML을 찾을 수 없음"
                )

            parts = []
            for sf in section_files:
                xml_data = zf.read(sf)
                text = _extract_text_from_xml(xml_data)
                if text:
                    parts.append(text)

            if parts:
                return "\n\n---\n\n".join(parts)
            raise RuntimeError("HWPX에서 텍스트를 추출할 수 없음")

    except zipfile.BadZipFile:
        raise RuntimeError("올바른 HWPX(ZIP) 파일이 아닙니다.")


def execute(inputs: dict, params: dict, context: dict) -> dict:
    hwpx_path = inputs["파일"]

    if not Path(hwpx_path).exists():
        raise FileNotFoundError(f"HWPX 파일 없음: {hwpx_path}")

    context["progress"](0.1)
    context["log"]("HWPX 변환 시작")

    # kordoc 시도, 없으면 ZIP+XML 직접 파싱
    result = _convert_with_kordoc(hwpx_path)
    if result is None:
        context["log"]("ZIP+XML 파싱으로 변환")
        result = _convert_with_fallback(hwpx_path)

    context["progress"](1.0)
    context["log"](f"변환 완료 ({len(result)} 글자)")

    return {"텍스트": result}
