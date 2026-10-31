# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared runtime/history orchestration for editor and Workbench creator entrypoints."""

from contracts.conversation import ConversationTarget
from management.db.conversation.repository import get_conversation_history
from management.services.agent.system import system_agent_provider
from management.services.conversation.creation_history import prepare_creation_history, persist_creation_stream
from management.services.conversation.creator_targets import authorize_target


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
    # Validate and build the runtime before inserting the user turn.
    stream = await stream_factory(effective, ref)
    try:
        conversation_id, index = prepare_creation_history(
            conversation_id=request.conversation_id, mode=f"{kind}_create", query=request.query,
            minio_files=request.minio_files, workbench_config=request.workbench_config,
            agent_id=ref.agent_id, target=target, user_id=user_id, tenant_id=tenant_id,
            retry_user_message_id=request.retry_user_message_id,
            retry_message_index=request.retry_message_index,
        )
    except BaseException:
        await stream.aclose()
        raise

    async def persisted():
        try:
            async for event in persist_creation_stream(
                stream, conversation_id=conversation_id, assistant_index=index,
                user_id=user_id, tenant_id=tenant_id,
            ):
                yield event
        finally:
            await stream.aclose()

    return persisted(), conversation_id
