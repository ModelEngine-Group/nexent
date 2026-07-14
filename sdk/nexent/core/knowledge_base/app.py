"""FastAPI service exposing the Nexent standard knowledge-base adapter API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..ext_components.aidp.knowledge_base.aidp_client import AidpAdapterError, AidpClient
from .config import ADAPTER_PLATFORM, ADAPTER_VERSION
from .mapper import (
    build_create_payload,
    build_retrieve_payload,
    build_update_payload,
    error_response,
    map_document_list,
    map_knowledge_base,
    map_knowledge_base_list,
    map_retrieve_response,
    map_upload_response,
    success_response,
)


app = FastAPI(title="AIDP Knowledge Base Adapter", version=ADAPTER_VERSION)
client = AidpClient()


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    embedding_model: str | None = None
    is_multimodal: bool = False
    vision_model: str | None = None


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class RerankingModel(BaseModel):
    provider: str | None = ""
    model: str | None = ""


class RetrievalModel(BaseModel):
    search_method: str = "semantic_search"
    top_k: int = 5
    score_threshold: float = 0.0
    score_threshold_enabled: bool = False
    reranking_enable: bool = False
    reranking_model: RerankingModel | None = None


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    knowledge_base_ids: list[str] = Field(min_length=1, max_length=10)
    retrieval_model: RetrievalModel | None = None


def _http_status_for_upstream(status_code: int) -> int:
    if status_code in (400, 401, 403, 404, 409, 422, 429, 500, 503):
        return status_code
    return 500


def _standard_code_for_upstream(status_code: int) -> int:
    if status_code in (400, 422):
        return 40001
    if status_code == 404:
        return 40002
    if status_code == 409:
        return 40003
    if status_code == 503:
        return 50002
    return 50001


def _upstream_error(exc: AidpAdapterError) -> JSONResponse:
    status_code = _http_status_for_upstream(exc.status_code)
    standard_code = _standard_code_for_upstream(exc.status_code)
    return JSONResponse(status_code=status_code, content=error_response(standard_code, str(exc)))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=error_response(40001, "Invalid request parameters"),
    )


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        reachable = client.health_check()
    except Exception:
        reachable = False
    return {
        "status": "ok" if reachable else "error",
        "platform": ADAPTER_PLATFORM,
        "version": ADAPTER_VERSION,
        "external_kb_reachable": reachable,
    }


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "create_knowledge_base": True,
        "delete_knowledge_base": True,
        "update_knowledge_base": True,
        "upload_document": True,
        "delete_document": False,
        "list_documents": True,
        "query_document_status": False,
        "download_document": False,
        "list_models": False,
        "search_modes": ["semantic_search", "keyword_search", "hybrid_search"],
        "supports_rerank": True,
        "supports_multimodal": True,
        "supports_batch_search": True,
        "max_kb_ids_per_search": 10,
        "requires_embedding_model": False,
        "supports_custom_embedding_model": False,
    }


@app.post("/api/v1/knowledge-bases")
def create_knowledge_base(body: KnowledgeBaseCreateRequest) -> dict[str, Any] | JSONResponse:
    try:
        created = client.create_knowledge_base(build_create_payload(body.model_dump()))
        knowledge_base_id = str(created.get("kds_id") or "")
        if knowledge_base_id:
            try:
                detail = client.get_knowledge_base(knowledge_base_id)
                return success_response(map_knowledge_base(detail))
            except AidpAdapterError:
                pass
        return success_response(
            {
                "id": knowledge_base_id,
                "name": body.name,
                "description": body.description,
                "embedding_model": body.embedding_model or "default",
                "document_count": 0,
                "status": "active",
                "created_at": "",
                "updated_at": "",
            }
        )
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.get("/api/v1/knowledge-bases")
def list_knowledge_bases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any] | JSONResponse:
    try:
        raw = client.list_knowledge_bases(page=page, page_size=page_size)
        total_count = client.count_knowledge_bases(is_personal=0)
        return success_response(map_knowledge_base_list(raw, page, page_size, total_count))
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.get("/api/v1/knowledge-bases/{knowledge_base_id}")
def get_knowledge_base(knowledge_base_id: str) -> dict[str, Any] | JSONResponse:
    try:
        return success_response(map_knowledge_base(client.get_knowledge_base(knowledge_base_id)))
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.put("/api/v1/knowledge-bases/{knowledge_base_id}")
def update_knowledge_base(knowledge_base_id: str, body: KnowledgeBaseUpdateRequest) -> dict[str, Any] | JSONResponse:
    try:
        payload = build_update_payload(body.model_dump())
        if payload:
            client.update_knowledge_base(knowledge_base_id, payload)
        return success_response(map_knowledge_base(client.get_knowledge_base(knowledge_base_id)))
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.delete("/api/v1/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: str) -> dict[str, Any] | JSONResponse:
    try:
        client.delete_knowledge_base(knowledge_base_id)
        return success_response({"success": True})
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.post("/api/v1/knowledge-bases/{knowledge_base_id}/documents")
async def upload_documents(
    knowledge_base_id: str,
    file: list[UploadFile] = File(...),
) -> dict[str, Any] | JSONResponse:
    try:
        files = []
        for upload in file:
            content = await upload.read()
            files.append((upload.filename or "file", content, upload.content_type or "application/octet-stream"))
        raw = client.upload_documents(knowledge_base_id, files)
        return success_response(map_upload_response(raw))
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.get("/api/v1/knowledge-bases/{knowledge_base_id}/documents")
def list_documents(
    knowledge_base_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
) -> dict[str, Any] | JSONResponse:
    if status and status != "completed":
        return success_response({"list": [], "total": 0, "page": page, "page_size": page_size, "has_more": False})
    try:
        raw = client.list_documents(knowledge_base_id, page=page, page_size=page_size)
        return success_response(map_document_list(raw, knowledge_base_id, page, page_size))
    except AidpAdapterError as exc:
        return _upstream_error(exc)


@app.delete("/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
def delete_document(knowledge_base_id: str, document_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content=error_response(50004, "Document deletion is not implemented for the AIDP adapter yet."),
    )


@app.post("/api/v1/retrieve")
def retrieve(body: RetrieveRequest) -> dict[str, Any] | JSONResponse:
    request_body = body.model_dump()
    try:
        raw = client.retrieve(build_retrieve_payload(request_body))
        return success_response(map_retrieve_response(raw, body.query, body.knowledge_base_ids))
    except AidpAdapterError as exc:
        return _upstream_error(exc)
