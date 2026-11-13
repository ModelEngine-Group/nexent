# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Construct the read service independently of telemetry capture enablement."""

import threading

from .primitives import QueryError, ReferenceStore

_lock = threading.Lock()
_service = None


def get_service():
    from contracts.constants import environment as config

    if not config.TRAJECTORY_READ_ENABLED:
        raise QueryError("trajectory_read_disabled", 404)
    global _service
    with _lock:
        if _service is None:
            from infrastructure.observability.trajectory_io import (
                TrajectoryConflict,
                TrajectoryCorrupt,
            )
            from infrastructure.observability.trajectory_runtime import capture_sources
            from infrastructure.observability.trajectory_store import (
                TrajectoryFileStore,
            )
            from management.db.conversation.trajectory_catalog import TrajectoryCatalog
            from management.db.trajectory.queries import ExecutionCatalog
            from management.db.trajectory.repository import ExecutionRepository

            from .archive import storage_error
            from .service import TrajectoryService

            try:
                references = ReferenceStore()
                catalog = TrajectoryCatalog()
                store = TrajectoryFileStore(
                    config.TRAJECTORY_ROOT_DIR,
                    authorize=lambda identity: catalog.resolve(
                        [identity.tenant_id],
                        identity.conversation_id,
                        target_user_id=identity.owner_user_id,
                    ),
                    initialization_guard=ExecutionRepository().initialize,
                    expire_callback=ExecutionRepository().expire,
                    retention_days=config.TRAJECTORY_RETENTION_DAYS,
                    storage_mode=config.TRAJECTORY_STORAGE_MODE,
                    initialize_storage=False,
                )
            except ValueError as error:
                raise QueryError("trajectory_configuration_invalid", 503) from error
            except (OSError, TrajectoryConflict, TrajectoryCorrupt) as error:
                raise storage_error(error) from error
            _service = TrajectoryService(
                store,
                catalog,
                references,
                max_bytes=config.TRAJECTORY_QUERY_MAX_BYTES,
                max_candidates=config.TRAJECTORY_QUERY_MAX_CANDIDATES,
                source_query=capture_sources,
                execution_catalog=ExecutionCatalog(),
            )
    return _service
