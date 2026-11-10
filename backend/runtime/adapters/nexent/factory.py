# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Construct SDK run objects without business lookups or deployment configuration."""

import threading
from pathlib import Path

from nexent.core.agents.agent_model import AgentRunInfo
from nexent.core.utils.observer import MessageObserver


def build_run_info(*, language="zh", **prepared_values) -> AgentRunInfo:
    """Own local observer/cancellation primitives while preserving injected identities."""
    if "observer" not in prepared_values:
        prepared_values["observer"] = MessageObserver(lang=language)
    if "stop_event" not in prepared_values:
        prepared_values["stop_event"] = threading.Event()
    return AgentRunInfo(**prepared_values)

def materialize_legacy_run(
    *, agent_config, workspace_path, workspace_root, sandbox_policy, sandbox_minio_client_factory, **values,
) -> AgentRunInfo:
    """Build sandbox resources and local SDK objects for the compatibility path."""
    from contracts.constants.environment import (
        NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT,
        NEXENT_SANDBOX_FAILURE_POLICY,
        NEXENT_SANDBOX_WORKSPACE_MODE,
        NEXENT_SANDBOX_WORKSPACE_VOLUME,
    )
    from runtime.adapters.nexent.sandbox import resolve_sandbox_config

    sandbox_config = resolve_sandbox_config(
        getattr(agent_config, "sandbox_policy", None),
        sandbox_policy,
        workspace_mode=NEXENT_SANDBOX_WORKSPACE_MODE,
        container_workspace_root=NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT,
        failure_policy=NEXENT_SANDBOX_FAILURE_POLICY,
    )
    sandbox_minio_client = (
        sandbox_minio_client_factory() if sandbox_config and sandbox_config.auto_sync_outputs else None
    )
    if sandbox_config is not None:
        sandbox_config.output_dir = str(Path(workspace_path) / "outputs")
        sandbox_config.extra_kwargs = {
            **sandbox_config.extra_kwargs,
            "workspace_root": str(Path(workspace_root).resolve()),
            "workspace_path": workspace_path,
        }
        if (
            getattr(sandbox_config.level, "value", sandbox_config.level) == "docker"
            and getattr(sandbox_config.scope, "value", sandbox_config.scope) == "system"
            and sandbox_config.workspace_mode == "legacy"
        ):
            sandbox_config.extra_kwargs.update(
                {"workspace_volume_name": NEXENT_SANDBOX_WORKSPACE_VOLUME, "shared_workspace": True}
            )

    return build_run_info(
        agent_config=agent_config,
        workspace_path=workspace_path,
        sandbox_config=sandbox_config,
        minio_client=sandbox_minio_client,
        **values,
    )
