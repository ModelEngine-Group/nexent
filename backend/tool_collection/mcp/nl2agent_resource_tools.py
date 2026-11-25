# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Local MCP tools for the versioned resource workflow."""

import json
import logging
from typing import Literal
from uuid import uuid4

from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.tool import ToolResult
from pydantic import TypeAdapter, ValidationError

from contracts.errors.exceptions import AgentDraftEditError, UnauthorizedError
from contracts.nl2agent_resources import (
    MAX_REQUIREMENTS,
    MAX_REQUIREMENTS_PER_VERIFICATION_BATCH,
    BilingualSearchQueries,
    Identifier,
    RequirementDiscoveryInput,
    ResourcePurpose,
    VerificationCheck,
)
from management.services.permission.identity.session import get_current_user_id
from management.services.agent.authorization import require_agent_draft_edit
from services import nl2agent_resource_flow as flow
from management.services.agent.nl2agent import Nl2AgentResourceError, read_generation_state
from services.nl2agent_state_service import ResourceScope, ResourceStateError
from management.services.agent.nl2agent_tools import (
    tool_headers, _tool_scope, _tool_actor,
    NL2AGENT_AGENT_ID_HEADER,
    NL2AGENT_CONVERSATION_ID_HEADER,
    NL2AGENT_RECEIPT_KEY,
    NL2AGENT_RUN_ID_HEADER,
)

logger = logging.getLogger(__name__)
_requirements = TypeAdapter(list[RequirementDiscoveryInput])
_checks = TypeAdapter(list[VerificationCheck])
_search_queries = TypeAdapter(dict[Identifier, BilingualSearchQueries])


def _scope() -> ResourceScope:
    headers = tool_headers() if _tool_scope.get() is not None else get_http_request().headers
    run_id = headers.get(NL2AGENT_RUN_ID_HEADER)
    conversation_id = headers.get(NL2AGENT_CONVERSATION_ID_HEADER)
    try:
        agent_id = int(headers.get(NL2AGENT_AGENT_ID_HEADER, "0"))
    except ValueError as exc:
        raise ResourceStateError("invalid_resource_context") from exc
    if not run_id or not conversation_id or agent_id <= 0:
        raise ResourceStateError("invalid_resource_context")
    user_id, tenant_id = _tool_actor() if _tool_scope.get() is not None else get_current_user_id(headers.get("Authorization"))
    require_agent_draft_edit(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    return ResourceScope(tenant_id, user_id, agent_id, conversation_id, run_id)


def _error(code: str, retryable: bool = False) -> dict:
    return {"status": "error", "code": code, "retryable": retryable}


async def _run(operation, *args):
    try:
        scope = _scope()
        return scope, await operation(scope, *args)
    except (ResourceStateError, Nl2AgentResourceError) as exc:
        return None, _error(exc.code, exc.retryable)
    except AgentDraftEditError as exc:
        return None, _error(exc.code)
    except (PermissionError, UnauthorizedError):
        return None, _error("unauthorized")
    except Exception:
        logger.exception("NL2Agent resource tool failed")
        return None, _error("resource_workflow_failed", retryable=True)


async def discover_requirements(
    requirements: list[dict] | None = None, purpose: ResourcePurpose = "generate",
    search_queries: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Keep knowledge content in query for KB recommendation; search_queries describe only tool capability.
    For clinical guidelines/internal hospital materials use knowledge retrieval / knowledge base search.
    A named knowledge base is content scope, not a tool/provider constraint.
    Discover candidates; prepare requested zh/en search_queries by requirement ID on resume."""
    if requirements is not None and len(requirements) > MAX_REQUIREMENTS:
        return {**_error("requirements_limit_exceeded"), "max_requirements": MAX_REQUIREMENTS}
    try:
        parsed = None if requirements is None else _requirements.validate_python(requirements)
        if search_queries is not None and (requirements is not None or not 1 <= len(search_queries) <= MAX_REQUIREMENTS):
            return _error("invalid_search_queries")
        queries = None if search_queries is None else _search_queries.validate_python(search_queries)
    except ValidationError:
        return _error("invalid_requirements")
    _, result = await _run(flow.discover, parsed, purpose, queries)
    return result


async def verify_requirements(verification_batch_id: str, checks: list[dict]) -> ToolResult:
    """Assess every candidate independently, retaining ALL that meet the original requirement.

    Each check includes requirement_id, accepted and assessments. assessments contains
    one {candidate_ref, satisfies: bool, reason: str} for EVERY offered candidate.
    accepted must contain exactly all satisfies=true references. Reject only for a
    capability/source/constraint mismatch, never for redundancy, preference, retrieval
    score or needing user configuration. Binding chooses defaults after verification.
    """
    if not verification_batch_id or not 1 <= len(checks) <= MAX_REQUIREMENTS_PER_VERIFICATION_BATCH:
        return ToolResult(content=json.dumps(_error("invalid_verification")))
    try:
        parsed = _checks.validate_python(checks)
    except ValidationError:
        return ToolResult(content=json.dumps(_error("invalid_verification")))
    scope, result = await _run(flow.verify, verification_batch_id, parsed)
    if scope is None or result.get("verification_batch_id") is not None or result.get("next_step"):
        return ToolResult(content=json.dumps(result, ensure_ascii=False))
    return await show_resource_card()


async def show_resource_card() -> ToolResult:
    """Publish only the card selected from the current verified state."""
    scope, result = await _run(flow.show_card)
    if scope is None:
        return ToolResult(content=json.dumps(result))
    if result is None:
        return ToolResult(content=json.dumps({"status": "success", "card_required": False}))
    return ToolResult(
        content=json.dumps({"status": "success", "card_required": True}),
        meta={NL2AGENT_RECEIPT_KEY: {
            "event_id": uuid4().hex, "run_id": scope.run_id, "conversation_id": scope.conversation_id,
            "payload": result,
        }},
    )


async def _read_generation_context(scope: ResourceScope, goal: str = "prompt") -> dict:
    state = await read_generation_state(
        agent_id=scope.agent_id, tenant_id=scope.tenant_id, user_id=scope.user_id,
        include_binding_revision=True,
    )
    from services.nl2agent_prompt_service import read_pending, refresh_basis
    await refresh_basis(scope, state, complete_generation=goal == "complete")
    state.pop("binding_revision")
    pending = await read_pending(scope)
    if pending:
        state["pending_prompt"] = pending
    return {"status": "success", **state}


async def read_generation_context(goal: Literal["prompt", "complete"] = "prompt") -> dict:
    """Read generation facts without using temporary resource state."""
    if goal not in {"prompt", "complete"}:
        return _error("invalid_generation_goal")
    _, result = await _run(_read_generation_context, goal)
    return result
