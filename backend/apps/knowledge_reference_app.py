# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch knowledge-resource status API and deletion reference preview.

Powers the per-item knowledge status markers in the agent configuration and
the conversation knowledge selector, plus the second confirmation dialog of a
knowledge-base deletion. Both endpoints are read-only: they never modify
persisted configuration and never return names or metadata for resources the
caller cannot access.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from consts.model import (
    KnowledgeReferencePreviewRequest,
    KnowledgeResourceStatusRequest,
)
from database.conversation_db import get_conversation
from management.services.knowledge_base.service import get_vector_db_core
from services.knowledge_reference_service import (
    assert_agent_context_visible,
    collect_agent_reference_preview,
    resolve_item_statuses,
)
from utils.auth_utils import get_current_user_id
from utils.knowledge_reference import (
    MAX_STATUS_ITEMS,
    PROVIDER_LOCAL,
    SUPPORTED_PROVIDERS,
)


logger = logging.getLogger("knowledge_reference_app")

router = APIRouter(prefix="/knowledge-bases")


@router.post("/statuses")
async def query_knowledge_resource_statuses(
    request: KnowledgeResourceStatusRequest,
    authorization: Optional[str] = Header(None),
):
    """Return the availability status of the requested knowledge resources."""
    user_id, tenant_id = get_current_user_id(authorization)

    raw_items = request.items or []
    if len(raw_items) > MAX_STATUS_ITEMS:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            details={"max_items": MAX_STATUS_ITEMS, "received": len(raw_items)},
        )

    refs = []
    for item in raw_items:
        provider = str(item.provider or "").strip().lower()
        resource_id = str(item.resource_id or "").strip()
        if provider not in SUPPORTED_PROVIDERS or not resource_id:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                details={"item": item.model_dump()},
            )
        refs.append((provider, resource_id))

    context = request.context or {}
    context_type = str(context.get("type") or "selection").strip().lower()
    if context_type == "agent":
        agent_id = context.get("agent_id")
        if agent_id is None:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                details={"context": "agent_id is required"},
            )
        assert_agent_context_visible(int(agent_id), user_id=user_id, tenant_id=tenant_id)
    elif context_type == "conversation":
        conversation_id = context.get("conversation_id")
        if conversation_id is None:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                details={"context": "conversation_id is required"},
            )
        conversation = get_conversation(
            int(conversation_id), user_id=user_id, tenant_id=tenant_id
        )
        if conversation is None:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND,
                details={"resource": "conversation"},
            )
    elif context_type != "selection":
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            details={"context_type": context_type},
        )

    vdb_core = None
    if any(provider == PROVIDER_LOCAL for provider, _ in refs):
        try:
            vdb_core = get_vector_db_core()
        except Exception:
            logger.warning(
                "Vector database core is unavailable for knowledge status check",
                exc_info=True,
            )
            vdb_core = None

    items = resolve_item_statuses(
        refs, user_id=user_id, tenant_id=tenant_id, vdb_core=vdb_core
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"items": items})


@router.post("/reference-preview")
async def query_knowledge_reference_preview(
    request: KnowledgeReferencePreviewRequest,
    authorization: Optional[str] = Header(None),
):
    """List the agents bound to one resource for the delete confirmation dialog.

    The caller must already be able to access the resource; anything else is
    reported as forbidden so the endpoint cannot be used to probe bindings of
    resources the caller cannot see.
    """
    user_id, tenant_id = get_current_user_id(authorization)

    provider = str(request.provider or "").strip().lower()
    resource_id = str(request.resource_id or "").strip()
    if provider not in SUPPORTED_PROVIDERS or not resource_id:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            details={"provider": request.provider, "resource_id": request.resource_id},
        )

    resources = [(provider, resource_id)]
    status = resolve_item_statuses(
        resources, user_id=user_id, tenant_id=tenant_id, vdb_core=None
    )[0]
    if status.get("status") != "available":
        raise AppException(
            ErrorCode.COMMON_FORBIDDEN,
            details={"resource": "knowledge"},
        )

    preview = collect_agent_reference_preview(
        resources, user_id=user_id, tenant_id=tenant_id
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=preview)
