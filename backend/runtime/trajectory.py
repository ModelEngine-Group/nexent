# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Wire the Runtime archive writer and execution observer with shared persistence."""

from contracts.constants import environment
from infrastructure.rdb.trajectory.repository import ExecutionRepository
from infrastructure.trace.trajectory_runtime import create_local_processor
from nexent.monitor import get_agent_monitoring_context


def configure_runtime_trajectory():
    repository = ExecutionRepository()
    processor = create_local_processor(environment, get_agent_monitoring_context, repository=repository)
    if processor is None:
        return None
    from infrastructure.trace import bootstrap
    from infrastructure.trace.trajectory_execution import execution_observer

    observer = execution_observer(
        capturing=environment.LOCAL_FILE_MONITORING_ENABLED,
        store=processor.store,
        repository=repository,
    )
    bootstrap.configure_trajectory(processor, observer)
    return processor
