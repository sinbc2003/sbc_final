"""
이미지 추출 노드.

PDF: pymupdf로 이미지 추출
HWPX/DOCX: ZIP으로 열어 media/ 폴더에서 이미지 추출
"""

import os
import zipfile
from pathlib import Path


def _extract_from_pdf(pdf_path: str, output_dir: str, fmt: str) -> list[str]:
    """PDF에서 이미지 추출."""
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    image_paths = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        image_list = page.get_images(full=True)

        for img_idx, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            # 지정 형식으로 변환 필요 시
            filename = f"page{page_idx + 1}_img{img_idx + 1}.{fmt}"
            output_path = os.path.join(output_dir, filename)

            if image_ext == fmt:
                with open(output_path, "wb") as f:
                    f.write(image_bytes)
            else:
                from PIL import Image
                import io

                img_obj = Image.open(io.BytesIO(image_bytes))
                if fmt == "jpg":
                    img_obj = img_obj.convert("RGB")
                img_obj.save(output_path)

            image_paths.append(output_path)

    doc.close()
    return image_paths


def _extract_from_zip(file_path: str, output_dir: str, fmt: str) -> list[str]:
    """HWPX/DOCX(ZIP 기반)에서 이미지 추출."""
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".emf", ".wmf"}
    image_paths = []

    with zipfile.ZipFile(file_path, "r") as zf:
        for name in zf.namelist():
            ext = Path(name).suffix.lower()
            if ext in image_extensions:
                # 추출
                data = zf.read(name)
                safe_name = Path(name).name
                base = Path(safe_name).stem
                output_path = os.path.join(output_dir, f"{base}.{fmt}")

                # 중복 방지
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(
                        output_dir, f"{base}_{counter}.{fmt}"
                    )
                    counter += 1

                if ext.lstrip(".") == fmt or (fmt == "jpg" and ext in (".jpg", ".jpeg")):
                    with open(output_path, "wb") as f:
                        f.write(data)
                else:
                    from PIL import Image
                    import io

                    try:
                        img = Image.open(io.BytesIO(data))
                        if fmt == "jpg":
                            img = img.convert("RGB")
                        img.save(output_path)
                    except Exception:
                        # 변환 불가한 이미지는 원본으로 저장
                        raw_path = os.path.join(output_dir, safe_name)
                        with open(raw_path, "wb") as f:
                            f.write(data)
                        output_path = raw_path

                image_paths.append(output_path)

    return image_paths


def execute(inputs: dict, params: dict, context: dict) -> dict:
    file_path = inputs["파일"]
    fmt = params.get("format", "png")

    if not Path(file_path).exists():
        raise FileNotFoundError(f"파일 없음: {file_path}")

    context["progress"](0.1)
    context["log"]("이미지 추출 시작")

    output_dir = os.path.join(context["temp_dir"], "images")
    os.makedirs(output_dir, exist_ok=True)

    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        context["log"]("PDF에서 이미지 추출")
        image_paths = _extract_from_pdf(file_path, output_dir, fmt)
    elif ext in (".hwpx", ".docx"):
        context["log"](f"{ext.upper()}에서 이미지 추출")
        image_paths = _extract_from_zip(file_path, output_dir, fmt)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {ext}")

    context["progress"](1.0)
    context["log"](f"추출 완료 ({len(image_paths)}개 이미지)")

    return {"이미지목록": image_paths}
