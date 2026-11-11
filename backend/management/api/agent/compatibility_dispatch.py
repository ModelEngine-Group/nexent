# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Accept old Runtime public starts as signed Management-owned submissions."""

from fastapi import APIRouter, HTTPException, Request

from contracts.agentos import MAX_REQUEST_BYTES, CompatibilityConversationRun, ManagementOperation
from management.api.agentos_request import read_agentos_callback
from management.services.agent.runtime_client import forward_conversation_run

router = APIRouter()
_OPERATION = ManagementOperation.CONVERSATION_DISPATCH


@router.post(_OPERATION.value, include_in_schema=False)
async def dispatch_conversation(request: Request):
    payload, actor = await read_agentos_callback(
        request, _OPERATION, CompatibilityConversationRun, max_bytes=MAX_REQUEST_BYTES,
    )
    if payload.preparation == "legacy":
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_PREPARATION_HANDOFF"})
    return await forward_conversation_run(payload, actor.user_id, actor.tenant_id)
