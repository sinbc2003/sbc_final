"""RAG 검색 + LLM 답변 생성 노드."""

import json


def execute(inputs: dict, params: dict, context: dict) -> dict:
    from engine.vector_store import VectorStore

    query = inputs.get("질문", "")
    if not query.strip():
        return {"답변": "질문이 비어있습니다.", "참조문서": "[]"}

    # 벡터 검색
    context["log"]("관련 문서 검색 중...")
    context["progress"](0.1)

    rag_settings = context.get("config", {}).get("rag", {})
    rag_settings["enabled"] = True

    from pathlib import Path
    data_dir = Path(context.get("temp_dir", ".")).parent.parent / "data"

    vs = VectorStore(data_dir=data_dir, settings=rag_settings)
    search_result = vs.query(
        query_text=query,
        n_results=params.get("n_results", 5),
    )

    references = search_result.get("results", [])
    context["progress"](0.4)

    if not references:
        return {
            "답변": "관련 문서를 찾을 수 없습니다. RAG 임베딩 저장 노드로 먼저 문서를 저장해주세요.",
            "참조문서": "[]",
        }

    # 참조 문서 컨텍스트 구성
    ref_texts = []
    for i, ref in enumerate(references, 1):
        source = ref.get("metadata", {}).get("source_name", "")
        source_label = f" (출처: {source})" if source else ""
        ref_texts.append(f"[참조 {i}]{source_label}\n{ref['text']}")

    context_text = "\n\n---\n\n".join(ref_texts)

    # LLM 프롬프트 구성
    system_prompt = params.get("system_prompt", "주어진 참조 문서를 바탕으로 질문에 정확히 답하라.")
    full_prompt = f"""{system_prompt}

## 참조 문서
{context_text}

## 질문
{query}

## 답변"""

    context["log"](f"LLM 답변 생성 중 (참조 {len(references)}건)...")
    context["progress"](0.6)

    # LLM 호출
    llm = context.get("llm")
    if llm is None:
        return {
            "답변": f"LLM 없음. 참조 문서:\n\n{context_text}",
            "참조문서": json.dumps(references, ensure_ascii=False),
        }

    answer = llm.generate(
        prompt=full_prompt,
        max_tokens=params.get("max_tokens", 2048),
        temperature=0.3,  # RAG는 낮은 temperature
        provider=params.get("provider", "auto"),
    )

    context["progress"](1.0)

    return {
        "답변": answer,
        "참조문서": json.dumps(
            [{"text": r["text"][:200], "source": r.get("metadata", {}).get("source_name", "")}
             for r in references],
            ensure_ascii=False,
        ),
    }
