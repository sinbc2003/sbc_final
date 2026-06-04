"""RAG 임베딩 저장 노드."""

import json


def execute(inputs: dict, params: dict, context: dict) -> dict:
    from engine.vector_store import VectorStore

    text = inputs.get("텍스트", "")
    if not text.strip():
        return {"결과": json.dumps({"error": "입력 텍스트 없음"}, ensure_ascii=False)}

    context["log"]("벡터 스토어 초기화...")
    context["progress"](0.1)

    # 설정에서 RAG config 가져오기
    rag_settings = context.get("config", {}).get("rag", {})
    rag_settings["enabled"] = True
    if params.get("collection"):
        rag_settings["collection_name"] = params["collection"]

    from pathlib import Path
    data_dir = Path(context.get("temp_dir", ".")).parent.parent / "data"

    vs = VectorStore(data_dir=data_dir, settings=rag_settings)

    context["log"](f"텍스트 임베딩 중 ({len(text)}자)...")
    context["progress"](0.3)

    result = vs.ingest(
        text=text,
        source=params.get("source_name", ""),
        metadata={"source_name": params.get("source_name", "")},
    )

    context["progress"](1.0)

    return {"결과": json.dumps(result, ensure_ascii=False)}
