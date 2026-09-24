"""Dify route set (mounted at /dify).

Contract mirrored from:
  - backend/services/dify_service.py — datasets listing. The service strips a
    trailing ``/v1`` from the user-supplied base and calls ``{base}/v1/datasets``.
  - sdk/nexent/core/tools/dify_search_tool.py — retrieve and upload-file. The
    tool's ``server_url`` conventionally INCLUDES ``/v1``
    (e.g. ``https://api.dify.ai/v1``) and appends ``/datasets/...`` directly.

Because the two call sites disagree on whether the base carries ``/v1``, the
retrieve/upload-file endpoints are registered under BOTH ``/dify/datasets/...``
and ``/dify/v1/datasets/...``. This is intentional — do not "clean it up".

The ``download_url`` returned by upload-file is self-referential and derived
from the request Host header, so it is always reachable through whatever
address the caller used to reach this mock.
"""
import mimetypes
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import Response

from mock_common import StateStore, content_disposition, require_bearer, term_boost

# Fixed seed timestamps (seconds since epoch) — dify_service multiplies by 1000.
_SEED_CREATED_AT = 1718000000


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/dify")

    @router.get("/v1/datasets")
    def list_datasets(
        page: int = 1,
        limit: int = 20,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Dataset listing in Dify envelope shape.

        dify_service only reads ``data[].{id, name, document_count,
        created_at, updated_at, embedding_available, embedding_model}``;
        the pagination fields are kept for realism.
        """
        require_bearer(authorization)
        datasets: List[Dict[str, Any]] = state.data.get("datasets", [])
        start = (page - 1) * limit
        items = datasets[start : start + limit]
        return {
            "data": items,
            "has_more": start + limit < len(datasets),
            "limit": limit,
            "page": page,
            "total": len(datasets),
        }

    def _retrieve(dataset_id: str, body: Dict[str, Any], authorization: Optional[str]) -> Dict[str, Any]:
        require_bearer(authorization)
        chunks: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_dataset", {})
        if dataset_id not in chunks and dataset_id not in {
            d.get("id") for d in state.data.get("datasets", [])
        }:
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

        query = str(body.get("query") or "")
        retrieval_model = body.get("retrieval_model") or {}
        top_k = int(retrieval_model.get("top_k") or 5)

        records = []
        for chunk in chunks.get(dataset_id, []):
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
            })
        records.sort(key=lambda r: r["score"], reverse=True)
        return {"records": records[:top_k]}

    def _upload_file(
        dataset_id: str,
        document_id: str,
        request: Request,
        authorization: Optional[str],
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        documents: Dict[str, List[Dict[str, Any]]] = state.data.get("documents_by_dataset", {})
        known_ids = {
            doc.get("id") for docs in documents.values() for doc in docs
        }
        if document_id not in known_ids:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        # Self-referential URL from the request's own scheme://host, so the
        # address works no matter whether the caller reached this mock from
        # the host, from a container network, or from a test process.
        base = str(request.base_url).rstrip("/")
        return {"download_url": f"{base}/dify/files/{document_id}"}

    # Both base conventions (with and without /v1) are served — see the
    # module docstring before removing either registration.
    for path_prefix in ("", "/v1"):
        def _retrieve_route(
            dataset_id: str,
            body: Dict[str, Any] = Body(...),
            authorization: Optional[str] = Header(default=None),
        ) -> Dict[str, Any]:
            return _retrieve(dataset_id, body, authorization)

        def _upload_file_route(
            dataset_id: str,
            document_id: str,
            request: Request,
            authorization: Optional[str] = Header(default=None),
        ) -> Dict[str, Any]:
            return _upload_file(dataset_id, document_id, request, authorization)

        router.add_api_route(
            f"{path_prefix}/datasets/{{dataset_id}}/retrieve",
            _retrieve_route,
            methods=["POST"],
        )
        router.add_api_route(
            f"{path_prefix}/datasets/{{dataset_id}}/documents/{{document_id}}/upload-file",
            _upload_file_route,
            methods=["GET"],
        )

    @router.get("/files/{document_id}")
    def download_file(
        document_id: str,
        authorization: Optional[str] = Header(default=None),
    ) -> Response:
        """Backs the download_url handed out by upload-file."""
        require_bearer(authorization)
        documents: Dict[str, List[Dict[str, Any]]] = state.data.get("documents_by_dataset", {})
        document = next(
            (doc for docs in documents.values() for doc in docs if doc.get("id") == document_id),
            None,
        )
        if document is None:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        filename = str(document.get("name") or document_id)
        content = f"Mock Dify file content for {filename}\n".encode("utf-8")
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": content_disposition(filename)},
        )

    return router
