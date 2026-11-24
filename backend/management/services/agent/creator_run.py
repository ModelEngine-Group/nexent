# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize and dispatch NL2Agent creation through AgentOS."""

import asyncio
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


async def _creator_frames(response, payload, actor):
    """Forward retrieval progress while Runtime waits for a resource callback."""
    if payload.conversation_id is None:
        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                yield frame
        return
    from services.nl2agent_retrieval_progress import clear_progress, read_progress
    from services.nl2agent_state_service import ResourceScope

    scope = ResourceScope(actor.tenant_id, actor.user_id, payload.agent_id,
                          str(payload.conversation_id), payload.run_id)
    pending = None
    sequence = 0
    async with aclosing(iter_sse_frames(response)) as frames:
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(frames))
                done, _ = await asyncio.wait({pending}, timeout=0.3)
                events = await run_blocking(
                    "nl2agent-read-retrieval-progress", read_progress, scope, sequence,
                    lane="control-io", owner="management",
                )
                for event in events:
                    sequence = event["sequence"]
                    yield ("data: " + json.dumps({"type": "nl2a_state", "content": json.dumps(event)})).encode()
                if not done:
                    continue
                try:
                    frame = pending.result()
                except StopAsyncIteration:
                    return
                pending = None
                yield frame
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            with CancelScope(shield=True):
                await run_blocking("nl2agent-clear-retrieval-progress", clear_progress, scope,
                                   lane="control-io", owner="management")


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


async def _apply_card_action(payload, actor, request, *, validate_only=False):
    """Apply the authorized user action before dispatching the next creator run."""
    from contracts.nl2agent_resources import ResourceCardAction
    from management.services.agent.authorization import require_agent_draft_edit
    from services.nl2agent_state_service import ResourceScope, ResourceStateError

    if _parse_nl2agent_card_action_agent_id(request.query) is None:
        return payload, []
    action = json.loads(request.query)
    data = action.get("result")
    scope = ResourceScope(actor.tenant_id, actor.user_id, payload.agent_id,
                          str(payload.conversation_id or ""), payload.run_id)
    require_agent_draft_edit(agent_id=payload.agent_id, tenant_id=actor.tenant_id, user_id=actor.user_id)
    frames = []
    resume = getattr(request, "_resume_confirmed_requirements", False)
    if action.get("subtype") == "prompt_generation":
        from services.nl2agent_prompt_service import apply_action
        if not scope.conversation_id:
            raise ResourceStateError("prompt_card_stale")
        result = await apply_action(scope, action.get("action"), data, resume_confirmation=resume)
        if result["saved"]:
            frames.append({"type": "nl2a_state", "content": json.dumps({
                "event": "agent_draft_fields_saved", "agent_id": payload.agent_id, "updated_fields": ["prompt"],
            })})
        frames.append({"type": "nl2a", "content": json.dumps(result["card"], ensure_ascii=False)})
        if not result["resume"]:
            return None, frames
        query = ("The runtime has applied the exact prompt approved by the user. Do not regenerate or save prompt. "
                 "Continue the original full-generation task: save greeting_message and example_questions, "
                 "then call nl2a_validate_agent_generation_complete and report its actual result.")
    elif action.get("subtype") in {"installed_resource_binding", "local_mcp_recommendation", "suggested_resource_installation"}:
        raise ResourceStateError("resource_card_stale")
    elif isinstance(data, dict) and ("card_id" in data or "state_version" in data):
        from services.nl2agent_resource_flow import apply_card_action
        if not scope.conversation_id:
            raise ResourceStateError("resource_state_expired")
        try:
            parsed = ResourceCardAction.model_validate(data)
        except ValueError as exc:
            raise ResourceStateError("invalid_resource_action") from exc
        result = await apply_card_action(scope, action.get("subtype"), action.get("action"), parsed,
                                         resume_confirmation=resume, validate_only=validate_only)
        if validate_only:
            return payload, []
        if result.get("card") is not None:
            frames.append({"type": "nl2a", "content": json.dumps(result["card"], ensure_ascii=False)})
            return None, frames
        payload = payload.model_copy(update={"resource_pending": (
            result.get("next_step") == "verify_resources" and result.get("purpose") == "generate"
        )})
        query = "Continue from the resource action accepted by the runtime. Accepted resource action: " + json.dumps(result)
    else:
        return payload, frames
    context = await _build_verified_bound_resources_context(
        agent_id=payload.agent_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
    )
    return payload.model_copy(update={
        "input": payload.input.model_copy(update={"query": query}), "bound_resources": context.content["text"],
    }), frames


async def create_nl2agent_stream(payload: PreparedAgentCreatorRun, actor: ServicePrincipal, *, request=None) -> AsyncIterator[str]:
    granted = False
    try:
        if request is not None:
            payload, frames = await _apply_card_action(payload, actor, request)
            for frame in frames:
                yield "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n"
            if payload is None:
                return
        with CancelScope(shield=True):
            await run_blocking(
                "nl2agent-open-tool-grant", open_nl2agent_tool_grant, payload.run_id, payload.agent_id, actor,
                _requires_policy_clarification(payload.input.query), str(payload.conversation_id or ""),
                payload.resource_pending, lane="control-io", owner="management",
            )
            granted = True
        response = await forward_creator_run(payload, actor.user_id, actor.tenant_id)
        async with aclosing(_creator_frames(response, payload, actor)) as frames:
            if response.status_code != 200:
                await anext(frames, None)
                raise RuntimeError("NL2Agent execution was rejected by Runtime")
            boundary_delivered = False
            async for frame in frames:
                if frame == b"event: agentos_execution_complete\ndata: {}":
                    return
                if frame.startswith(b"event: agentos_execution_error\ndata: "):
                    if not boundary_delivered:
                        yield frame.split(b"\n", 1)[1].decode() + "\n\n"
                    return
                if frame.startswith(b"data: ") and not boundary_delivered:
                    yield frame.decode() + "\n\n"
                    boundary_delivered = json.loads(frame[6:]).get("type") == "nl2a"
            if not boundary_delivered:
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
