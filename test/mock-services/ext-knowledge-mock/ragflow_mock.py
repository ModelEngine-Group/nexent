"""RAGFlow route set (mounted at /ragflow).

Contract mirrored from:
  - backend/services/ragflow_service.py — GET {base}/api/v1/datasets with
    Bearer; response ``{"code": 0, "data": [...]}``; a non-zero code is an
    error. Items are read as ``{id, name, description, doc_num, chunk_num,
    create_time, update_time}``.
  - sdk/nexent/core/tools/ragflow_search_tool.py — POST {base}/api/v1/datasets/search
    with ``{question, top_k, similarity_threshold, ..., dataset_ids, doc_ids}``;
    response ``{"code": 0, "data": {"total": N, "chunks": [...]}}`` where
    chunks carry ``{content_with_weight, content_ltks, docnm_kwd,
    important_kwd, doc_id, similarity, term_similarity, vector_similarity}``
    and the tool re-sorts them by ``similarity``.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header

from mock_common import StateStore, require_bearer, term_boost


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/ragflow")

    @router.get("/api/v1/datasets")
    def list_datasets(
        page: int = 1,
        page_size: int = 30,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        datasets: List[Dict[str, Any]] = state.data.get("datasets", [])
        start = (page - 1) * page_size
        return {
            "code": 0,
            "data": datasets[start : start + page_size],
            "message": "success",
        }

    @router.post("/api/v1/datasets/search")
    def search(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        question = str(body.get("question") or "")
        top_k = int(body.get("top_k") or 5)
        threshold = float(body.get("similarity_threshold") or 0.0)
        dataset_ids = body.get("dataset_ids") or []
        doc_ids = body.get("doc_ids") or []
        chunks_by_dataset: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_dataset", {})

        chunks: List[Dict[str, Any]] = []
        for dataset_id in dataset_ids:
            for chunk in chunks_by_dataset.get(dataset_id, []):
                if doc_ids and chunk.get("doc_id") not in doc_ids:
                    continue
                haystack = f"{chunk.get('docnm_kwd', '')} {chunk.get('content_with_weight', '')}"
                similarity = round(
                    float(chunk.get("similarity", 0.5)) + term_boost(question, haystack), 4
                )
                if similarity < threshold:
                    continue
                chunks.append({**chunk, "similarity": similarity})
        chunks.sort(key=lambda c: c.get("similarity", 0), reverse=True)
        return {"code": 0, "data": {"total": len(chunks), "chunks": chunks[:top_k]}}

    return router
