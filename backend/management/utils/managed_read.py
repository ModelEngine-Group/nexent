# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Schedule synchronous read handlers on the application's managed I/O lane."""

from functools import wraps

from contracts.errors.exceptions import ManagementReadBusyError
from nexent.core.concurrency import ThreadCapacityExceeded, ThreadQueueTimedOut, run_blocking


async def run_management_read(task_name, handler, *args, **kwargs):
    """Keep admission failures distinct from business and database errors."""
    try:
        return await run_blocking(
            task_name, handler, *args, lane="control-io", owner="management", **kwargs
        )
    except ThreadCapacityExceeded as exc:
        raise ManagementReadBusyError() from exc
    except ThreadQueueTimedOut as exc:
        raise ManagementReadBusyError(queue_timeout_seconds=exc.timeout_seconds) from exc


def managed_read(handler):
    """Retain FastAPI's inspected signature and existing exception boundaries."""
    @wraps(handler)
    async def execute(*args, **kwargs):
        return await run_management_read(handler.__name__, handler, *args, **kwargs)

    return execute
