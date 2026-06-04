"""
HWPX 양식 채우기 노드.

HWPX(ZIP) 내부 XML에서 {{빈칸}} 패턴을 찾아
데이터로 치환한 뒤 저장한다.

데이터가 여러 행이면 행별로 파일을 생성하고 ZIP으로 묶는다.
"""

import os
import re
import shutil
import zipfile
from pathlib import Path


def _fill_hwpx(template_path: str, data: dict, output_path: str) -> str:
    """HWPX 양식 하나를 데이터로 채워서 저장."""
    with zipfile.ZipFile(template_path, "r") as zf_in:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                content = zf_in.read(item.filename)

                # XML 파일만 치환 대상
                if item.filename.endswith(".xml"):
                    try:
                        text = content.decode("utf-8")

                        # {{변수명}} 패턴 치환
                        def replacer(match):
                            key = match.group(1).strip()
                            return str(data.get(key, match.group(0)))

                        text = re.sub(r"\{\{(.+?)\}\}", replacer, text)
                        content = text.encode("utf-8")
                    except UnicodeDecodeError:
                        pass  # 바이너리 파일은 건너뜀

                zf_out.writestr(item, content)

    return output_path


def execute(inputs: dict, params: dict, context: dict) -> dict:
    template_path = inputs["양식파일"]
    table_data = inputs["데이터"]

    if not Path(template_path).exists():
        raise FileNotFoundError(f"양식 파일 없음: {template_path}")

    context["progress"](0.1)
    context["log"]("HWPX 양식 채우기 시작")

    # JSON 문자열이면 파싱
    if isinstance(table_data, str):
        import json
        try:
            table_data = json.loads(table_data)
        except (ValueError, json.JSONDecodeError):
            raise TypeError(f"데이터를 파싱할 수 없습니다: {table_data[:100]}")

    # 데이터 정규화
    if isinstance(table_data, dict):
        table_data = [table_data]
    elif not isinstance(table_data, list):
        raise TypeError(f"지원하지 않는 데이터 타입: {type(table_data)}")

    if not table_data:
        raise ValueError("데이터가 비어있습니다")

    output_dir = os.path.join(context["temp_dir"], "hwpx_filled")
    os.makedirs(output_dir, exist_ok=True)

    if len(table_data) == 1:
        # 단일 행: HWPX 하나 생성
        output_path = os.path.join(context["temp_dir"], "filled.hwpx")
        _fill_hwpx(template_path, table_data[0], output_path)

        context["progress"](1.0)
        context["log"]("양식 채우기 완료 (1개 파일)")

        return {"파일": output_path}

    # 여러 행: 각각 생성 후 ZIP으로 묶기
    generated = []
    total = len(table_data)

    for idx, row in enumerate(table_data):
        row_name = row.get("이름", row.get("name", f"row_{idx + 1}"))
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", str(row_name))
        out_path = os.path.join(output_dir, f"{safe_name}.hwpx")
        _fill_hwpx(template_path, row, out_path)
        generated.append(out_path)

        context["progress"](0.1 + 0.8 * ((idx + 1) / total))

    # ZIP으로 묶기
    zip_path = os.path.join(context["temp_dir"], "filled_all.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in generated:
            zf.write(file_path, Path(file_path).name)

    context["progress"](1.0)
    context["log"](f"양식 채우기 완료 ({len(generated)}개 파일 → ZIP)")

    return {"파일": zip_path}
