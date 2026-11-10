# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private AgentOS entry point for Runtime's scheduled-task proposal tool."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from contracts.agentos import AgentRunReference, ManagementOperation
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from infrastructure.agentos_identity import AgentOSIdentityError, verify_call
from management.services.automation.agentos_callback import create_automation_proposal

router = APIRouter()
_OPERATION = ManagementOperation.AUTOMATION_PROPOSAL


@router.post(_OPERATION.value, include_in_schema=False)
async def automation_proposal(request: Request):
    authorization = request.headers.getlist("authorization")
    if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "AGENTOS_UNAUTHORIZED"})
    if request.scope["query_string"]:
        raise HTTPException(status_code=400, detail={"code": "AGENTOS_INVALID_REQUEST"})
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > 1024:
            raise HTTPException(status_code=413, detail={"code": "AGENTOS_REQUEST_TOO_LARGE"})
    body = bytes(buffer)
    try:
        actor = verify_call(authorization[0].removeprefix("Bearer "), _OPERATION, body)
    except AgentOSIdentityError as exc:
        raise HTTPException(status_code=401, detail={"code": "AGENTOS_UNAUTHORIZED"}) from exc
    try:
        reference = AgentRunReference.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_REQUEST"}) from exc
    try:
        proposal = await create_automation_proposal(reference, actor)
    except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_AUTOMATION_UNAVAILABLE"}) from exc
    if proposal is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    return proposal
