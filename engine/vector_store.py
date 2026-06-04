"""
ChromaDB 벡터 스토어 — 문서 임베딩/검색/공유.

기능:
  - 문서 청킹 → 임베딩 → ChromaDB 저장
  - 쿼리 → 유사 청크 검색 → LLM 컨텍스트 제공
  - 컬렉션 내보내기/가져오기 (공유용)
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any


class VectorStore:
    """ChromaDB 래퍼. RAG 파이프라인 전체를 관리."""

    def __init__(self, data_dir: Path, settings: dict[str, Any] | None = None):
        self._data_dir = data_dir / "chroma"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._settings = settings or {}
        self._client = None
        self._collection = None
        self._embedder = None

    @property
    def enabled(self) -> bool:
        return self._settings.get("enabled", False)

    def _ensure_client(self):
        """ChromaDB 클라이언트 초기화 (lazy)."""
        if self._client is not None:
            return
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._data_dir))
            col_name = self._settings.get("collection_name", "teacherflow")
            self._collection = self._client.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            raise RuntimeError(
                "chromadb가 설치되지 않았습니다. pip install chromadb"
            )

    def _ensure_embedder(self):
        """임베딩 모델 로드 (lazy)."""
        if self._embedder is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            model_name = self._settings.get(
                "embedding_model",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
            self._embedder = SentenceTransformer(model_name)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers가 설치되지 않았습니다. "
                "pip install sentence-transformers"
            )

    # ── 문서 인제스트 ────────────────────────────────

    def ingest(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        source: str = "",
    ) -> dict[str, Any]:
        """텍스트를 청킹 → 임베딩 → 저장."""
        if not self.enabled:
            return {"success": False, "error": "RAG 비활성화"}

        self._ensure_client()
        self._ensure_embedder()

        chunk_size = self._settings.get("chunk_size", 500)
        chunk_overlap = self._settings.get("chunk_overlap", 50)
        chunks = self._chunk_text(text, chunk_size, chunk_overlap)

        if not chunks:
            return {"success": False, "error": "청킹 결과 없음"}

        # 임베딩
        embeddings = self._embedder.encode(chunks).tolist()

        # 메타데이터
        base_meta = metadata or {}
        base_meta["source"] = source
        doc_id = hashlib.sha256(text[:500].encode()).hexdigest()[:12]

        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        metas = [{**base_meta, "chunk_index": i, "doc_id": doc_id} for i in range(len(chunks))]

        # 기존 동일 doc_id 청크 삭제 (업데이트)
        try:
            existing = self._collection.get(where={"doc_id": doc_id})
            if existing["ids"]:
                self._collection.delete(ids=existing["ids"])
        except Exception:
            pass

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metas,
        )

        return {
            "success": True,
            "chunks": len(chunks),
            "doc_id": doc_id,
            "total_documents": self._collection.count(),
        }

    # ── 검색 ─────────────────────────────────────────

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """유사 청크 검색."""
        if not self.enabled:
            return {"results": [], "error": "RAG 비활성화"}

        self._ensure_client()
        self._ensure_embedder()

        query_embedding = self._embedder.encode([query_text]).tolist()

        kwargs: dict[str, Any] = {
            "query_embeddings": query_embedding,
            "n_results": min(n_results, self._collection.count() or 1),
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        items = []
        for i in range(len(results["ids"][0])):
            items.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
            })

        return {"results": items, "total": self._collection.count()}

    # ── 컬렉션 관리 ──────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """컬렉션 통계."""
        if not self.enabled:
            return {"enabled": False, "count": 0}
        try:
            self._ensure_client()
            return {
                "enabled": True,
                "count": self._collection.count(),
                "collection": self._settings.get("collection_name", "teacherflow"),
            }
        except Exception as e:
            return {"enabled": True, "count": 0, "error": str(e)}

    def delete_collection(self) -> dict[str, Any]:
        """컬렉션 전체 삭제."""
        try:
            self._ensure_client()
            col_name = self._settings.get("collection_name", "teacherflow")
            self._client.delete_collection(col_name)
            self._collection = self._client.get_or_create_collection(
                name=col_name, metadata={"hnsw:space": "cosine"}
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 공유 (내보내기/가져오기) ──────────────────────

    def export_collection(self) -> dict[str, Any]:
        """컬렉션을 JSON으로 내보내기 (공유용)."""
        try:
            self._ensure_client()
            data = self._collection.get(include=["documents", "metadatas", "embeddings"])
            return {
                "success": True,
                "data": {
                    "ids": data["ids"],
                    "documents": data["documents"],
                    "metadatas": data["metadatas"],
                    "embeddings": data["embeddings"],
                    "count": len(data["ids"]),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def import_collection(self, export_data: dict[str, Any], merge: bool = True) -> dict[str, Any]:
        """내보낸 데이터 가져오기."""
        try:
            self._ensure_client()
            if not merge:
                self.delete_collection()

            ids = export_data["ids"]
            docs = export_data["documents"]
            metas = export_data["metadatas"]
            embeddings = export_data.get("embeddings")

            # 중복 ID 필터링
            existing = set()
            try:
                existing_data = self._collection.get()
                existing = set(existing_data["ids"])
            except Exception:
                pass

            new_ids, new_docs, new_metas, new_embeds = [], [], [], []
            for i, doc_id in enumerate(ids):
                if doc_id not in existing:
                    new_ids.append(doc_id)
                    new_docs.append(docs[i])
                    new_metas.append(metas[i])
                    if embeddings:
                        new_embeds.append(embeddings[i])

            if new_ids:
                kwargs = {
                    "ids": new_ids,
                    "documents": new_docs,
                    "metadatas": new_metas,
                }
                if new_embeds:
                    kwargs["embeddings"] = new_embeds
                self._collection.add(**kwargs)

            return {
                "success": True,
                "imported": len(new_ids),
                "skipped": len(ids) - len(new_ids),
                "total": self._collection.count(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 내부 유틸 ────────────────────────────────────

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        """텍스트를 문장 경계 기반으로 청킹."""
        if not text.strip():
            return []

        # 문장 분리 (한국어/영어 모두 대응)
        sentences = re.split(r'(?<=[.!?。])\s+|\n{2,}', text)
        chunks: list[str] = []
        current = ""

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > chunk_size and current:
                chunks.append(current.strip())
                # 겹침: 마지막 overlap 글자 유지
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:] + " " + sent
                else:
                    current = sent
            else:
                current = (current + " " + sent).strip() if current else sent

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def cleanup(self):
        """리소스 정리."""
        self._client = None
        self._collection = None
        self._embedder = None
