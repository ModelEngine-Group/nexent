# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Finish stream projections left behind by the previous Runtime process."""

import asyncio
import logging
from time import monotonic

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.rdb.agent_execution import (
    mark_journal_repaired, pending_journal_repairs, recover_expired_executions, renew_execution_leases,
)
from infrastructure.redis.agent_events import RunJournal
from nexent.core.concurrency import ManagedTaskSpec

from infrastructure.rdb.conversation_state import fail_streaming_assistant_messages
from infrastructure.redis.run_state import runtime_state_service

logger = logging.getLogger(__name__)


def recover_streaming_runs() -> int:
    messages = fail_streaming_assistant_messages()
    for message in messages:
        if user_id := message["user_id"]:
            conversation_id = int(message["conversation_id"])
            runtime_state_service.mark_run_finished(user_id, conversation_id, "failed")
            runtime_state_service.mark_stream_completed(user_id, conversation_id, "failed")
    logger.info("Recovered %d interrupted assistant streams", len(messages))
    return len(messages)


def reconcile_executions() -> None:
    renew_execution_leases()
    recover_expired_executions()
    repair_deadline = monotonic() + 10
    for identity, status in pending_journal_repairs():
        if monotonic() >= repair_deadline:
            break
        if runtime_state_service.enabled:
            try:
                RunJournal(identity.tenant_id, identity.user_id, identity.conversation_id, identity.run_id).repair_terminal(status)
            except RedisError:
                logger.warning("AgentOS journal repair will retry")
                return
        mark_journal_repaired(identity)


async def watch_executions(manager) -> None:
    while True:
        try:
            await manager.run(
                "control-io", ManagedTaskSpec(task_name="agentos-reconcile-executions", owner="runtime"),
                reconcile_executions,
            )
        except (SQLAlchemyError, RuntimeError):
            logger.exception("AgentOS execution reconciliation failed; retrying")
        await asyncio.sleep(5)
