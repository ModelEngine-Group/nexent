# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Construct SDK run objects without business lookups or deployment configuration."""

import threading
from pathlib import Path

from contracts.constants import environment
from infrastructure.redis.client import get_redis_client
from infrastructure.sandbox_deployment import get_sandbox_minio_client
from nexent.core.agents.agent_model import AgentRunInfo
from nexent.core.utils.observer import MessageObserver


def build_run_info(*, language="zh", **prepared_values) -> AgentRunInfo:
    """Own local observer/cancellation primitives while preserving injected identities."""
    if "observer" not in prepared_values:
        prepared_values["observer"] = MessageObserver(lang=language)
    if "stop_event" not in prepared_values:
        prepared_values["stop_event"] = threading.Event()
    return AgentRunInfo(**prepared_values)


def materialize_legacy_run(*, agent_config, workspace_path, **values) -> AgentRunInfo:
    """Resolve Runtime deployment settings for the in-process compatibility path."""
    from runtime.adapters.nexent.sandbox import resolve_deployed_sandbox

    return materialize_run(
        agent_config=agent_config,
        workspace_path=workspace_path,
        workspace_root=environment.AGENT_WORKSPACE_ROOT,
        mcp_request_timeout_seconds=environment.MCP_REQUEST_TIMEOUT_SECONDS,
        mcp_tool_timeout_seconds=environment.RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
        mcp_close_timeout_seconds=environment.RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
        tool_fastpath_enabled=environment.NEXENT_TOOL_FASTPATH_ENABLED,
        tool_fastpath_allowed_tools=list(environment.NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS),
        redis_client=get_redis_client(),
        sandbox_config=resolve_deployed_sandbox(getattr(agent_config, "sandbox_policy", None)),
        **values,
    )


def materialize_run(*, agent_config, workspace_path, workspace_root, sandbox_config, **values) -> AgentRunInfo:
    """Attach the sandbox workspace and output storage to the SDK run."""
    sandbox_minio_client = (
        get_sandbox_minio_client() if sandbox_config and sandbox_config.auto_sync_outputs else None
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
                {"workspace_volume_name": environment.NEXENT_SANDBOX_WORKSPACE_VOLUME, "shared_workspace": True}
            )

    return build_run_info(
        agent_config=agent_config,
        workspace_path=workspace_path,
        sandbox_config=sandbox_config,
        minio_client=sandbox_minio_client,
        **values,
    )
