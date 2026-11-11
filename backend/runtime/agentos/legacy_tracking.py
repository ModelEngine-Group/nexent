# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own durable execution registration for compatibility launches."""

from infrastructure.rdb.agent_admission import set_conversation_admission
from infrastructure.rdb.agent_execution import RunIdentity, begin_execution, finish_execution, track_execution, untrack_execution
from nexent.core.concurrency import run_blocking


async def begin_legacy_tracking(conversation_id: int, run_id: str, user_id: str, tenant_id: str) -> RunIdentity:
    identity = RunIdentity(tenant_id, user_id, conversation_id, run_id)
    await run_blocking(
        "agentos-execution-start", begin_execution, identity, lane="control-io", owner="runtime",
    )
    track_execution(identity)
    return identity


async def bind_legacy_admission(scope, run_id, user_id, tenant_id, *, conversation_id, journal_available):
    recorded = await run_blocking(
        "agentos-bind-conversation", set_conversation_admission, scope, run_id, user_id, tenant_id,
        conversation_id=conversation_id, journal_available=journal_available, lane="control-io", owner="runtime",
    )
    if not recorded:
        raise RuntimeError("Conversation run claim is no longer pending")


async def fail_legacy_setup(identity: RunIdentity) -> None:
    try:
        await run_blocking(
            "agentos-execution-setup-failed", finish_execution, identity, "failed",
            lane="control-io", owner="runtime",
        )
    finally:
        untrack_execution(identity)
