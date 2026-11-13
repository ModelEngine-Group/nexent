# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backend wiring for trusted trajectory capture and its managed I/O service."""

from __future__ import annotations


def authorize_capture(identity):
    """Use the existing tenant membership and conversation ownership queries."""
    from management.db.conversation.repository import get_conversation
    from management.db.identity.user_tenant import get_user_tenant_in_tenant

    member = get_user_tenant_in_tenant(identity.owner_user_id, identity.tenant_id)
    if not member or member.get("delete_flag") != "N":
        raise PermissionError("Trajectory capture owner is not an active tenant member")
    conversation = get_conversation(
        int(identity.conversation_id), user_id=identity.owner_user_id, tenant_id=identity.tenant_id
    )
    if not conversation or conversation.get("created_by") != identity.owner_user_id:
        raise PermissionError("Trajectory capture conversation ownership differs")


def create_local_processor(config, metadata_provider):
    """Keep environment reads in the backend configuration module."""
    capturing = config.ENABLE_TELEMETRY and config.MONITORING_PROVIDER == "local_file"
    maintaining = config.MONITORING_PROVIDER == "local_file" or config.TRAJECTORY_READ_ENABLED
    if not capturing and not maintaining:
        return None
    from management.db.trajectory.repository import ExecutionRepository
    from management.services.trajectory.cleanup_schedule import read_intervals

    from .trajectory_processor import LocalTrajectoryProcessor
    from .trajectory_store import TrajectoryFileStore

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
    # Maintenance identities come only from manifests under the verified storage root.
    maintenance = TrajectoryFileStore(
        config.TRAJECTORY_ROOT_DIR,
        authorize=lambda identity: None,
        initialization_guard=repository.initialize,
        expire_callback=repository.expire,
        retention_days=config.TRAJECTORY_RETENTION_DAYS,
        storage_mode=getattr(config, "TRAJECTORY_STORAGE_MODE", "single_node"),
    )
    return LocalTrajectoryProcessor(
        store,
        metadata_provider,
        flush_interval_ms=config.TRAJECTORY_FLUSH_INTERVAL_MS,
        flush_bytes=config.TRAJECTORY_FLUSH_BYTES,
        queue_max_bytes=config.TRAJECTORY_QUEUE_MAX_BYTES,
        run_queue_max_bytes=config.TRAJECTORY_RUN_QUEUE_MAX_BYTES,
        maintenance_store=maintenance,
        cleanup_enabled=config.TRAJECTORY_CLEANUP_ENABLED,
        cleanup_interval_seconds=config.TRAJECTORY_CLEANUP_INTERVAL_SECONDS,
        cleanup_interval_provider=read_intervals,
    )


def capture_sources(identity, upper=None):
    """Read only scalar IDs from the same currently authorized conversation."""
    from management.db.conversation.trajectory_catalog import TrajectoryCatalog

    return TrajectoryCatalog().source_messages(
        identity.tenant_id, identity.owner_user_id, identity.conversation_id, upper=upper,
    )


def conversation_deleted(identity):
    """Only a confirmed PG absence permits maintenance to reclaim an orphan."""
    from management.db.conversation.trajectory_catalog import TrajectoryCatalog

    return TrajectoryCatalog().conversation_deleted(identity.conversation_id, identity.owner_user_id)


def request_conversation_cleanup(conversation_ids, owner_user_id):
    """Submit confirmed deletions without doing filesystem work on the HTTP loop."""
    from contracts.constants import environment as config

    if config.MONITORING_PROVIDER != "local_file" and not config.TRAJECTORY_READ_ENABLED:
        return True
    from .bootstrap import local_trajectory_processor

    return local_trajectory_processor is not None and local_trajectory_processor.request_conversation_cleanup(
        conversation_ids, owner_user_id,
    )
