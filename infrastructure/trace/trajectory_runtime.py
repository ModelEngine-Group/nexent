# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backend wiring for trusted trajectory capture and its managed I/O service."""

from __future__ import annotations


def authorize_capture(identity):
    """Use the existing tenant membership and conversation ownership queries."""
    from infrastructure.rdb.trajectory.capture import CaptureCatalog

    CaptureCatalog().authorize(identity)


def create_local_processor(config, metadata_provider, *, repository=None):
    """Keep environment reads in the backend configuration module."""
    if not trajectory_storage_enabled(config):
        return None
    from infrastructure.rdb.trajectory.repository import ExecutionRepository

    from .trajectory_processor import LocalTrajectoryProcessor
    from .trajectory_store import TrajectoryFileStore

    if repository is None:
        repository = ExecutionRepository()
    store = TrajectoryFileStore(
        config.TRAJECTORY_ROOT_DIR,
        authorize=authorize_capture,
        initialization_guard=repository.initialize,
        expire_callback=repository.expire,
        retention_days=config.TRAJECTORY_RETENTION_DAYS,
        source_query=capture_sources,
        storage_mode=getattr(config, "TRAJECTORY_STORAGE_MODE", "single_node"),
    )
    return LocalTrajectoryProcessor(
        store,
        metadata_provider,
        flush_interval_ms=config.TRAJECTORY_FLUSH_INTERVAL_MS,
        flush_bytes=config.TRAJECTORY_FLUSH_BYTES,
        queue_max_bytes=config.TRAJECTORY_QUEUE_MAX_BYTES,
        run_queue_max_bytes=config.TRAJECTORY_RUN_QUEUE_MAX_BYTES,
        cleanup_interval_seconds=config.TRAJECTORY_CLEANUP_INTERVAL_SECONDS,
    )


def trajectory_storage_enabled(config):
    return (
        config.LOCAL_FILE_MONITORING_ENABLED
        or config.TRAJECTORY_READ_ENABLED
        or config.MONITORING_PROVIDER == "local_file"
    )


def capture_sources(identity, upper=None):
    """Read only scalar IDs from the same currently authorized conversation."""
    from infrastructure.rdb.trajectory.capture import CaptureCatalog

    return CaptureCatalog().source_messages(
        identity.tenant_id, identity.owner_user_id, identity.conversation_id, upper=upper,
    )


def conversation_deleted(identity):
    """Only a confirmed PG absence permits maintenance to reclaim an orphan."""
    from infrastructure.rdb.trajectory.capture import CaptureCatalog

    return CaptureCatalog().conversation_deleted(identity.conversation_id, identity.owner_user_id)


def request_conversation_cleanup(conversation_ids, owner_user_id):
    """Submit confirmed deletions without doing filesystem work on the HTTP loop."""
    from contracts.constants import environment as config

    if not trajectory_storage_enabled(config):
        return True
    from .bootstrap import local_trajectory_processor

    return local_trajectory_processor is not None and local_trajectory_processor.request_conversation_cleanup(
        conversation_ids, owner_user_id,
    )
