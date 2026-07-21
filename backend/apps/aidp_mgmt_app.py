"""
AIDP Management App Layer
FastAPI endpoints for AIDP knowledge base CRUD and document management proxy.
"""
import logging
import os
from http import HTTPStatus
from typing import Annotated, List, Optional

from fastapi import APIRouter, File, Path, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from services.aidp_service import (
    count_aidp_docs_impl,
    count_aidp_kbs_impl,
    create_aidp_kb_impl,
    delete_aidp_kb_impl,
    fetch_aidp_knowledge_bases_impl,
    get_aidp_kb_impl,
    list_aidp_docs_impl,
    list_aidp_models_impl,
    update_aidp_kb_impl,
    upload_aidp_docs_impl,
)

aidp_mgmt_router = APIRouter(prefix="/aidp-mgmt")
logger = logging.getLogger("aidp_mgmt_app")


def _get_aidp_credentials() -> tuple[str, str]:
    server_url = os.environ.get("AIDP_SERVER_URL", "")
    api_key = os.environ.get("AIDP_API_KEY", "")
    return server_url, api_key


# ==================== Request Models ====================


class CreateKbRequest(BaseModel):
    """Request body for creating a knowledge base.

    All optional fields (chunk_token_num, vlm_model, caption_enable, etc.)
    must be explicitly declared so Pydantic v2 preserves them when the frontend
    sends them. Missing fields are filled in by ``_apply_create_defaults`` on
    the service side, aligned with AIDP's expected payload schema.
    """

    name: str = Field(..., description="Knowledge base name (required)")
    description: Optional[str] = Field(None, description="Knowledge base description")
    embedding_model: Optional[str] = Field(None, description="Embedding model identifier")
    is_multimodal: Optional[bool] = Field(None, description="Whether KB supports multimodal content")
    vision_model: Optional[str] = Field(None, description="Vision model identifier for multimodal KBs")
    # AIDP chunk pipeline configuration — forwarded verbatim to AIDP.
    chunk_token_num: Optional[int] = Field(None, description="Chunk size in tokens (> 0)")
    chunk_overlap_num: Optional[int] = Field(None, description="Chunk overlap in tokens (>= 0)")
    vlm_model: Optional[str] = Field(None, description="VLM model identifier for caption generation")
    is_personal: Optional[int] = Field(None, ge=0, le=1, description="Personal KB flag, int 0 or 1")
    topk: Optional[int] = Field(None, description="Top-K retrieval count")
    similarity: Optional[float] = Field(None, description="Similarity score threshold")
    smartsplit: Optional[int] = Field(None, ge=0, le=1, description="Smart chunking mode, int 0 or 1")
    # AIDP caption_enable: int 0/1.
    caption_enable: Optional[int] = Field(None, ge=0, le=1, description="Caption generation toggle, int 0 or 1")


class UpdateKbRequest(BaseModel):
    """Request body for updating a knowledge base."""

    name: Optional[str] = Field(None, description="Knowledge base name")
    description: Optional[str] = Field(None, description="Knowledge base description")


# ==================== Route Handlers ====================


@aidp_mgmt_router.get("/knowledge-bases")
async def list_knowledge_bases(
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
) -> JSONResponse:
    """List knowledge bases from AIDP (paginated) with total count."""
    try:
        server_url, api_key = _get_aidp_credentials()
        result = fetch_aidp_knowledge_bases_impl(
            server_url=server_url,
            api_key=api_key,
            page=page,
            page_size=page_size,
        )
        # AIDP list response behavior:
        #   - `total_count` field is the CURRENT PAGE count (equal to
        #     len(value)), NOT the true total. We must NOT use it as total.
        #   - `next_link` is the authoritative "more pages" signal.
        # Therefore we call the Count API to obtain the true total, and fall
        # back to `next_link` + page fullness only when Count fails.
        page_items = result.get("value", [])
        page_count = len(page_items) if isinstance(page_items, list) else 0

        count_reliable = False
        count_failed = False
        try:
            total_count = count_aidp_kbs_impl(
                server_url=server_url,
                api_key=api_key,
            )
            count_reliable = True
        except Exception as count_err:
            logger.warning(
                "AIDP Count API failed; true total unknown: %s", count_err
            )
            total_count = page_count
            count_failed = True

        # has_more: use Count API when available, otherwise combine next_link
        # and page fullness to detect additional pages.
        has_more = (
            total_count > page * page_size
            if count_reliable
            else bool(result.get("next_link")) or page_count >= page_size
        )

        # When Count failed, do not expose AIDP's misleading total_count
        # (which is just the page count). Keep `total_count` at the page
        # count as a defensive lower bound.
        result["total_count"] = int(total_count)
        result["has_more"] = has_more
        # Always include count_failed flag so the frontend knows the total
        # is approximate (useful for "共 N 条" display).
        if count_failed:
            result["total_reliable"] = False
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to list AIDP knowledge bases: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to list AIDP knowledge bases: {str(e)}",
        )


