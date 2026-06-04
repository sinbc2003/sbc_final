"""
이미지 → 텍스트 (OCR) 변환 노드.

pytesseract로 이미지에서 텍스트를 추출한다.
Tesseract가 설치되어 있어야 동작한다.
"""

from pathlib import Path


def execute(inputs: dict, params: dict, context: dict) -> dict:
    image_path = inputs["파일"]
    lang = params.get("lang", "kor+eng")

    if not Path(image_path).exists():
        raise FileNotFoundError(f"이미지 파일 없음: {image_path}")

    context["progress"](0.1)
    context["log"](f"OCR 시작 (언어: {lang})")

    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        context["progress"](0.3)

        result = pytesseract.image_to_string(img, lang=lang)
        result = result.strip()

    except ImportError:
        raise RuntimeError(
            "pytesseract 또는 Pillow가 설치되지 않았습니다. "
            "pip install pytesseract Pillow 을 실행하세요."
        )
    except Exception as e:
        error_msg = str(e)
        if "tesseract" in error_msg.lower():
            raise RuntimeError(
                "Tesseract OCR이 설치되지 않았습니다. "
                "https://github.com/tesseract-ocr/tesseract 에서 설치하세요."
            )
        raise

    context["progress"](1.0)
    context["log"](f"OCR 완료 ({len(result)} 글자)")

    return {"텍스트": result}
