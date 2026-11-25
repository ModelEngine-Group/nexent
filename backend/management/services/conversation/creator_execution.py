# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared runtime/history orchestration for editor and Workbench creator entrypoints."""

import asyncio
import json
from contextlib import suppress

from contracts.constants.environment import APP_VERSION, RUNTIME_RUN_TTL_SECONDS
from contracts.conversation import ConversationTarget, HistoryItem, MessageRequest
from infrastructure.redis.run_state import runtime_state_service
from management.db.conversation.repository import get_conversation_history
from contracts.errors.exceptions import AgentRunAlreadyActiveError
from management.services.agent.system import system_agent_provider
from management.services.conversation.creation_history import (
    prepare_creation_history,
)
from management.services.conversation.creator_checkpoints import (
    checkpoint_creator_stream,
)
from management.services.conversation.creator_runtime import (
    CreatorControl,
    agent_run_manager,
    claim_creator,
    claim_request,
    launch_creator,
    release_request,
    resume_creator,
)
from management.services.conversation.creator_targets import authorize_target
from management.services.conversation.nexent_output import adapt_nexent_stream
from management.services.conversation.service import save_message, update_message_status
from nexent.core.concurrency import run_blocking
from nexent.monitor import AgentRunMetadata, agent_monitoring_context


class _CreationStream:
    """Bind saved identity around runtime advances without coupling HTTP lifetime."""

    def __init__(self, stream, metadata):
        self._runtime = stream
        self._metadata = metadata
        self._closed = False

    async def __aiter__(self):
        try:
            while True:
                try:
                    event = await self.__anext__()
                except StopAsyncIteration:
                    return
                yield event
        finally:
            await self.aclose()

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        try:
            with agent_monitoring_context(self._metadata):
                return await anext(self._runtime)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        with agent_monitoring_context(self._metadata):
            await self._runtime.aclose()


def creator_history_context(history, retry_index=None):
    """Keep the selected answer branch and its structured questions model-visible."""
    selected = {}
    for message in history.get("message_records", []):
        index = message.get("message_index", 0)
        if retry_index is None or index < retry_index:
            selected[index] = message
    result = []
    for _, message in sorted(selected.items()):
        content = message.get("message_content") or ""
        if message.get("role") == "assistant":
            card = next(
                (
                    unit
                    for unit in message.get("units", [])
                    if unit.get("unit_type") == "nl2a"
                ),
                None,
            )
            if card:
                content = card["unit_content"]
        result.append(HistoryItem(role=message["role"], content=content))
    return result


def validate_creator_card_action(history, query):
    try:
        action = json.loads(query)
    except (TypeError, json.JSONDecodeError):
        return
    if (
        not isinstance(action, dict)
        or action.get("type") != "nl2agent_card_action"
        or not action.get("card_id")
    ):
        return
    messages = history.get("message_records", [])
    latest = max(
        (m for m in messages if m.get("role") == "assistant"),
        key=lambda m: m["message_id"],
        default=None,
    )
    if latest is None:
        raise ValueError("Card action has no originating answer")
    cards = [
        json.loads(unit["unit_content"])
        for unit in latest.get("units", [])
        if unit.get("unit_type") == "nl2a"
    ]
    if not any(
        card.get("card_id") == action["card_id"]
        and card.get("agent_id") == action.get("agent_id")
        and card.get("subtype") == action.get("subtype")
        for card in cards
    ):
        raise ValueError(
            "Card action is stale or does not belong to the current answer"
        )


