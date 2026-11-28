# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own process-local operations startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from contracts.constants import environment as config
from infrastructure.system_configuration.database import configuration_database
from infrastructure.trace.trajectory_runtime import trajectory_storage_enabled
from ops.concurrency import create_thread_manager


def trajectory_enabled():
    return trajectory_storage_enabled(config)


def create_trajectory_workers():
    from ops.services.trajectory.lifecycle import TrajectoryWorkers

    return TrajectoryWorkers()


@asynccontextmanager
async def ops_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own readiness, managed I/O and all enabled operations resources."""
    from infrastructure.redis.run_state import runtime_state_service

    manager = create_thread_manager()
    workers = None
    app.state.thread_manager = manager
    async with AsyncExitStack() as stack:
        try:
            manager.start()
            # The northbound rate limiter (and any other Redis state call in
            # this process) runs its blocking pipeline I/O on the bounded
            # control-io lane instead of the request event loop.
            runtime_state_service.set_thread_manager(manager)
            if trajectory_enabled():
                workers = create_trajectory_workers()
                workers.start(manager)
            if config.OPS_MONITORING_ENABLED:
                from ops.monitoring.runtime import ops_monitoring_lifespan

                await stack.enter_async_context(ops_monitoring_lifespan(app))
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            runtime_state_service.set_thread_manager(None)
            try:
                if workers is not None:
                    await workers.stop(manager)
            finally:
                try:
                    await manager.shutdown(timeout=config.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
                finally:
                    if trajectory_enabled():
                        from ops.services.trajectory.runtime import reset_service

                        reset_service()
                    configuration_database.dispose()
