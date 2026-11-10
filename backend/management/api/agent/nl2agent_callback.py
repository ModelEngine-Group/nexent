# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private AgentOS endpoint for NL2Agent resource and draft tools."""

from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError

from contracts.agentos import MAX_REQUEST_BYTES, ManagementOperation, NL2AgentToolCall
from management.api.agentos_request import read_agentos_callback
from management.services.agent.nl2agent_callback import NL2AgentToolScopeUnavailable, execute_nl2agent_tool

router = APIRouter()
_OPERATION = ManagementOperation.NL2AGENT_TOOL


@router.post(_OPERATION.value, include_in_schema=False)
async def nl2agent_tool(request: Request):
    call, actor = await read_agentos_callback(request, _OPERATION, NL2AgentToolCall, max_bytes=MAX_REQUEST_BYTES)
    try:
        result = await execute_nl2agent_tool(call, actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_TOOL_ARGUMENTS"}) from exc
    except (NL2AgentToolScopeUnavailable, RedisError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_RUN_SCOPE_UNAVAILABLE"}) from exc
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    return result
