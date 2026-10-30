# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from typing import Any

from nexent.core.agents.cores.smolagents.agent import NexentAgent
from nexent.core.agents.orchestration.execution import (
    _get_authorized_context_items,
    _get_authorized_history,
    _get_default_agent_thread_manager,
    build_run_additional_args,
)
from nexent.core.agents.resources.mcp import (
    ManagedMCPToolCollection,
    _normalize_mcp_config,
    _resolve_mcp_request_timeout_seconds,
)
from nexent.core.concurrency import RunCancellationScope
from nexent.core.utils.observer import ProcessType


logger = logging.getLogger("run_agent")


def _log_memory_value_assessment(agent: Any) -> None:
    """Emit one content-free memory assessment summary for each agent run."""
    tools = getattr(agent, "tools", {}) or {}
    store_tool = tools.get("store_memory") if hasattr(tools, "get") else None
    if store_tool is None:
        logger.info(
            "event=memory_value_assessment decision=unavailable "
            "invocation_count=0 successful_store_count=0 last_outcome=tool_unavailable"
        )
        return

    invocation_count = int(getattr(store_tool, "invocation_count", 0) or 0)
    successful_store_count = int(getattr(store_tool, "successful_store_count", 0) or 0)
    decision = "store_attempted" if invocation_count else "skip"
    logger.info(
        "event=memory_value_assessment tenant_id=%s user_id=%s agent_id=%s "
        "conversation_id=%s decision=%s invocation_count=%d "
        "successful_store_count=%d last_outcome=%s",
        getattr(store_tool, "tenant_id", ""),
        getattr(store_tool, "user_id", ""),
        getattr(store_tool, "agent_id", ""),
        getattr(store_tool, "conversation_id", ""),
        decision,
        invocation_count,
        successful_store_count,
        getattr(store_tool, "last_outcome", "not_invoked"),
    )


def _run_with_resources(agent_run_info, tool_collection=None):
    """Own resources from partial setup through execution and cleanup."""
    user_context = getattr(agent_run_info, "user_context", None)
    kwargs = dict(
        observer=agent_run_info.observer,
        model_config_list=agent_run_info.model_config_list,
        stop_event=agent_run_info.stop_event,
        redis_client=agent_run_info.redis_client,
        user_context=user_context,
        sandbox_config=getattr(agent_run_info, "sandbox_config", None),
        tool_fastpath_enabled=getattr(agent_run_info, "tool_fastpath_enabled", True),
        tool_fastpath_allowed_tools=getattr(agent_run_info, "tool_fastpath_allowed_tools", None),
        minio_client=getattr(agent_run_info, "minio_client", None),
        conversation_id=agent_run_info.conversation_id,
        user_id=agent_run_info.user_id,
        tenant_id=getattr(agent_run_info, "tenant_id", None),
        workspace_path=getattr(agent_run_info, "workspace_path", None),
        workspace_run_id=getattr(agent_run_info, "workspace_run_id", None),
        minio_files=getattr(agent_run_info, "minio_files", None),
        cancellation_scope=agent_run_info.cancellation_scope,
    )
    if tool_collection is not None:
        kwargs["mcp_tool_collection"] = tool_collection
    nexent = NexentAgent(**kwargs)
    agent = None
    try:
        nexent.core_run_info = agent_run_info
        agent = nexent.create_single_agent(  # NOSONAR - constructs the SDK's trusted CoreAgent implementation.
            agent_run_info.agent_config,
            context_items_override=_get_authorized_context_items(agent_run_info),
        )
        nexent.set_agent(agent)

        nexent.add_history_to_agent(_get_authorized_history(agent_run_info))
        return nexent.agent_run_with_observer(
            query=agent_run_info.query,
            reset=False,
            additional_args=build_run_additional_args(agent_run_info),
        )
    finally:
        try:
            if agent is not None:
                _log_memory_value_assessment(agent)
        finally:
            nexent.close()


def _run_smolagents(agent_run_info):
    """Execute only the smolagents loop with shared managed resources."""
    mcp_host = agent_run_info.mcp_host
    if not mcp_host:
        return _run_with_resources(agent_run_info)
    agent_run_info.observer.add_message("", ProcessType.AGENT_NEW_RUN, "<MCP_START>")
    from nexent.core.agents.resources.compatibility.smolagents_tools import mcp_adapter_factory
    with ManagedMCPToolCollection(
        manager=agent_run_info.thread_manager or _get_default_agent_thread_manager(),
        server_parameters=[_normalize_mcp_config(item) for item in mcp_host],
        cancellation_scope=agent_run_info.cancellation_scope or RunCancellationScope(agent_run_info.stop_event),
        tool_timeout_seconds=agent_run_info.mcp_tool_timeout_seconds,
        close_timeout_seconds=agent_run_info.mcp_close_timeout_seconds,
        connect_timeout_seconds=_resolve_mcp_request_timeout_seconds(agent_run_info),
        tool_adapter_factory=mcp_adapter_factory,
    ) as tool_collection:
        return _run_with_resources(agent_run_info, tool_collection)
