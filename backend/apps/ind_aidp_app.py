"""HTTP endpoints for the independent AIDP search connector."""

from io import BytesIO

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.ind_aidp_service import (
    IndependentAidpServiceError,
    fetch_ind_aidp_image_impl,
    fetch_ind_aidp_knowledge_bases_impl,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/ind-aidp", tags=["independent-aidp"])


class IndependentAidpKnowledgeBaseListRequest(BaseModel):
    server_url: str = Field(..., description="Independent AIDP API base URL")
    api_key: str = Field(..., description="Independent AIDP API key")
    tenant_id: str = Field(default="aidp", description="AIDP tenant identifier")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)


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