async def start_creation_turn(
    request, *, kind, user_id, tenant_id, stream_factory, resume=False
):
    ref = system_agent_provider.get_creator_ref(tenant_id, f"nl2{kind}_main")
    target = request.target.model_dump() if request.target is not None else None
    history = None
    if kind == "agent" and target is None and request.agent_id is not None:
        # Compatibility for existing editors: their request agent_id names the edited draft.
        target = {"type": "agent", "id": request.agent_id}
    history = None
    if request.conversation_id is not None:
        history = get_conversation_history(request.conversation_id, user_id)
        if not history or history.get("agent_id") != ref.agent_id:
            raise ValueError("Conversation does not belong to this creator")
        if resume and target is not None and target != history.get("target"):
            raise ValueError("Resume target does not match creator history")
        target = target or history.get("target")
    if target is not None:
        if target["type"] != kind:
            raise ValueError("Creator target type does not match executor")
        target = authorize_target(target, user_id, tenant_id)
    if kind == "agent" and target is None:
        raise ValueError("NL2Agent requires an editable Agent target")
    if resume:
        if request.conversation_id is None:
            raise ValueError("Resume requires a creator conversation")
        state = await runtime_state_service.get_run_state_async(
            user_id, request.conversation_id
        )
        local = agent_run_manager.get_agent_run_info(request.conversation_id, user_id)
        generation = (
            local.__dict__.get("_automation_runtime_generation")
            if local is not None
            else None
        ) or state.get("generation")
        if generation:
            request.__dict__["_creator_generation"] = generation
        subscriber = await resume_creator(request.conversation_id, user_id)
        return adapt_nexent_stream(subscriber), request.conversation_id
    effective = request.model_copy(
        update={"target": ConversationTarget.model_validate(target) if target else None}
    )
    if history and not (
        request.retry_user_message_id or request.retry_message_index is not None
    ):
        validate_creator_card_action(history, request.query)
    if history and "message_records" in history:
        retry_index = request.retry_message_index
        if request.retry_user_message_id:
            retry_index = next(
                (
                    m["message_index"]
                    for m in history["message_records"]
                    if m["message_id"] == request.retry_user_message_id
                ),
                retry_index,
            )
        effective.history = creator_history_context(history, retry_index)
    if kind == "agent":
        effective.agent_id = target["id"]
    if request.conversation_id is not None:
        from management.services.conversation.model_preferences import (
            read_model_preferences,
        )

        saved = await run_blocking(
            "creator-model-preferences",
            read_model_preferences,
            request.conversation_id,
            user_id,
        )
        effective.__dict__["_runtime_model_parameter_preferences"] = saved[
            "model_parameter_preferences"
        ]
        if effective.model_id is None:
            effective.model_id = saved.get("selected_model_id")
    control = CreatorControl()
    request.__dict__["_creator_generation"] = control.generation
    effective.__dict__["_creator_control"] = control
    reservation = None
    conversation_id = request.conversation_id
    stream = None
    message_id = None
    request_key = (
        f"creator-request:{tenant_id}:{user_id}:{request.request_id}"
        if request.request_id
        else None
    )
    request_claimed = False
    preparation_guard = None
    message_receipt = {}
    history_args = dict(
        conversation_id=request.conversation_id, mode=f"{kind}_create", query=request.query,
        minio_files=request.minio_files, workbench_config=request.workbench_config,
        agent_id=ref.agent_id, target=target, user_id=user_id, tenant_id=tenant_id,
        selected_model_id=effective.model_id, model_parameter_preferences=request.model_parameter_preferences,
        retry_user_message_id=request.retry_user_message_id, retry_message_index=request.retry_message_index,
        message_receipt=message_receipt,
    )
    try:
        if conversation_id is not None:
            reservation = await claim_creator(
                conversation_id, user_id, control.generation
            )
            preparation_guard = control.guard_preparation(conversation_id, user_id)
            for previous in (history or {}).get("message_records", []):
                if previous.get("status") == "streaming":
                    await run_blocking(
                        "creator-prior-interrupted",
                        update_message_status,
                        previous["message_id"],
                        "failed",
                        user_id,
                    )
        if request_key:
            request_claimed = await claim_request(request_key, RUNTIME_RUN_TTL_SECONDS)
            if not request_claimed:
                raise AgentRunAlreadyActiveError("Creator request was already accepted")
        retry_position = None
        if request.retry_user_message_id is not None or request.retry_message_index is not None:
            # This path only validates an existing turn. Do it before the runtime can advance a card.
            retry_position = await run_blocking(
                "creator-validate-retry", prepare_creation_history, **history_args,
            )
            if kind == "agent" and history and history.get("message_records"):
                last = history["message_records"][-1]
                effective.__dict__["_resume_confirmed_requirements"] = (
                    last.get("role") == "assistant"
                    and last.get("message_index") == retry_position[1]
                    and last.get("status") in {"failed", "stopped"}
                )
        # Validate/build before history writes and admit the managed worker first.
        stream = await stream_factory(effective, ref)
        await control.admit()
        conversation_id, index = retry_position or await run_blocking(
            "creator-prepare-history", prepare_creation_history, **history_args,
        )
        if kind == "agent":
            effective.conversation_id = conversation_id
        if reservation is None:
            reservation = await claim_creator(
                conversation_id, user_id, control.generation
            )
            preparation_guard = control.guard_preparation(conversation_id, user_id)
        message_id = await run_blocking(
            "creator-start-message",
            save_message,
            MessageRequest(
                conversation_id=conversation_id,
                message_idx=index,
                role="assistant",
                message=[],
            ),
            user_id=user_id,
            tenant_id=tenant_id,
            status="streaming",
            streaming_owner="management",
        )
        extra_metadata = {"app_version": APP_VERSION, "core_type": "smolagents", "creator_mode": f"nl2{kind}"}
        source_id = message_receipt.get("message_id")
        if type(source_id) is int and 0 < source_id <= 2147483647:
            extra_metadata["trajectory_source_message_id"] = str(source_id)
        stream = _CreationStream(stream, AgentRunMetadata(
            tenant_id=tenant_id, user_id=user_id, agent_id=ref.agent_id,
            conversation_id=conversation_id, query=request.query, is_debug=False,
            extra_metadata=extra_metadata,
        ))
        persisted = checkpoint_creator_stream(
            stream,
            message_id=message_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        subscriber = await launch_creator(
            persisted,
            control=control,
            conversation_id=conversation_id,
            user_id=user_id,
            reservation=reservation,
        )
        return adapt_nexent_stream(subscriber), conversation_id
    except BaseException:
        control.cancel()
        if stream is not None:
            await stream.aclose()
        if reservation is not None:
            agent_run_manager.release_agent_run_reservation(
                conversation_id, user_id, reservation
            )
            await runtime_state_service._run_managed(
                "creator-failed-preparation",
                runtime_state_service.mark_run_finished,
                user_id,
                conversation_id,
                "failed",
                control.generation,
            )
        if message_id is not None:
            await run_blocking(
                "creator-failed-message",
                update_message_status,
                message_id,
                "failed",
                user_id,
            )
        if request_claimed and message_id is None:
            await release_request(request_key)
        raise
    finally:
        if preparation_guard is not None:
            preparation_guard.cancel()
            with suppress(asyncio.CancelledError):
                await preparation_guard
