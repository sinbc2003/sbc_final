"""
마크다운 → PDF 변환 노드.

변환 우선순위:
1. pypandoc (Pandoc 기반, 가장 안정적)
2. reportlab 기반 직접 생성 (fallback)
"""

import os
import subprocess
from pathlib import Path


def _convert_with_pandoc(md_text: str, output_path: str) -> str | None:
    """Pandoc으로 MD → PDF."""
    try:
        import pypandoc
        # 임시 MD 파일
        md_tmp = output_path + ".tmp.md"
        with open(md_tmp, "w", encoding="utf-8") as f:
            f.write(md_text)

        pypandoc.convert_file(
            md_tmp, "pdf",
            outputfile=output_path,
            extra_args=[
                "--pdf-engine=xelatex",
                "-V", "mainfont=Malgun Gothic",
                "-V", "geometry:margin=2.5cm",
            ],
        )
        os.unlink(md_tmp)

        if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
            return output_path
    except Exception:
        pass

    # xelatex 없으면 pdflatex 시도
    try:
        md_tmp = output_path + ".tmp.md"
        with open(md_tmp, "w", encoding="utf-8") as f:
            f.write(md_text)
        pypandoc.convert_file(
            md_tmp, "pdf",
            outputfile=output_path,
        )
        os.unlink(md_tmp)
        if Path(output_path).exists():
            return output_path
    except Exception:
        if Path(md_tmp).exists():
            os.unlink(md_tmp)
    return None


def _convert_with_reportlab(md_text: str, output_path: str) -> str:
    """reportlab으로 간단 PDF 생성 (fallback)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 한글 폰트 등록
    font_registered = False
    for font_path in [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]:
        if Path(font_path).exists():
            try:
                pdfmetrics.registerFont(TTFont("Korean", font_path))
                font_registered = True
                break
            except Exception:
                pass

    font_name = "Korean" if font_registered else "Helvetica"

    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("Korean", parent=styles["Normal"],
                            fontName=font_name, fontSize=10, leading=16)
    heading = ParagraphStyle("KoreanH", parent=styles["Heading1"],
                             fontName=font_name, fontSize=16, leading=22)

    story = []
    for line in md_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 8))
            continue
        if line.startswith("# "):
            story.append(Paragraph(line[2:], heading))
        elif line.startswith("## "):
            h2 = ParagraphStyle("H2", parent=heading, fontSize=14, leading=20)
            story.append(Paragraph(line[3:], h2))
        elif line.startswith("### "):
            h3 = ParagraphStyle("H3", parent=heading, fontSize=12, leading=18)
            story.append(Paragraph(line[4:], h3))
        else:
            # HTML 태그 이스케이프
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, normal))

    doc.build(story)
    return output_path


def execute(inputs: dict, params: dict, context: dict) -> dict:
    md_text = inputs["텍스트"]
    output_name = params.get("output_name", "output")
    output_path = os.path.join(context["temp_dir"], f"{output_name}.pdf")

    context["progress"](0.1)
    context["log"]("PDF 변환 시작")

    # reportlab (한글 지원, 빠름)
    result = _convert_with_reportlab(md_text, output_path)

    context["progress"](1.0)
    context["log"](f"PDF 생성 완료: {Path(result).name}")

    return {"파일": result}
