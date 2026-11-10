# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Admit legacy requests to the Runtime worker pool and execution registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts.constants.environment import RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError,
    AgentRunConcurrencyExceededError,
    RuntimeCapacityExceededError,
    RuntimeQueueTimeoutError,
)
from nexent.core.agents.run_agent import DeferredAgentRun
from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded, ThreadQueueTimedOut

if TYPE_CHECKING:
    from nexent.core.concurrency import ThreadManager
    from nexent.core.concurrency.models import ManagedExecution
    from runtime.executions import AgentRunManager


async def admit_legacy_execution(
    registry: AgentRunManager,
    thread_manager: ThreadManager,
    agent_id: int | None,
    run_identifier: int | str,
    user_id: str,
) -> tuple[DeferredAgentRun, ManagedExecution, str]:
    deferred_run = DeferredAgentRun()
    execution = None
    agent_capacity_token = None
    try:
        agent_capacity_token = registry.reserve_agent_capacity(
            agent_id,
            RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS,
        )
        execution = thread_manager.submit(
            "agent-run",
            ManagedTaskSpec(
                task_name="agent-run",
                owner="runtime",
                run_id=str(run_identifier),
                close_hook=deferred_run.cancel,
                pass_cancel_event=True,
            ),
            deferred_run.run,
        )
        execution.future.add_done_callback(
            lambda _future: registry.release_agent_capacity(
                agent_capacity_token
            )
        )
        await thread_manager.wait_until_started(execution)
    except AgentRunConcurrencyExceededError as exc:
        raise RuntimeCapacityExceededError() from exc
    except ThreadCapacityExceeded as exc:
        if execution is None and agent_capacity_token is not None:
            registry.release_agent_capacity(agent_capacity_token)
        raise RuntimeCapacityExceededError() from exc
    except ThreadQueueTimedOut as exc:
        deferred_run.cancel()
        raise RuntimeQueueTimeoutError(exc.timeout_seconds) from exc
    except BaseException:
        deferred_run.cancel()
        if execution is not None:
            thread_manager.cancel(
                execution.execution_id,
                reason="agent admission failed",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
        elif agent_capacity_token is not None:
            registry.release_agent_capacity(agent_capacity_token)
        raise

    try:
        reservation_token = registry.reserve_agent_run(
            run_identifier,
            user_id,
        )
    except AgentRunAlreadyActiveError:
        deferred_run.cancel()
        thread_manager.cancel(
            execution.execution_id,
            reason="agent run already active",
            wait_timeout=0,
            mark_stuck_on_timeout=False,
        )
        raise
    return deferred_run, execution, reservation_token
