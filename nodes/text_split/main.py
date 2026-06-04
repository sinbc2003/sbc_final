"""
텍스트 분할 노드.

슬라이딩 윈도우 방식으로 텍스트를 청크로 분할한다.
"""


def execute(inputs: dict, params: dict, context: dict) -> dict:
    text = inputs["텍스트"]
    chunk_size = int(params.get("chunk_size", 2000))
    overlap = int(params.get("overlap", 200))

    if chunk_size <= 0:
        raise ValueError(f"청크 크기는 양수여야 합니다: {chunk_size}")
    if overlap < 0:
        raise ValueError(f"겹침 크기는 0 이상이어야 합니다: {overlap}")
    if overlap >= chunk_size:
        raise ValueError(
            f"겹침 크기({overlap})가 청크 크기({chunk_size})보다 작아야 합니다"
        )

    context["progress"](0.1)
    context["log"](
        f"텍스트 분할 시작 (총 {len(text)}자, "
        f"청크={chunk_size}, 겹침={overlap})"
    )

    if not text or not text.strip():
        context["progress"](1.0)
        return {"청크목록": []}

    chunks = []
    step = chunk_size - overlap
    pos = 0

    while pos < len(text):
        end = pos + chunk_size
        chunk = text[pos:end]
        chunks.append(chunk)
        pos += step

    context["progress"](1.0)
    context["log"](f"분할 완료 ({len(chunks)}개 청크)")

    return {"청크목록": chunks}
