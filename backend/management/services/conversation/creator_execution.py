# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared runtime/history orchestration for editor and Workbench creator entrypoints."""

from contracts.constants.environment import APP_VERSION
from contracts.conversation import ConversationTarget
from management.db.conversation.repository import get_conversation_history
from management.services.agent.system import system_agent_provider
from management.services.conversation.creation_history import (
    persist_creation_stream,
    prepare_creation_history,
)
from management.services.conversation.creator_targets import authorize_target
from nexent.monitor import AgentRunMetadata, agent_monitoring_context


class _CreationStream:
    """Bind runtime identity per advance and release both streams on every exit."""

    def __init__(self, stream, metadata, **history):
        self._runtime = stream
        self._persisted = persist_creation_stream(stream, **history)
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
            # Leave this context before returning an event to the response consumer.
            with agent_monitoring_context(self._metadata):
                return await anext(self._persisted)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        with agent_monitoring_context(self._metadata):
            try:
                await self._persisted.aclose()
            finally:
                await self._runtime.aclose()


async def start_creation_turn(request, *, kind, user_id, tenant_id, stream_factory):
    ref = system_agent_provider.get_creator_ref(tenant_id, f"nl2{kind}_main")
    target = request.target.model_dump() if request.target is not None else None
    if kind == "agent" and target is None and request.agent_id is not None:
        # Compatibility for existing editors: their request agent_id names the edited draft.
        target = {"type": "agent", "id": request.agent_id}
    if request.conversation_id is not None:
        history = get_conversation_history(request.conversation_id, user_id)
        if not history or history.get("agent_id") != ref.agent_id:
            raise ValueError("Conversation does not belong to this creator")
        target = target or history.get("target")
    if target is not None:
        if target["type"] != kind:
            raise ValueError("Creator target type does not match executor")
        target = authorize_target(target, user_id, tenant_id)
    if kind == "agent" and target is None:
        raise ValueError("NL2Agent requires an editable Agent target")
    effective = request.model_copy(update={"target": ConversationTarget.model_validate(target) if target else None})
    if kind == "agent":
        effective.agent_id = target["id"]
    if request.conversation_id is not None:
        from management.services.conversation.model_preferences import (
            read_model_preferences,
        )
        from nexent.core.concurrency import run_blocking

        saved = await run_blocking("creator-model-preferences", read_model_preferences,
            request.conversation_id, user_id)
        effective.__dict__["_runtime_model_parameter_preferences"] = saved["model_parameter_preferences"]
        if effective.model_id is None:
            effective.model_id = saved.get("selected_model_id")
    # Validate and build the runtime before inserting the user turn.
    stream = await stream_factory(effective, ref)
    message_receipt = {}
    try:
        conversation_id, index = prepare_creation_history(
            conversation_id=request.conversation_id, mode=f"{kind}_create", query=request.query,
            minio_files=request.minio_files, workbench_config=request.workbench_config,
            agent_id=ref.agent_id, target=target, user_id=user_id, tenant_id=tenant_id,
            **({"selected_model_id": effective.model_id} if effective.model_id is not None else {}),
            **({"model_parameter_preferences": request.model_parameter_preferences} if request.model_parameter_preferences else {}),
            retry_user_message_id=request.retry_user_message_id,
            retry_message_index=request.retry_message_index,
            message_receipt=message_receipt,
        )
    except BaseException:
        await stream.aclose()
        raise

    extra_metadata = {"app_version": APP_VERSION, "core_type": "smolagents"}
    message_id = message_receipt.get("message_id")
    if type(message_id) is int and 0 < message_id <= 2147483647:
        extra_metadata["trajectory_source_message_id"] = str(message_id)
    metadata = AgentRunMetadata(
        tenant_id=tenant_id, user_id=user_id, agent_id=ref.agent_id,
        conversation_id=conversation_id, query=request.query, is_debug=False,
        extra_metadata=extra_metadata,
    )
    return _CreationStream(
        stream, metadata, conversation_id=conversation_id, assistant_index=index,
        user_id=user_id, tenant_id=tenant_id,
    ), conversation_id
