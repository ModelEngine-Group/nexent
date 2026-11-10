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
    capturing = config.ENABLE_TELEMETRY and config.MONITORING_TRACE_SINK in {"local_file", "both"}
    if not capturing and not (config.TRAJECTORY_ROOT_DIR and config.TRAJECTORY_CLEANUP_ENABLED):
        return None
    from .trajectory_processor import LocalTrajectoryProcessor
    from .trajectory_store import TrajectoryFileStore

    store = TrajectoryFileStore(
        config.TRAJECTORY_ROOT_DIR,
        config.TRAJECTORY_STORAGE_ROOT_ID,
        authorize=authorize_capture,
        retention_days=config.TRAJECTORY_RETENTION_DAYS,
    )
    # Maintenance identities come only from manifests under the verified storage root.
    maintenance = TrajectoryFileStore(
        config.TRAJECTORY_ROOT_DIR,
        config.TRAJECTORY_STORAGE_ROOT_ID,
        authorize=lambda identity: None,
        retention_days=config.TRAJECTORY_RETENTION_DAYS,
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
    )


def main():
    import argparse

    from .trajectory_store import TrajectoryFileStore

    parser = argparse.ArgumentParser(description="Register a persistent local trajectory root")
    parser.add_argument("--root", required=True)
    parser.add_argument("--storage-root-id", required=True)
    args = parser.parse_args()
    TrajectoryFileStore.provision(args.root, args.storage_root_id)


if __name__ == "__main__":
    main()
