# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own process-local operations startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from management.configuration.database import configuration_database
from nexent.core.concurrency import LanePolicy, ThreadManager

OPS_THREAD_SHUTDOWN_GRACE_SECONDS = 30.0


@asynccontextmanager
async def ops_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own readiness, managed I/O workers and configuration connections."""
    manager = ThreadManager(
        service_name="ops",
        lane_policies={
            "control-io": LanePolicy(
                name="control-io",
                max_workers=4,
                max_queue_size=32,
                queue_timeout_seconds=0,
                cancel_grace_seconds=2,
                shutdown_grace_seconds=OPS_THREAD_SHUTDOWN_GRACE_SECONDS,
            )
        },
    )
    app.state.thread_manager = manager
    try:
        manager.start()
        app.state.ready = True
        yield
    finally:
        app.state.ready = False
        await manager.shutdown(timeout=OPS_THREAD_SHUTDOWN_GRACE_SECONDS)
        configuration_database.dispose()
