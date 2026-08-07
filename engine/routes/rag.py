"""RAG 벡터 스토어 엔드포인트."""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from engine import deps

router = APIRouter()


class IngestRequest(BaseModel):
    text: str
    source: str = ""
    metadata: dict[str, Any] = {}

class QueryRequest(BaseModel):
    query: str
    n_results: int = 5

class ImportRequest(BaseModel):
    data: dict[str, Any]
    merge: bool = True


@router.get("/api/rag/stats")
async def rag_stats():
    if not deps.vector_store:
        return {"enabled": False, "count": 0}
    return deps.vector_store.get_stats()

@router.post("/api/rag/ingest")
async def rag_ingest(req: IngestRequest):
    if not deps.vector_store:
        raise HTTPException(503, "RAG 비활성")
    return deps.vector_store.ingest(req.text, metadata=req.metadata, source=req.source)

@router.post("/api/rag/query")
async def rag_query(req: QueryRequest):
    if not deps.vector_store:
        raise HTTPException(503, "RAG 비활성")
    return deps.vector_store.query(req.query, req.n_results)

@router.get("/api/rag/export")
async def rag_export():
    if not deps.vector_store:
        raise HTTPException(503, "RAG 비활성")
    return deps.vector_store.export_collection()

@router.post("/api/rag/import")
async def rag_import(req: ImportRequest):
    if not deps.vector_store:
        raise HTTPException(503, "RAG 비활성")
    return deps.vector_store.import_collection(req.data, req.merge)
