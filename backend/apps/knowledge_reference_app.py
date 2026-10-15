# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge binding preview for the deletion confirmation dialog."""

from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from consts.model import KnowledgeReferencePreviewRequest
from management.services.agent.read import collect_agent_reference_preview
from utils.auth_utils import get_current_user_id


router = APIRouter(prefix="/knowledge-bases")


@router.post("/reference-preview")
async def query_knowledge_reference_preview(
    request: KnowledgeReferencePreviewRequest,
    authorization: Optional[str] = Header(None),
):
    """Return visible agent bindings without checking the knowledge resource."""
    user_id, tenant_id = get_current_user_id(authorization)
    preview = await run_blocking(
        "preview-knowledge-bindings",
        collect_agent_reference_preview,
        [(request.provider, request.resource_id)],
        user_id=user_id,
        tenant_id=tenant_id,
        lane="control-io",
        owner="apps.knowledge_reference_app",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=preview)
