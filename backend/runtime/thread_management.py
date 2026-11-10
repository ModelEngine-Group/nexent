# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import logging

from nexent.core.concurrency import LanePolicy, ThreadManager

from contracts.constants.environment import (
    RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
    RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
    RUNTIME_AGENT_THREAD_MAX_WORKERS,
    RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS,
    RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
    RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
)


runtime_thread_manager = ThreadManager(
    service_name="runtime",
    lane_policies={
        "agent-run": LanePolicy(
            name="agent-run",
            max_workers=RUNTIME_AGENT_THREAD_MAX_WORKERS,
            max_queue_size=RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "control-io": LanePolicy(
            name="control-io",
            max_workers=16,
            max_queue_size=32,
            queue_timeout_seconds=0,
            cancel_grace_seconds=2,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "model-tool-io": LanePolicy(
            name="model-tool-io",
            max_workers=max(4, RUNTIME_AGENT_THREAD_MAX_WORKERS),
            max_queue_size=RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "model-embedding": LanePolicy(
            name="model-embedding",
            max_workers=max(4, RUNTIME_AGENT_THREAD_MAX_WORKERS),
            max_queue_size=RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "mcp-session": LanePolicy(
            name="mcp-session",
            max_workers=RUNTIME_AGENT_THREAD_MAX_WORKERS,
            max_queue_size=0,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "sandbox": LanePolicy(
            name="sandbox",
            max_workers=200,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "background-service": LanePolicy(
            name="background-service",
            max_workers=12,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "evaluation": LanePolicy(
            name="evaluation",
            max_workers=6,
            max_queue_size=12,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
    },
)


logger = logging.getLogger(__name__)
channel_cleanup_tasks: set[asyncio.Task[None]] = set()
agent_stream_producer_tasks: set[asyncio.Task[None]] = set()
external_memory_ingest_tasks: set[asyncio.Task[None]] = set()
fa_extraction_tasks: set[asyncio.Task[None]] = set()


async def shutdown_agent_stream_tasks(timeout: float) -> tuple[str, ...]:
    """Cancel request-owned async tasks before the Runtime thread manager drains."""
    task_groups = (
        agent_stream_producer_tasks,
        external_memory_ingest_tasks,
        fa_extraction_tasks,
        channel_cleanup_tasks,
    )
    tasks = tuple(
        task
        for task_group in task_groups
        for task in tuple(task_group)
        if not task.done()
    )
    if not tasks:
        return ()

    for task in tasks:
        task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=max(0, timeout))
    logger.info(
        "Agent stream task shutdown requested=%s completed=%s pending=%s",
        len(tasks),
        len(done),
        len(pending),
    )
    return tuple(task.get_name() for task in pending)


def unregister_after_worker_exit(
    registry,
    conversation_id: int | str,
    user_id: str,
    status: str,
    agent_run_info=None,
) -> bool:
    """Keep the conversation reserved until its worker Future really finishes."""
    future = getattr(agent_run_info, "thread_future", None)
    if future is not None and not future.done():
        future.add_done_callback(
            lambda _future: registry.unregister_agent_run(
                conversation_id,
                user_id,
                status=status,
                agent_run_info=agent_run_info,
            )
        )
        logger.info(
            "Deferred agent run unregister until worker exit conversation=%s "
            "execution_id=%s",
            conversation_id,
            getattr(agent_run_info, "thread_execution_id", ""),
        )
        return False
    return registry.unregister_agent_run(
        conversation_id,
        user_id,
        status=status,
        agent_run_info=agent_run_info,
    )
