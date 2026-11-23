# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public authenticated access to versioned KB source and image references."""

import mimetypes
from typing import Annotated

from contracts.agentos_knowledge import (
    KnowledgeContentRequest,
    KnowledgeLegacyImageRequest,
)
from fastapi import APIRouter, Header, HTTPException, Response
from management.api.file.http import build_content_disposition_header
from management.services.knowledge_base.content import fetch_knowledge_content
from management.services.knowledge_base.image_ticket import open_image_ticket
from management.services.permission.identity.session import get_current_user_id
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from backend.http.server.knowledge_errors import knowledge_error
from infrastructure.agentos_identity import ServicePrincipal

router = APIRouter(prefix="/file/knowledge")


@router.post("/content")
async def read_content(
    payload: KnowledgeContentRequest | KnowledgeLegacyImageRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    user_id, tenant_id = get_current_user_id(authorization)
    return await _content_response(payload, user_id, tenant_id)


@router.get("/content")
async def read_image(
    ticket: str,
    authorization: Annotated[str | None, Header()] = None,
):
    user_id, tenant_id = get_current_user_id(authorization)
    return await read_image_ticket(ticket, user_id, tenant_id)


async def read_image_ticket(ticket, user_id, tenant_id, *, northbound=False):
    try:
        payload = open_image_ticket(ticket, ServicePrincipal(user_id, tenant_id), northbound=northbound)
    except ScopeDenied as error:
        return knowledge_error(error)
    return await _content_response(payload, user_id, tenant_id)


async def _content_response(payload, user_id, tenant_id):
    try:
        data, filename = await fetch_knowledge_content(
            payload, user_id=user_id, tenant_id=tenant_id
        )
        image = payload.image_ref is not None
        selected_name = payload.image_ref.key if image else filename
        media_type = (
            mimetypes.guess_type(selected_name)[0] or "application/octet-stream"
        )
        return Response(
            data,
            media_type=media_type,
            headers={
                "Content-Disposition": "inline"
                if image
                else build_content_disposition_header(filename),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )
    except HTTPException:
        raise
    except TimeoutError:
        return knowledge_error(DeadlineExceeded())
    except Exception as error:  # noqa: BLE001 - The content boundary redacts storage and policy failures.
        return knowledge_error(error)
