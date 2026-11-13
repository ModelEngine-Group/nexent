# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS debug ownership and cancellation across Runtime instances."""

import json
from hashlib import sha256

from fastapi import HTTPException

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking
from runtime.executions import agent_run_manager, registered_stop_response


def debug_owner(actor: ServicePrincipal) -> str:
    scope = json.dumps([actor.tenant_id, actor.user_id], ensure_ascii=False, separators=(",", ":")).encode()
    return f"agentos-debug-{sha256(scope).hexdigest()}"


async def stop_agentos_debug(run_id: str, actor: ServicePrincipal) -> dict:
    def stop_debug():
        with get_db_session() as session:
            if not tenant_membership_matches(session, actor.user_id, actor.tenant_id):
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
        owner = debug_owner(actor)
        if (agent_run_manager.get_agent_run_info(run_id, owner) is not None
                or runtime_state_service.get_run_state(owner, run_id).get("status") == "running"):
            stopped = agent_run_manager.stop_agent_run(run_id, owner)
        else:
            # Legacy keys omit the tenant. Require ownership from the live info or stored metadata.
            legacy = agent_run_manager.get_agent_run_info(run_id, actor.user_id)
            state = runtime_state_service.get_run_state(actor.user_id, run_id) if legacy is None else {}
            owned = (
                getattr(legacy, "tenant_id", None) == actor.tenant_id if legacy is not None
                else state.get("status") == "running" and state.get("tenant_id") == actor.tenant_id
            )
            stopped = owned and agent_run_manager.stop_agent_run(run_id, actor.user_id)
        return registered_stop_response(run_id, actor.user_id, stopped)

    return await run_blocking("agentos-stop-debug", stop_debug, lane="control-io", owner="runtime")
