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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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

    # 텍스트는 kordoc(한글 문서 재현이 더 좋음) 우선. 단 시트를 지정했으면
    # kordoc이 그 지시를 모르므로 pandas 결과를 쓴다.
    kordoc_result = None if sheet else _convert_with_kordoc(file_path)

    # 표데이터는 **항상 pandas로** 만든다. 예전엔 kordoc 성공 시 빈 리스트를
    # 내보내, 표데이터를 쓰는 하류(column_mapping·save_xlsx)가 아무 오류 없이
    # 빈 엑셀을 만들었다(무음 실패).
    try:
        text_result, table_data = _convert_with_fallback(file_path, sheet)
    except Exception as e:
        if kordoc_result is None:
            raise
        context["log"](f"[WARN] 표 데이터 추출 실패({e}) — 텍스트만 제공합니다")
        text_result, table_data = kordoc_result, []
    else:
        if kordoc_result:
            text_result = kordoc_result

    context["progress"](1.0)
    rows = sum(t.get("rows", 0) for t in table_data)
    context["log"](f"변환 완료 ({len(text_result)} 글자, 표 {len(table_data)}개 / {rows}행)")

    return {"텍스트": text_result, "표데이터": table_data}
