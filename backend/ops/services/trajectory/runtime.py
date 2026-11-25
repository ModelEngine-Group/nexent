# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Construct the read service independently of telemetry capture enablement."""

import threading

from .primitives import QueryError, ReferenceStore

_lock = threading.Lock()
_service = None
_cache_client = None


def get_service():
    from contracts.constants import environment as config

    if not config.TRAJECTORY_READ_ENABLED:
        raise QueryError("trajectory_read_disabled", 404)
    global _service, _cache_client
    with _lock:
        if _service is None:
            from infrastructure.trace.trajectory_io import (
                TrajectoryConflict,
                TrajectoryCorrupt,
            )
            from infrastructure.trace.trajectory_runtime import capture_sources
            from infrastructure.trace.trajectory_store import (
                TrajectoryFileStore,
            )
            from infrastructure.rdb.trajectory.repository import ExecutionRepository
            from ops.db.trajectory.catalog import TrajectoryCatalog
            from ops.db.trajectory.queries import ExecutionCatalog

            from .archive import storage_error
            from .redis_cache import shared_caches
            from .service import TrajectoryService

            client, reference_cache, query_cache = shared_caches(config.REDIS_BACKEND_URL)
            try:
                references = ReferenceStore(cache=reference_cache)
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
                client.close()
                raise QueryError("trajectory_configuration_invalid", 503) from error
            except (OSError, TrajectoryConflict, TrajectoryCorrupt) as error:
                client.close()
                raise storage_error(error) from error
            _cache_client = client
            _service = TrajectoryService(
                store,
                catalog,
                references,
                max_bytes=config.TRAJECTORY_QUERY_MAX_BYTES,
                max_candidates=config.TRAJECTORY_QUERY_MAX_CANDIDATES,
                source_query=capture_sources,
                execution_catalog=ExecutionCatalog(),
                query_cache=query_cache,
            )
    return _service


def reset_service():
    """Close this process's Redis pool; shared references retain their original TTL."""
    global _service, _cache_client
    with _lock:
        _service = None
        if _cache_client is not None:
            _cache_client.close()
            _cache_client = None
