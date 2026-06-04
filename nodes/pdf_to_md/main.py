"""
PDF → 마크다운 변환 노드.

구현 우선순위:
1. kordoc CLI (설치되어 있으면)
2. pymupdf (fallback)
"""

import shutil
import subprocess
import re
from pathlib import Path


def _parse_page_range(pages_str: str, total_pages: int) -> list[int]:
    """'1-5, 3, 10-15' → [0, 1, 2, 3, 4, 2, 9, 10, 11, 12, 13, 14] (0-indexed)."""
    if not pages_str or pages_str.strip() == "전체":
        return list(range(total_pages))

    result = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start, end = int(start.strip()), int(end.strip())
            result.extend(range(start - 1, min(end, total_pages)))
        else:
            idx = int(part.strip()) - 1
            if 0 <= idx < total_pages:
                result.append(idx)
    return result


def _convert_with_kordoc(pdf_path: str, pages: str) -> str | None:
    """kordoc CLI로 변환 시도."""
    if not shutil.which("npx"):
        return None

    try:
        cmd = ["npx", "kordoc", pdf_path, "--format", "json"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            parsed = json.loads(result.stdout)
            return parsed.get("markdown", result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


def _convert_with_pymupdf(pdf_path: str, pages: str) -> str:
    """pymupdf(fitz)로 변환."""
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    total = len(doc)
    page_indices = _parse_page_range(pages, total)

    parts = []
    for i in page_indices:
        page = doc[i]

        # 텍스트 추출
        text = page.get_text("text")

        # 표 추출 시도
        tables = page.find_tables()
        table_md = ""
        if tables and tables.tables:
            for table in tables.tables:
                df = table.to_pandas()
                table_md += "\n" + df.to_markdown(index=False) + "\n"

        page_content = text.strip()
        if table_md:
            page_content += "\n" + table_md.strip()

        if page_content:
            parts.append(f"<!-- 페이지 {i + 1} -->\n{page_content}")

    doc.close()
    return "\n\n---\n\n".join(parts)


def execute(inputs: dict, params: dict, context: dict) -> dict:
    pdf_path = inputs["파일"]
    pages = params.get("pages", "전체")

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF 파일 없음: {pdf_path}")

    context["progress"](0.1)
    context["log"]("PDF 변환 시작")

    # kordoc 시도, 없으면 pymupdf
    result = _convert_with_kordoc(pdf_path, pages)
    if result is None:
        context["log"]("pymupdf로 변환")
        result = _convert_with_pymupdf(pdf_path, pages)

    context["progress"](1.0)
    context["log"](f"변환 완료 ({len(result)} 글자)")

    return {"텍스트": result}
