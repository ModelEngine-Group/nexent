# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP endpoints for the independent AIDP search connector."""

from contracts.knowledge import IndependentAidpKnowledgeBaseListRequest
from io import BytesIO

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from management.services.knowledge_base.providers.aidp import (
    IndependentAidpServiceError,
    fetch_ind_aidp_image_impl,
    fetch_ind_aidp_knowledge_bases_impl,
)
from gateway.authentication.identity import get_current_user_id

router = APIRouter(prefix="/ind-aidp", tags=["independent-aidp"])


@router.post("/knowledge-bases/list")
async def list_ind_aidp_knowledge_bases(
    request: IndependentAidpKnowledgeBaseListRequest,
    authorization: Optional[str] = Header(None),
):
    """List AIDP knowledge bases for the tool configuration modal."""
    try:
        get_current_user_id(authorization)
        return await fetch_ind_aidp_knowledge_bases_impl(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IndependentAidpServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/images/{image_ref}")
async def proxy_ind_aidp_image(image_ref: str):
    """Stream an AIDP image without exposing its API key to the browser."""
    try:
        content, content_type = await fetch_ind_aidp_image_impl(image_ref)
        return StreamingResponse(
            BytesIO(content),
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except IndependentAidpServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
