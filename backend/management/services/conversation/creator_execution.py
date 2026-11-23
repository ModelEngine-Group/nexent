# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared runtime/history orchestration for editor and Workbench creator entrypoints."""

import asyncio
import json
import logging
from contextlib import suppress

from contracts.constants.environment import APP_VERSION, RUNTIME_RUN_TTL_SECONDS
from contracts.conversation import ConversationTarget, HistoryItem, MessageRequest
from contracts.errors.exceptions import ForbiddenError, RuntimeCoordinationUnavailableError
from infrastructure.redis.run_state import creator_runtime_state_service as runtime_state_service
from management.db.conversation.repository import get_conversation_history
from management.services.agent.admission import reserve_agent_scope, uses_durable_agent_admission
from management.services.agent.control import get_owned_execution, read_owned_stream
from management.services.agent.lifecycle import (
    AgentRunAlreadyActiveError,
    agent_run_manager,
)
from management.services.agent.system import system_agent_provider
from management.services.conversation.creation_history import (
    create_creation_conversation,
    prepare_creation_history,
)
from management.services.conversation.creator_checkpoints import (
    checkpoint_creator_stream,
)
from management.services.conversation.creator_runtime import (
    CreatorControl,
    claim_creator,
    claim_request,
    launch_creator,
    release_request,
    required_creator_redis,
    resume_creator,
    resume_owned_creator,
    wait_creator_step,
)
from management.services.conversation.creator_targets import authorize_target
from management.services.conversation.nexent_output import adapt_nexent_stream
from management.services.conversation.service import get_conversation_service, save_message, update_message_status
from nexent.core.concurrency import run_blocking
from nexent.core.concurrency.errors import ThreadManagerDraining, ThreadManagerNotRunning
from nexent.monitor import AgentRunMetadata, agent_monitoring_context

logger = logging.getLogger(__name__)


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


def _creator_target(request, history, *, kind, user_id, tenant_id, resume=False):
    target = request.target.model_dump() if request.target is not None else None
    if kind == "agent" and target is None and request.agent_id is not None:
        # Compatibility for existing editors: their request agent_id names the edited draft.
        target = {"type": "agent", "id": request.agent_id}
    if history is not None:
        if resume and target is not None and target != history.get("target"):
            raise ValueError("Resume target does not match creator history")
        target = target or history.get("target")
    if target is not None:
        if target["type"] != kind:
            raise ValueError("Creator target type does not match executor")
        target = authorize_target(target, user_id, tenant_id)
    if kind == "agent" and target is None:
        raise ValueError("NL2Agent requires an editable Agent target")
    return target


def _read_creator_history(conversation_id, user_id, agent_id):
    history = get_conversation_history(conversation_id, user_id)
    if not history or history.get("agent_id") != agent_id:
        raise ValueError("Conversation does not belong to this creator")
    return history


async def _prepare_creator_request(request, history, target, *, kind, user_id):
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
    return effective


