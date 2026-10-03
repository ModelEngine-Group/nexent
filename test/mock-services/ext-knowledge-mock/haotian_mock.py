"""Haotian (昊天) route set (mounted at /haotian).

Contract mirrored from:
  - backend/services/haotian_service.py — GET list_url with the raw
    Authorization header forwarded verbatim (follow_redirects=True);
    response ``{"knowledge_sets": [{"name": ..., "knowledge_bases":
    [{"dify_dataset_id": ..., "name": ...}]}]}``. A ``dify_dataset_id`` of
    the literal string "null" is replaced with a default UUID by the product.
  - sdk/nexent/core/tools/haotian_search_tool.py — POST retrieve_url with a
    Dify-style payload plus ``dataset_ids``; the tool accepts several
    response shapes and reads ``records[].{segment.content,
    segment.document.name, metadata.*}``.

Seeds deliberately include one knowledge base whose ``dify_dataset_id`` is
"null" so the product's default-UUID replacement path stays covered.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header

from mock_common import StateStore, require_authorization, term_boost

# Matches haotian_service._DEFAULT_KNOWLEDGE_BASE_ID: chunks stored under
# this id are reachable after the product replaces the "null" dataset id.
DEFAULT_DATASET_ID = "a8d68fbf-bd6e-5461-a9d1-cf1bb3522e38"


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/haotian")

    @router.get("/api/knowledge-sets")
    def list_knowledge_sets(
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_authorization(authorization)
        return {"knowledge_sets": state.data.get("knowledge_sets", [])}

    @router.post("/api/retrieve")
    def retrieve(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_authorization(authorization)
        query = str(body.get("query") or "")
        retrieval_model = body.get("retrieval_model") or {}
        top_k = int(retrieval_model.get("top_k") or 5)
        dataset_ids = [str(d) for d in body.get("dataset_ids") or []]
        chunks_by_dataset: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_dataset", {})

        records: List[Dict[str, Any]] = []
        for dataset_id in dataset_ids:
            for chunk in chunks_by_dataset.get(dataset_id, []):
                haystack = f"{chunk.get('document_name', '')} {chunk.get('content', '')}"
                score = round(float(chunk.get("score", 0.5)) + term_boost(query, haystack), 4)
                records.append({
                    "segment": {
                        "content": chunk.get("content", ""),
                        "document": {
                            "id": chunk.get("document_id", ""),
                            "name": chunk.get("document_name", ""),
                        },
                    },
                    "score": score,
                    "metadata": {
                        "dataset_id": dataset_id,
                        "document_id": chunk.get("document_id", ""),
                        "document_name": chunk.get("document_name", ""),
                        "score": score,
                    },
                })
        records.sort(key=lambda r: r.get("score", 0), reverse=True)
        return {"records": records[:top_k]}

    return router