@aidp_mgmt_router.get("/knowledge-bases/count")
async def count_knowledge_bases() -> JSONResponse:
    """Get total count of knowledge bases from AIDP."""
    try:
        server_url, api_key = _get_aidp_credentials()
        total = count_aidp_kbs_impl(
            server_url=server_url,
            api_key=api_key,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"total_count": total})
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to count AIDP knowledge bases: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to count AIDP knowledge bases: {str(e)}",
        )


@aidp_mgmt_router.post("/knowledge-bases")
async def create_knowledge_base(
    body: CreateKbRequest,
) -> JSONResponse:
    """Create a new knowledge base via AIDP."""
    try:
        server_url, api_key = _get_aidp_credentials()
        payload = body.model_dump(exclude_none=True)
        result = create_aidp_kb_impl(
            server_url=server_url,
            api_key=api_key,
            payload=payload,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to create AIDP knowledge base: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to create AIDP knowledge base: {str(e)}",
        )


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}")
async def get_knowledge_base(
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
) -> JSONResponse:
    """Get details of a specific knowledge base."""
    try:
        server_url, api_key = _get_aidp_credentials()
        result = get_aidp_kb_impl(
            server_url=server_url,
            api_key=api_key,
            kds_id=kds_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to get AIDP knowledge base: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to get AIDP knowledge base: {str(e)}",
        )


@aidp_mgmt_router.put("/knowledge-bases/{kds_id}")
async def update_knowledge_base(
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: UpdateKbRequest,
) -> JSONResponse:
    """Update a knowledge base via AIDP."""
    try:
        payload = body.model_dump(exclude_none=True)
        if not payload:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                "At least one field (name or description) must be provided for update",
            )
        server_url, api_key = _get_aidp_credentials()
        result = update_aidp_kb_impl(
            server_url=server_url,
            api_key=api_key,
            kds_id=kds_id,
            payload=payload,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to update AIDP knowledge base: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to update AIDP knowledge base: {str(e)}",
        )


@aidp_mgmt_router.delete("/knowledge-bases/{kds_id}")
async def delete_knowledge_base(
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
) -> JSONResponse:
    """Delete a knowledge base via AIDP."""
    try:
        server_url, api_key = _get_aidp_credentials()
        success = delete_aidp_kb_impl(
            server_url=server_url,
            api_key=api_key,
            kds_id=kds_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to delete AIDP knowledge base: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to delete AIDP knowledge base: {str(e)}",
        )


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/documents")
async def upload_documents(
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    files: List[UploadFile] = File(..., description="Files to upload"),
) -> JSONResponse:
    """Upload documents to a knowledge base via AIDP."""
    try:
        server_url, api_key = _get_aidp_credentials()
        result = upload_aidp_docs_impl(
            server_url=server_url,
            api_key=api_key,
            kds_id=kds_id,
            files=files,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to upload documents to AIDP knowledge base: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to upload documents to AIDP knowledge base: {str(e)}",
        )


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}/documents")
async def list_documents(
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
) -> JSONResponse:
    """List documents in a knowledge base via AIDP."""
    try:
        server_url, api_key = _get_aidp_credentials()
        result = list_aidp_docs_impl(
            server_url=server_url,
            api_key=api_key,
            kds_id=kds_id,
            page=page,
            page_size=page_size,
        )
        # AIDP's doc list response does NOT return the true total count —
        # its `total_count` field is just the current page count. We must
        # call the dedicated Count API to get the accurate total, identical
        # to the KB list pattern.
        page_items = result.get("value", [])
        page_count = len(page_items) if isinstance(page_items, list) else 0

        count_reliable = False
        count_failed = False
        try:
            total_count = count_aidp_docs_impl(
                server_url=server_url,
                api_key=api_key,
                kds_id=kds_id,
            )
            count_reliable = True
        except Exception as count_err:
            logger.warning(
                "AIDP doc Count API failed for KB %s; true total unknown: %s",
                kds_id,
                count_err,
            )
            total_count = page_count
            count_failed = True

        # has_more: use Count API when available, otherwise combine next_link
        # and page fullness to detect additional pages.
        has_more = (
            total_count > page * page_size
            if count_reliable
            else bool(result.get("next_link")) or page_count >= page_size
        )

        result["total_count"] = int(total_count)
        result["has_more"] = has_more
        if count_failed:
            result["total_reliable"] = False
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to list AIDP documents: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to list AIDP documents: {str(e)}",
        )


@aidp_mgmt_router.get("/models")
async def list_models(
    service: Annotated[str, Query(description="Model service category (default: llm)")] = "llm",
    app: Annotated[str, Query(description="Application filter (default: KnowledgeBase)")] = "KnowledgeBase",
) -> JSONResponse:
    """List available models from AIDP ModelService.

    Queries the AIDP ModelService for models applicable to the given
    ``app`` (default ``KnowledgeBase``). Response is post-filtered on
    the server side — AIDP's own query filtering is advisory only.
    """
    try:
        server_url, api_key = _get_aidp_credentials()
        result = list_aidp_models_impl(
            server_url=server_url,
            api_key=api_key,
            service=service,
            app=app,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to list AIDP models: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to list AIDP models: {str(e)}",
        )
