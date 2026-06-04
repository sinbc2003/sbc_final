"""
URL → 마크다운 변환 노드.

requests + BeautifulSoup으로 웹 페이지 본문을 추출하여
마크다운으로 변환한다.
"""

import re


def _html_to_markdown(soup) -> str:
    """BeautifulSoup 요소를 간이 마크다운으로 변환."""
    from bs4 import NavigableString

    # 스크립트, 스타일, nav, footer, header 제거
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # 본문 영역 우선 탐색
    body = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"(content|article|post|entry)"))
        or soup.find("body")
        or soup
    )

    lines = []

    for element in body.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "table"]
    ):
        tag = element.name
        text = element.get_text(separator=" ", strip=True)

        if not text:
            continue

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        elif tag == "p":
            lines.append(text)
            lines.append("")
        elif tag == "li":
            lines.append(f"- {text}")
        elif tag == "pre":
            lines.append(f"```\n{text}\n```")
            lines.append("")
        elif tag == "blockquote":
            for bq_line in text.split("\n"):
                lines.append(f"> {bq_line}")
            lines.append("")
        elif tag == "table":
            rows = element.find_all("tr")
            if rows:
                for row_idx, row in enumerate(rows):
                    cells = row.find_all(["th", "td"])
                    cell_texts = [c.get_text(strip=True) for c in cells]
                    lines.append("| " + " | ".join(cell_texts) + " |")
                    if row_idx == 0:
                        lines.append(
                            "| " + " | ".join(["---"] * len(cell_texts)) + " |"
                        )
                lines.append("")

    return "\n".join(lines).strip()


def execute(inputs: dict, params: dict, context: dict) -> dict:
    url = inputs["URL"].strip()

    if not url:
        raise ValueError("URL이 비어있습니다")

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    context["progress"](0.1)
    context["log"](f"웹 페이지 요청: {url}")

    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    context["progress"](0.5)
    context["log"](f"응답 수신 ({len(response.content)} bytes)")

    # 인코딩 처리
    response.encoding = response.apparent_encoding or "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")

    # 제목 추출
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""

    result = _html_to_markdown(soup)

    if title_text and not result.startswith("# "):
        result = f"# {title_text}\n\n{result}"

    context["progress"](1.0)
    context["log"](f"변환 완료 ({len(result)} 글자)")

    return {"텍스트": result}
