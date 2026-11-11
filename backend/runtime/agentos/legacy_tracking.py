# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own execution registration and replay state for compatibility launches."""

from infrastructure.agent_stream_channels import StreamingChannel, streaming_channel_manager
from infrastructure.rdb.agent_admission import set_conversation_admission
from infrastructure.rdb.agent_execution import RunIdentity, begin_execution, finish_execution, track_execution, untrack_execution
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking


async def begin_legacy_tracking(conversation_id: int, run_id: str, user_id: str, tenant_id: str) -> RunIdentity:
    identity = RunIdentity(tenant_id, user_id, conversation_id, run_id)
    await run_blocking(
        "agentos-execution-start", begin_execution, identity, lane="control-io", owner="runtime",
    )
    track_execution(identity)
    return identity


async def reset_legacy_stream(conversation_id: int | None, user_id: str) -> None:
    await runtime_state_service.reset_stream_async(conversation_id=conversation_id, user_id=user_id)


async def open_legacy_channel(conversation_id: int, user_id: str) -> StreamingChannel:
    return await streaming_channel_manager.get_or_create_channel(conversation_id=conversation_id, user_id=user_id)


async def bind_legacy_channel(
    channel: StreamingChannel, run_id: str, user_id: str, tenant_id: str, *,
    conversation_id: int, identity: RunIdentity | None, admission_scope: str | None,
) -> str | None:
    if identity is not None:
        channel.execution_identity = identity
    journal_id = await channel.start_journal(tenant_id, run_id) if runtime_state_service.enabled is True else None
    if admission_scope is not None:
        recorded = await run_blocking(
            "agentos-bind-conversation", set_conversation_admission, admission_scope, run_id, user_id, tenant_id,
            conversation_id=conversation_id, journal_available=journal_id is not None, lane="control-io", owner="runtime",
        )
        if not recorded:
            raise RuntimeError("Conversation run claim is no longer pending")
    return journal_id


async def abort_legacy_channel(channel: StreamingChannel, conversation_id: int, user_id: str) -> None:
    await channel.finish_journal("failed")
    await streaming_channel_manager.remove_channel(conversation_id, user_id, expected_channel=channel)


async def fail_legacy_setup(identity: RunIdentity) -> None:
    try:
        await run_blocking(
            "agentos-execution-setup-failed", finish_execution, identity, "failed",
            lane="control-io", owner="runtime",
        )
    finally:
        untrack_execution(identity)
