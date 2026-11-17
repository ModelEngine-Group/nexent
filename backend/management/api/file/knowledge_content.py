# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public authenticated access to versioned KB source and image references."""

import mimetypes
from typing import Annotated

from contracts.agentos_knowledge import KnowledgeContentRequest
from fastapi import APIRouter, Header, HTTPException, Response
from management.api.file.http import build_content_disposition_header
from management.services.knowledge_base.content import fetch_knowledge_content
from management.services.permission.identity.session import get_current_user_id
from nexent.storage.errors import DeadlineExceeded

from backend.http.server.knowledge_errors import knowledge_error

router = APIRouter(prefix="/file/knowledge")


@router.post("/content")
async def read_content(
    payload: KnowledgeContentRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    user_id, tenant_id = get_current_user_id(authorization)
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
