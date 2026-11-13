# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own projection, statistics and maintenance independently of Agent capture."""

from contracts.constants import environment as config
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_runtime import conversation_deleted
from infrastructure.observability.trajectory_store import TrajectoryFileStore
from management.db.trajectory.repository import ExecutionRepository
from nexent.core.concurrency import ManagedTaskSpec, ManagedThreadSpec
from ops.services.trajectory.cleanup_schedule import read_intervals
from ops.services.trajectory.statistics import StatisticsWorker, SummaryWorker


class TrajectoryWorkers:
    def __init__(self):
        self.processor = None
        self.workers = []

    def start(self, manager):
        repository = ExecutionRepository()
        self.processor = create_maintenance_processor(config)
        store = self.processor.store
        self.processor.start(
            manager,
            ManagedThreadSpec(
                task_name="trajectory-maintenance",
                owner=__name__,
                close_hook=self.processor.request_stop,
            ),
        )
        for name, worker in (
            ("trajectory-summary-compensation", SummaryWorker(store, repository)),
            ("trajectory-statistics-refresh", StatisticsWorker(store, repository)),
        ):
            self.workers.append(worker)
            execution = manager.register_service(
                ManagedThreadSpec(
                    task_name=name,
                    owner=__name__,
                    close_hook=worker.request_stop,
                ),
                worker.run,
            )
            manager.start_service(execution.execution_id)

    async def stop(self, manager):
        for worker in self.workers:
            worker.request_stop()
        if self.processor is not None:
            self.processor.request_stop()
            await manager.run(
                "control-io",
                ManagedTaskSpec("trajectory-maintenance-shutdown", __name__),
                self.processor.shutdown,
            )


def create_maintenance_processor(settings):
    """Build maintenance without provisioning or accepting captured spans."""
    repository = ExecutionRepository()
    store = TrajectoryFileStore(
        settings.TRAJECTORY_ROOT_DIR,
        authorize=lambda identity: None,
        initialization_guard=repository.initialize,
        expire_callback=repository.expire,
        retention_days=settings.TRAJECTORY_RETENTION_DAYS,
        storage_mode=getattr(settings, "TRAJECTORY_STORAGE_MODE", "single_node"),
        initialize_storage=False,
    )
    processor = LocalTrajectoryProcessor(
        store,
        lambda: None,
        maintenance_store=store,
        cleanup_enabled=settings.TRAJECTORY_CLEANUP_ENABLED,
        cleanup_interval_seconds=settings.TRAJECTORY_CLEANUP_INTERVAL_SECONDS,
        cleanup_interval_provider=read_intervals,
    )
    processor.deleted_conversation_check = conversation_deleted
    return processor
