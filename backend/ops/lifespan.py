# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own process-local operations startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from contracts.constants import environment as config
from fastapi import FastAPI
from ops.concurrency import create_thread_manager


def trajectory_enabled():
    return config.TRAJECTORY_READ_ENABLED or config.MONITORING_PROVIDER == "local_file"


def create_trajectory_workers():
    from ops.services.trajectory.lifecycle import TrajectoryWorkers

    return TrajectoryWorkers()


@asynccontextmanager
async def ops_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep readiness aligned with all enabled operations resources."""
    manager = None
    workers = None
    try:
        if trajectory_enabled():
            manager = create_thread_manager()
            app.state.thread_manager = manager
            manager.start()
            workers = create_trajectory_workers()
            workers.start(manager)
        app.state.ready = True
        yield
    finally:
        app.state.ready = False
        try:
            if workers is not None:
                await workers.stop(manager)
        finally:
            if manager is not None:
                try:
                    await manager.shutdown(
                        timeout=config.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
                    )
                finally:
                    from ops.services.trajectory.runtime import reset_service

                    reset_service()
