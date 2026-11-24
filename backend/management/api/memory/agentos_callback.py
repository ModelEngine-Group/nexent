# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private notification from the Runtime Memory store."""

from fastapi import APIRouter, HTTPException, Request, Response

from contracts.agentos import AgentMemoryStored, ManagementOperation
from management.api.agentos_request import read_agentos_callback
from management.services.memory.agentos_callback import ingest_stored_agent_memory

router = APIRouter()
_OPERATION = ManagementOperation.MEMORY_STORED


@router.post(_OPERATION.value, status_code=204, response_class=Response, include_in_schema=False)
async def memory_stored(request: Request):
    notice, actor = await read_agentos_callback(request, _OPERATION, AgentMemoryStored)
    if not await ingest_stored_agent_memory(notice, actor):
        raise HTTPException(status_code=404, detail={"code": "MEMORY_SCOPE_NOT_FOUND"})
    return Response(status_code=204)
