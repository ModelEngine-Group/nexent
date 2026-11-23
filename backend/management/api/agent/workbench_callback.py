# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Serve run-scoped Workbench mount overrides to Runtime over AgentOS."""

from fastapi import APIRouter, HTTPException, Request, Response
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from contracts.agentos import ManagementOperation, WorkbenchDebugSkillLookup, WorkbenchSkillLookup, WorkbenchSkillMounts
from management.api.agentos_request import read_agentos_callback
from management.db.conversation.prepared_turn import read_workbench_skill_mounts
from management.services.agent.workbench_debug_grant import WorkbenchDebugGrantUnavailable, read_workbench_debug_grant
from nexent.core.concurrency import run_blocking

router = APIRouter()
_OPERATION = ManagementOperation.WORKBENCH_SKILL_MOUNTS
_DEBUG_OPERATION = ManagementOperation.WORKBENCH_DEBUG_SKILL_MOUNTS


@router.post(_OPERATION.value, response_model=WorkbenchSkillMounts, include_in_schema=False)
async def workbench_skill_mounts(request: Request, response: Response):
    lookup, actor = await read_agentos_callback(request, _OPERATION, WorkbenchSkillLookup)
    try:
        mounts = await run_blocking(
            "agentos-workbench-mounts", read_workbench_skill_mounts, lookup, actor.user_id, actor.tenant_id,
            lane="control-io", owner="management",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"}) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_WORKBENCH_SCOPE_UNAVAILABLE"}) from exc
    if mounts is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_SKILL_NOT_FOUND"})
    response.headers["Cache-Control"] = "no-store"
    return mounts


@router.post(_DEBUG_OPERATION.value, response_model=WorkbenchSkillMounts, include_in_schema=False)
async def workbench_debug_skill_mounts(request: Request, response: Response):
    lookup, actor = await read_agentos_callback(request, _DEBUG_OPERATION, WorkbenchDebugSkillLookup)
    try:
        mounts = await run_blocking(
            "agentos-workbench-debug-mounts", read_workbench_debug_grant, lookup, actor,
            lane="control-io", owner="management",
        )
    except (RedisError, SQLAlchemyError, ValueError, WorkbenchDebugGrantUnavailable) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_WORKBENCH_SCOPE_UNAVAILABLE"}) from exc
    if mounts is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_SKILL_NOT_FOUND"})
    response.headers["Cache-Control"] = "no-store"
    return mounts
