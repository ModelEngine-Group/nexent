# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read a body-bound AgentOS callback for Management."""

from typing import TypeVar

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from contracts.agentos import ManagementOperation
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, verify_call

Payload = TypeVar("Payload", bound=BaseModel)


async def read_agentos_callback(
    request: Request, operation: ManagementOperation, schema: type[Payload],
) -> tuple[Payload, ServicePrincipal]:
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
        actor = verify_call(authorization[0].removeprefix("Bearer "), operation, body)
    except AgentOSIdentityError as exc:
        raise HTTPException(status_code=401, detail={"code": "AGENTOS_UNAUTHORIZED"}) from exc
    try:
        return schema.model_validate_json(body), actor
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_REQUEST"}) from exc
