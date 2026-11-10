# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize and dispatch NL2Agent creation through AgentOS."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import uuid4

from anyio import CancelScope
from redis.exceptions import RedisError

from contracts.agent import NL2AgentRunRequest
from contracts.agentos import PreparedAgentCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.agentos_events import iter_sse_frames
from management.services.agent.nl2agent import (
    Nl2AgentDraftSaveError, _build_verified_bound_resources_context, _parse_nl2agent_card_action_agent_id,
    _requires_policy_clarification,
)
from management.services.agent.nl2agent_callback import (
    NL2AgentToolScopeUnavailable, close_nl2agent_tool_grant, open_nl2agent_tool_grant,
)
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from management.services.agent.runtime_client import forward_creator_run
from management.services.model.creator_snapshot import prepare_creator_model
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)


async def prepare_nl2agent_snapshot(
    request: NL2AgentRunRequest, actor: ServicePrincipal, language: str,
) -> PreparedAgentCreatorRun:
    action_agent_id = _parse_nl2agent_card_action_agent_id(request.query)
    if action_agent_id is not None and request.agent_id != action_agent_id:
        raise Nl2AgentDraftSaveError("agent_context_mismatch")
    model_scope = await run_blocking(
        "nl2agent-model", prepare_creator_model, request, actor.tenant_id, lane="control-io", owner="management",
    )
    context = await _build_verified_bound_resources_context(
        agent_id=request.agent_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
    )
    run_input = await run_blocking(
        "nl2agent-input", build_evaluation_input, request.query, request.minio_files,
        [item for item in request.history or [] if item.role in {"user", "assistant"}],
        actor.user_id, actor.tenant_id, lane="control-io", owner="management",
    )
    return PreparedAgentCreatorRun(
        mode="nl2agent", run_id=uuid4().hex, agent_id=request.agent_id, input=run_input,
        bound_resources=context.content["text"], language="en" if language == "en" else "zh", **model_scope,
    )


async def create_nl2agent_stream(payload: PreparedAgentCreatorRun, actor: ServicePrincipal) -> AsyncIterator[str]:
    granted = False
    try:
        with CancelScope(shield=True):
            await run_blocking(
                "nl2agent-open-tool-grant", open_nl2agent_tool_grant, payload.run_id, payload.agent_id, actor,
                _requires_policy_clarification(payload.input.query), lane="control-io", owner="management",
            )
            granted = True
        response = await forward_creator_run(payload, actor.user_id, actor.tenant_id)
        async with aclosing(iter_sse_frames(response)) as frames:
            if response.status_code != 200:
                await anext(frames, None)
                raise RuntimeError("NL2Agent execution was rejected by Runtime")
            async for frame in frames:
                if frame == b"event: agentos_execution_complete\ndata: {}":
                    return
                if frame.startswith(b"event: agentos_execution_error\ndata: "):
                    yield frame.split(b"\n", 1)[1].decode() + "\n\n"
                    return
                if frame.startswith(b"data: "):
                    yield frame.decode() + "\n\n"
                    if json.loads(frame[6:]).get("type") == "nl2a":
                        return
            raise RuntimeError("NL2Agent stream ended before the Runtime terminal")
    except Exception:
        logger.exception("NL2Agent AgentOS dispatch failed")
        yield 'data: {"type":"error","content":"NL2Agent execution failed."}\n\n'
    finally:
        if granted:
            with CancelScope(shield=True):
                try:
                    await run_blocking(
                        "nl2agent-close-tool-grant", close_nl2agent_tool_grant, payload.run_id,
                        lane="control-io", owner="management",
                    )
                except (RedisError, NL2AgentToolScopeUnavailable):
                    logger.warning("NL2Agent grant revocation will expire run_id=%s", payload.run_id)
