# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment defaults and storage wiring for sandbox execution."""

from contracts.constants import environment


def default_sandbox_policy() -> dict | None:
    """Build the deployment policy, leaving local execution unconfigured."""
    level = environment.NEXENT_SANDBOX_DEFAULT_LEVEL
    if level == "local":
        return None

    return {
        "level": level,
        "scope": environment.NEXENT_SANDBOX_DEFAULT_SCOPE,
        "docker_image": environment.NEXENT_SANDBOX_DOCKER_IMAGE,
        "memory_limit_mb": environment.NEXENT_SANDBOX_MEMORY_LIMIT_MB,
        "cpu_quota": environment.NEXENT_SANDBOX_CPU_QUOTA,
        "timeout_seconds": environment.NEXENT_SANDBOX_TIMEOUT_S,
        "host_tool_timeout_seconds": environment.NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S,
        "network_disabled": environment.NEXENT_SANDBOX_NETWORK_DISABLED,
        "shell_policy": environment.NEXENT_SANDBOX_SHELL_POLICY,
        "auto_sync_outputs": environment.NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS,
    }


def get_sandbox_minio_client():
    """
    Build a run-local MinIO client for sandbox output sync, if configured.
    """
    if not environment.MINIO_ENDPOINT:
        return None

    try:
        from nexent.storage import MinIOStorageClient
    except ImportError:
        return None

    client = MinIOStorageClient(
        endpoint=environment.MINIO_ENDPOINT,
        access_key=environment.MINIO_ACCESS_KEY or "",
        secret_key=environment.MINIO_SECRET_KEY or "",
        region=None,
        default_bucket=environment.NEXENT_SANDBOX_OUTPUT_BUCKET,
        secure=environment.MINIO_SECURE,
    )
    return client