async def start_creation_turn(
    request, *, kind, user_id, tenant_id, stream_factory, resume=False
):
    scope = f"nl2{kind}_main"
    ref = system_agent_provider.get_creator_ref(tenant_id, scope)
    conversation_id = request.conversation_id
    expected_message_id = request.resume_message_id
    resume = resume or expected_message_id is not None
    coordinated = uses_durable_agent_admission()
    if resume and coordinated and conversation_id is not None and not await run_blocking(
        "creator-resume-owner", get_conversation_service, conversation_id, user_id, tenant_id,
    ):
        raise ForbiddenError("Conversation is not accessible to the current identity")
    history = (
        _read_creator_history(conversation_id, user_id, ref.agent_id)
        if conversation_id is not None else None
    )
    target = _creator_target(request, history, kind=kind, user_id=user_id, tenant_id=tenant_id, resume=resume)
    if resume:
        async def unavailable_replay():
            yield 'event: stream_status\ndata: {"status":"stopped","replay_unavailable":true}\n\n'

        if conversation_id is None:
            raise ValueError("Resume requires a creator conversation")
        if coordinated:
            owned = await get_owned_execution(tenant_id, user_id, conversation_id)
            snapshot = None
            execution_id = None
            if owned is not None:
                execution_id, status, run_scope = owned
                if run_scope != scope:
                    raise ValueError("Conversation execution belongs to another runtime entrypoint")
                snapshot = await read_owned_stream(user_id, conversation_id, execution_id)
                if snapshot is None and status in {"PREPARING", "RUNNING", "FINALIZING"}:
                    if expected_message_id is not None:
                        return unavailable_replay(), conversation_id
                    raise RuntimeCoordinationUnavailableError("Creator replay is not ready")
            if snapshot is not None:
                request.__dict__["_creator_generation"] = snapshot["generation"]
                message_id = snapshot["message_id"]
            else:
                history = await run_blocking(
                    "creator-read-saved-replay", _read_creator_history, conversation_id, user_id, ref.agent_id,
                )
                latest = max(
                    (item for item in history.get("message_records", []) if item.get("role") == "assistant"),
                    key=lambda item: item["message_id"], default=None,
                )
                message_id = latest["message_id"] if latest else None
                if await get_owned_execution(tenant_id, user_id, conversation_id) != owned:
                    raise RuntimeCoordinationUnavailableError("Creator replay changed during lookup")
            if expected_message_id is not None and message_id != expected_message_id:
                return unavailable_replay(), conversation_id
            subscriber = resume_owned_creator(conversation_id, user_id, tenant_id, execution_id, snapshot, message_id)
            return adapt_nexent_stream(subscriber), conversation_id
        if expected_message_id is not None:
            latest_message_id = max(
                (item["message_id"] for item in (history or {}).get("message_records", [])
                 if item.get("role") == "assistant"), default=None,
            )
            if expected_message_id != latest_message_id:
                return unavailable_replay(), conversation_id
        state = await runtime_state_service.get_run_state_async(user_id, conversation_id)
        local = agent_run_manager.get_agent_run_info(conversation_id, user_id)
        generation = (
            local.__dict__.get("_automation_runtime_generation")
            if local is not None
            else None
        ) or state.get("generation")
        if generation:
            request.__dict__["_creator_generation"] = generation
        subscriber = await resume_creator(conversation_id, user_id)
        return adapt_nexent_stream(subscriber), conversation_id

    control = CreatorControl()
    reservation = None
    durable = None
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

    async def step(operation):
        return await wait_creator_step(operation) if coordinated else await operation

    async def claim_request_id():
        nonlocal request_claimed
        if not request_key:
            return
        args = (request_key, RUNTIME_RUN_TTL_SECONDS)
        request_claimed = (
            await required_creator_redis(claim_request, *args) if coordinated else await claim_request(*args)
        )
        if not request_claimed:
            raise AgentRunAlreadyActiveError("Creator request was already accepted")

    async def claim_stream():
        nonlocal reservation
        options = {"execution_id": durable.execution_id} if durable is not None else {}
        reservation = await claim_creator(conversation_id, user_id, control.generation, **options)

    async def prepare_history():
        nonlocal conversation_id
        conversation_id, index = await run_blocking(
            "creator-prepare-history", prepare_creation_history,
            conversation_id=conversation_id, minio_files=request.minio_files, tenant_id=tenant_id,
            message_receipt=message_receipt, **history_options,
        )
        return index

    async def save_assistant(index):
        nonlocal message_id
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
        )

    try:
        if coordinated:
            await control.admit(early=True)
            if conversation_id is not None:
                durable = await reserve_agent_scope(scope, conversation_id, user_id, tenant_id, control.execution.future)
                control.bind_reservation(durable)
                history = await run_blocking(
                    "creator-admitted-history", _read_creator_history, conversation_id, user_id, ref.agent_id,
                )
                target = _creator_target(request, history, kind=kind, user_id=user_id, tenant_id=tenant_id)
        effective = await _prepare_creator_request(request, history, target, kind=kind, user_id=user_id)
        history_options = dict(
            mode=f"{kind}_create", query=request.query, workbench_config=request.workbench_config,
            agent_id=ref.agent_id, target=target, user_id=user_id,
            **({"selected_model_id": effective.model_id} if effective.model_id is not None else {}),
            **({"model_parameter_preferences": request.model_parameter_preferences}
               if request.model_parameter_preferences else {}),
            retry_user_message_id=request.retry_user_message_id, retry_message_index=request.retry_message_index,
        )
        if coordinated:
            await step(claim_request_id())
            if conversation_id is None:
                conversation_id = await step(run_blocking(
                    "creator-allocate-conversation", create_creation_conversation, **history_options,
                ))
                durable = await reserve_agent_scope(scope, conversation_id, user_id, tenant_id, control.execution.future)
                control.bind_reservation(durable)
        request.__dict__["_creator_generation"] = control.generation
        effective.__dict__["_creator_control"] = control
        if conversation_id is not None:
            await step(claim_stream())
            if coordinated and await control.is_cancelled(conversation_id, user_id):
                raise asyncio.CancelledError()
            preparation_guard = control.guard_preparation(conversation_id, user_id)
            for previous in (history or {}).get("message_records", []):
                if previous.get("status") == "streaming":
                    await step(run_blocking(
                        "creator-prior-interrupted", update_message_status, previous["message_id"], "failed", user_id,
                    ))
        if not coordinated:
            await claim_request_id()
        stream = await stream_factory(effective, ref)
        if not coordinated:
            await control.admit()
        index = await step(prepare_history())
        if reservation is None:
            await claim_stream()
            preparation_guard = control.guard_preparation(conversation_id, user_id)
        await step(save_assistant(index))
        if durable is not None and not await step(required_creator_redis(
            runtime_state_service.bind_execution_message_async, user_id, conversation_id, durable.execution_id, message_id,
        )):
            raise RuntimeCoordinationUnavailableError("Creator no longer owns its replay")
        extra_metadata = {"app_version": APP_VERSION, "core_type": "smolagents"}
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
        if durable is not None:
            if await control.is_cancelled(conversation_id, user_id):
                raise asyncio.CancelledError()
            await step(durable.running())
        subscriber = await launch_creator(
            persisted,
            control=control,
            conversation_id=conversation_id,
            user_id=user_id,
            reservation=reservation,
        )
        return adapt_nexent_stream(subscriber), conversation_id
    except BaseException as exc:
        if coordinated and preparation_guard is not None:
            preparation_guard.cancel()
        if not getattr(control, "producer_started", False):
            async def cleanup():
                control.cancel()
                try:
                    if stream is not None:
                        await stream.aclose()
                finally:
                    if reservation is not None:
                        agent_run_manager.release_agent_run_reservation(conversation_id, user_id, reservation)
                        await runtime_state_service._run_managed(
                            "creator-failed-preparation", runtime_state_service.mark_run_finished,
                            user_id, conversation_id, "failed", control.generation,
                        )
                    if message_id is not None:
                        await run_blocking("creator-failed-message", update_message_status, message_id, "failed", user_id)
                    if request_claimed and message_id is None:
                        await release_request(request_key)

            try:
                await step(cleanup())
            except Exception:
                if not coordinated:
                    raise
                logger.exception("Creator failed to clean up preparation run_id=%s", control.generation)
            finally:
                if durable is not None:
                    durable.outcome = "stopped" if isinstance(exc, asyncio.CancelledError) else "failed"
                    durable.close()
        if coordinated and isinstance(exc, (ThreadManagerDraining, ThreadManagerNotRunning)):
            raise RuntimeCoordinationUnavailableError("Creator execution worker is unavailable") from exc
        raise
    finally:
        if preparation_guard is not None:
            preparation_guard.cancel()
            with suppress(asyncio.CancelledError):
                await preparation_guard
