# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound optional memory I/O separately from Agent model work."""

import asyncio
import logging
import time

from contracts.constants.environment import MEMORY_QUERY_TIMEOUT_SECONDS, MEMORY_WRITE_TIMEOUT_SECONDS
from infrastructure.concurrency import runtime_thread_manager
from nexent.core.concurrency import ManagedTaskSpec

logger = logging.getLogger(__name__)


def memory_deadline() -> float:
    return time.monotonic() + MEMORY_QUERY_TIMEOUT_SECONDS


def memory_write_deadline() -> float:
    return time.monotonic() + MEMORY_WRITE_TIMEOUT_SECONDS


def remaining_time(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


async def run_memory_io(name, fn, *args, deadline, lane="memory-read", **kwargs):
    """Limit caller wait, including admission, even when transport cancellation is cooperative."""
    remaining = remaining_time(deadline)
    if remaining <= 0:
        raise TimeoutError

    def checked_call():
        if remaining_time(deadline) <= 0:
            raise TimeoutError
        return fn(*args, **kwargs)

    spec = ManagedTaskSpec(task_name=name, owner="memory")
    async with asyncio.timeout(remaining):
        return await runtime_thread_manager.run(lane, spec, checked_call)


async def optional_memory_io(name, fn, *args, deadline, **kwargs):
    started_at = time.monotonic()
    try:
        return await run_memory_io(name, fn, *args, deadline=deadline, **kwargs)
    except Exception as exc:
        logger.warning(
            "event=memory_operation_degraded operation=%s error_type=%s elapsed_ms=%d",
            name, type(exc).__name__, int((time.monotonic() - started_at) * 1000),
        )
        return None
