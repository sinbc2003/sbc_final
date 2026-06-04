"""
파일 입력 노드.

파일 경로를 받아 원본 파일 + (선택) 자동 변환 텍스트를 출력한다.
자동 변환: PDF/HWPX/DOCX/XLSX/PPTX → 마크다운 텍스트.
"""

from pathlib import Path


# 확장자 → 변환 노드 매핑
_CONVERTERS = {
    ".pdf": "pdf_to_md",
    ".hwpx": "hwpx_to_md",
    ".hwp": "hwp_to_md",
    ".docx": "docx_to_md",
    ".doc": "docx_to_md",
    ".xlsx": "xlsx_to_md",
    ".xls": "xlsx_to_md",
    ".csv": "xlsx_to_md",
    ".pptx": "pptx_to_md",
    ".ppt": "pptx_to_md",
    ".txt": "_raw_text",
    ".md": "_raw_text",
}


def _auto_convert(file_path: str, context: dict) -> str:
    """파일을 마크다운 텍스트로 자동 변환."""
    ext = Path(file_path).suffix.lower()
    converter = _CONVERTERS.get(ext)

    if not converter:
        context["log"](f"자동 변환 미지원 확장자: {ext}")
        return ""

    if converter == "_raw_text":
        # 텍스트 파일은 그대로 읽기
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Path(file_path).read_text(encoding="cp949", errors="replace")

    # 해당 변환 노드의 execute 함수를 직접 호출
    try:
        import importlib
        mod = importlib.import_module(f"nodes.{converter}.main")
        # 입력 포트명 찾기
        input_name = "파일"
        if converter == "xlsx_to_md":
            input_name = "파일"

        result = mod.execute(
            {input_name: file_path},
            {"pages": "전체"},
            context,
        )
        # 텍스트 출력 포트 찾기
        return result.get("텍스트", "") or ""
    except Exception as e:
        context["log"](f"자동 변환 실패: {e}")
        return ""


def execute(inputs: dict, params: dict, context: dict) -> dict:
    file_path = params.get("path", "").strip()

    if not file_path:
        raise ValueError("파일 경로가 비어있습니다")

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"파일 없음: {file_path}")

    if not path.is_file():
        raise ValueError(f"파일이 아닙니다 (디렉토리?): {file_path}")

    context["progress"](0.3)
    context["log"](f"파일 확인: {path.name} ({path.stat().st_size:,} bytes)")

    result = {"파일": str(path.resolve())}

    # 자동 변환
    auto_convert = params.get("auto_convert", True)
    if auto_convert:
        context["log"](f"텍스트 자동 변환 중 ({path.suffix})...")
        text = _auto_convert(str(path.resolve()), context)
        if text:
            result["텍스트"] = text
            context["log"](f"변환 완료 ({len(text):,}자)")
        else:
            result["텍스트"] = ""
    else:
        result["텍스트"] = ""

    context["progress"](1.0)
    return result
