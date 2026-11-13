# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own and enforce the scope of NL2Agent tool calls from Runtime."""

import json
from dataclasses import asdict

from contracts.agentos import NL2AgentToolCall
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches
from infrastructure.redis.client import get_redis_client
from nexent.core.concurrency import run_blocking
from management.services.agent import nl2agent_tools as tools

_GRANT_TTL_SECONDS = 3600
_TOOL_ARGUMENTS = {
    "search_installed_resources": ({"requirements"}, set()),
    "search_uninstalled_resources": ({"requirements"}, {"exclude_refs"}),
    "recommend_resources": ({"candidates", "recommended_refs"}, set()),
    "wrapper": ({"subtype"}, {"resource_result", "questions"}),
    "save_agent_draft_fields": ({"fields"}, set()),
}


class NL2AgentToolScopeUnavailable(RuntimeError):
    """The run scope store cannot be used."""


def _redis():
    redis = get_redis_client()
    if redis is None:
        raise NL2AgentToolScopeUnavailable("NL2Agent run scope storage is unavailable")
    return redis


def _key(run_id: str) -> str:
    return f"agentos:nl2agent:grant:{run_id}"


def open_nl2agent_tool_grant(run_id: str, agent_id: int, actor: ServicePrincipal, policy_clarification: bool) -> None:
    scope = tools.NL2AgentToolScope(agent_id, actor.user_id, actor.tenant_id, policy_clarification)
    if not _redis().set(_key(run_id), json.dumps(asdict(scope)), ex=_GRANT_TTL_SECONDS, nx=True):
        raise NL2AgentToolScopeUnavailable("NL2Agent run scope already exists")


def close_nl2agent_tool_grant(run_id: str) -> None:
    _redis().delete(_key(run_id))


def _load_grant(call: NL2AgentToolCall, actor: ServicePrincipal) -> tools.NL2AgentToolScope | None:
    raw = _redis().get(_key(call.run_id))
    if raw is None:
        return None
    scope = tools.NL2AgentToolScope(**json.loads(raw))
    if (scope.user_id, scope.tenant_id, scope.agent_id) != (actor.user_id, actor.tenant_id, call.agent_id):
        return None
    with get_db_session() as session:
        if not tenant_membership_matches(session, actor.user_id, actor.tenant_id):
            return None
    return scope


async def execute_nl2agent_tool(call: NL2AgentToolCall, actor: ServicePrincipal) -> dict | str | None:
    required, optional = _TOOL_ARGUMENTS[call.tool]
    if not required <= call.arguments.keys() <= required | optional:
        raise ValueError("Invalid NL2Agent tool arguments")
    scope = await run_blocking(
        "nl2agent-tool-grant", _load_grant, call, actor, lane="control-io", owner="management",
    )
    if scope is None:
        return None
    handler = tools.nl2a_wrapper if call.tool == "wrapper" else getattr(tools, call.tool)
    with tools.bind_nl2agent_tool_scope(scope):
        return await handler(agent_id=call.agent_id, **call.arguments)
