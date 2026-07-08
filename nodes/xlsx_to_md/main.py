"""
Excel/CSV → 마크다운 변환 노드.

구현 우선순위:
1. kordoc CLI (설치되어 있으면)
2. pandas (fallback)
"""

import shutil
import subprocess
from pathlib import Path


def _convert_with_kordoc(file_path: str) -> str | None:
    """kordoc CLI로 변환 시도."""
    # Windows에서 CreateProcess가 npx.cmd를 실행하려면 확장자 포함 전체 경로 필요
    npx = shutil.which("npx")
    if not npx:
        return None

    try:
        cmd = [npx, "kordoc", file_path, "--format", "json"]
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


def _convert_with_fallback(file_path: str, sheet: str) -> tuple[str, list]:
    """pandas로 Excel/CSV 읽어서 마크다운 변환."""
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError(
            "pandas 미설치. pip install pandas openpyxl tabulate 후 다시 시도하세요."
        )

    suffix = Path(file_path).suffix.lower()
    parts = []
    table_data = []

    if suffix == ".csv":
        # CSV 파일
        df = pd.read_csv(file_path)
        md = df.to_markdown(index=False)
        parts.append(md)
        table_data.append({
            "sheet": "CSV",
            "rows": len(df),
            "columns": list(df.columns),
            "data": df.to_dict(orient="records"),
        })
    else:
        # Excel 파일 (.xlsx, .xls)
        try:
            xl = pd.ExcelFile(file_path)
        except Exception as e:
            raise RuntimeError(f"Excel 파일 열기 실패: {e}")

        sheet_names = xl.sheet_names

        if sheet and sheet in sheet_names:
            target_sheets = [sheet]
        elif sheet:
            raise ValueError(
                f"시트 '{sheet}'를 찾을 수 없음. 존재하는 시트: {sheet_names}"
            )
        else:
            target_sheets = sheet_names

        for sname in target_sheets:
            df = pd.read_excel(xl, sheet_name=sname)
            if df.empty:
                continue

            md = df.to_markdown(index=False)
            parts.append(f"## {sname}\n\n{md}")
            table_data.append({
                "sheet": sname,
                "rows": len(df),
                "columns": list(df.columns),
                "data": df.to_dict(orient="records"),
            })

    if not parts:
        raise RuntimeError("파일에서 데이터를 추출할 수 없음")

    return "\n\n---\n\n".join(parts), table_data


def execute(inputs: dict, params: dict, context: dict) -> dict:
    file_path = inputs["파일"]
    sheet = params.get("sheet", "").strip()

    if not Path(file_path).exists():
        raise FileNotFoundError(f"파일 없음: {file_path}")

    context["progress"](0.1)
    context["log"]("Excel/CSV 변환 시작")

    # kordoc 먼저 시도
    kordoc_result = _convert_with_kordoc(file_path)
    if kordoc_result is not None:
        context["progress"](1.0)
        context["log"](f"변환 완료 ({len(kordoc_result)} 글자)")
        return {"텍스트": kordoc_result, "표데이터": []}

    # fallback: pandas
    context["log"]("kordoc 미설치, pandas로 변환")
    text_result, table_data = _convert_with_fallback(file_path, sheet)

    context["progress"](1.0)
    context["log"](f"변환 완료 ({len(text_result)} 글자)")

    return {"텍스트": text_result, "표데이터": table_data}
