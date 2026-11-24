# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private AgentOS entry point for Runtime's scheduled-task proposal tool."""

from fastapi import APIRouter, HTTPException, Request

from contracts.agentos import AgentRunReference, ManagementOperation
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.api.agentos_request import read_agentos_callback
from management.services.automation.agentos_callback import create_automation_proposal

router = APIRouter()
_OPERATION = ManagementOperation.AUTOMATION_PROPOSAL


@router.post(_OPERATION.value, include_in_schema=False)
async def automation_proposal(request: Request):
    reference, actor = await read_agentos_callback(request, _OPERATION, AgentRunReference)
    try:
        proposal = await create_automation_proposal(reference, actor)
    except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_AUTOMATION_UNAVAILABLE"}) from exc
    if proposal is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    return proposal
