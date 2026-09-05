import asyncio
from copy import deepcopy
import json
import logging
from contextvars import copy_context
from threading import Thread
from typing import Any, Dict, Union

import httpx
from smolagents import ToolCollection

from ...monitor import (
    set_monitoring_capacity_snapshot,
    set_monitoring_safe_input_budget_snapshot,
)
from .agent_model import AgentRunInfo
from .nexent_agent import NexentAgent, ProcessType, cleanup_run_workspace


logger = logging.getLogger("run_agent")
logger.setLevel(logging.DEBUG)


def build_run_additional_args(agent_run_info: AgentRunInfo) -> Dict[str, Any]:
    """Build isolated variables for one agent run, including empty metadata."""

    return {"metadata": deepcopy(agent_run_info.runtime_metadata)}


def _get_authorized_context_items(agent_run_info: AgentRunInfo):
    """Return the run snapshot, falling back for direct SDK callers."""
    context_input = getattr(agent_run_info, "context_input", None)
    if context_input is not None:
        return tuple(context_input.items)
    return getattr(agent_run_info.agent_config, "context_items", None)


def _get_authorized_history(agent_run_info: AgentRunInfo):
    """Return the run snapshot, falling back for direct SDK callers."""
    context_input = getattr(agent_run_info, "context_input", None)
    if context_input is not None:
        # Historical runs are ContextItems. AgentMemory is reserved for this run.
        return []
    return agent_run_info.history


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
    successful_store_count = int(
        getattr(store_tool, "successful_store_count", 0) or 0
    )
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


def _emit_uncertainty_reserve_warning(agent_run_info: AgentRunInfo) -> None:
    snapshot = getattr(agent_run_info, "safe_input_budget_snapshot", None)
    if not isinstance(snapshot, dict):
        return
    warnings = snapshot.get("warnings") or []
    if "uncertainty_reserve_active" not in warnings:
        return

    payload = {
        "code": "uncertainty_reserve_active",
        "message": (
            "W2 applied the unified 10% uncertainty reserve because selected "
            "model capability behavior is not fully verified."
        ),
        "budget_fingerprint": snapshot.get("fingerprint"),
        "w1_fingerprint": snapshot.get("w1_fingerprint"),
        "uncertainty_reserve_tokens": snapshot.get("uncertainty_reserve_tokens"),
        "hard_input_budget_tokens": snapshot.get("hard_input_budget_tokens"),
    }
    logger.warning(
        "W2 uncertainty reserve active: budget_fingerprint=%s w1_fingerprint=%s "
        "uncertainty_reserve_tokens=%s hard_input_budget_tokens=%s",
        payload["budget_fingerprint"],
        payload["w1_fingerprint"],
        payload["uncertainty_reserve_tokens"],
        payload["hard_input_budget_tokens"],
    )
    try:
        agent_run_info.observer.add_message(
            "",
            ProcessType.OTHER,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        logger.debug("Failed to emit W2 uncertainty reserve observer warning", exc_info=True)


def _detect_transport(url: str) -> str:
    """
    Auto-detect MCP transport type based on URL format.

    Args:
        url: MCP server URL

    Returns:
        Transport type: 'sse' or 'streamable-http'
    """
    url_stripped = url.strip()

    if url_stripped.endswith("/sse"):
        return "sse"
    elif url_stripped.endswith("/mcp"):
        return "streamable-http"

    return "streamable-http"


def _create_mcp_http_client_without_proxy(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an MCP HTTP client that ignores proxy environment variables."""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
        trust_env=False,
    )


def _normalize_mcp_config(mcp_host_item: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalize MCP host configuration to a dictionary format.

    Args:
        mcp_host_item: Either a string URL or a dict with 'url', optional 'transport',
                       'headers', 'authorization', or 'httpx_client_factory'

    Returns:
        Dictionary with 'url', 'transport', and supported transport options
    """
    if isinstance(mcp_host_item, str):
        url = mcp_host_item
        transport = _detect_transport(url)
        return {"url": url, "transport": transport}
    elif isinstance(mcp_host_item, dict):
        url = mcp_host_item.get("url")
        if not url:
            raise ValueError("MCP host dict must contain 'url' key")
        transport = mcp_host_item.get("transport")
        if not transport:
            transport = _detect_transport(url)
        if transport not in ("sse", "streamable-http"):
            raise ValueError(f"Invalid transport type: {transport}. Must be 'sse' or 'streamable-http'")

        result = {"url": url, "transport": transport}

        if mcp_host_item.get("bypass_proxy") is True:
            result["httpx_client_factory"] = _create_mcp_http_client_without_proxy

        if "authorization" in mcp_host_item and "headers" in mcp_host_item:
            headers = mcp_host_item["headers"].copy() if isinstance(mcp_host_item["headers"], dict) else {}
            headers["Authorization"] = mcp_host_item["authorization"]
            result["headers"] = headers
        elif "authorization" in mcp_host_item:
            result["headers"] = {"Authorization": mcp_host_item["authorization"]}
        elif "headers" in mcp_host_item:
            result["headers"] = mcp_host_item["headers"]

        if "httpx_client_factory" in mcp_host_item:
            httpx_client_factory = mcp_host_item["httpx_client_factory"]
            if not callable(httpx_client_factory):
                raise ValueError("httpx_client_factory must be callable")
            result["httpx_client_factory"] = httpx_client_factory

        return result
    else:
        raise ValueError(f"Invalid MCP host item type: {type(mcp_host_item)}. Must be str or dict")


def agent_run_thread(agent_run_info: AgentRunInfo):
    try:
        set_monitoring_capacity_snapshot(
            getattr(agent_run_info, "capacity_snapshot", None)
        )
        set_monitoring_safe_input_budget_snapshot(
            getattr(agent_run_info, "safe_input_budget_snapshot", None)
        )
        _emit_uncertainty_reserve_warning(agent_run_info)
        mcp_host = agent_run_info.mcp_host
        if mcp_host is None or len(mcp_host) == 0:
            nexent = NexentAgent(
                observer=agent_run_info.observer,
                model_config_list=agent_run_info.model_config_list,
                stop_event=agent_run_info.stop_event,
                redis_client=agent_run_info.redis_client,
                user_context=agent_run_info.user_context,
                sandbox_config=getattr(agent_run_info, "sandbox_config", None),
                minio_client=getattr(agent_run_info, "minio_client", None),
                conversation_id=agent_run_info.conversation_id,
                user_id=agent_run_info.user_id,
                tenant_id=getattr(agent_run_info, "tenant_id", None),
                workspace_path=getattr(agent_run_info, "workspace_path", None),
                workspace_run_id=getattr(agent_run_info, "workspace_run_id", None),
                minio_files=getattr(agent_run_info, "minio_files", None),
            )
            agent = nexent.create_single_agent(  # NOSONAR - constructs the SDK's trusted CoreAgent implementation.
                agent_run_info.agent_config,
                context_items_override=_get_authorized_context_items(agent_run_info),
            )
            nexent.set_agent(agent)

            nexent.add_history_to_agent(_get_authorized_history(agent_run_info))
            try:
                nexent.agent_run_with_observer(
                    query=agent_run_info.query,
                    reset=False,
                    additional_args=build_run_additional_args(agent_run_info),
                )
            finally:
                _log_memory_value_assessment(agent)
        else:
            agent_run_info.observer.add_message(
                "", ProcessType.AGENT_NEW_RUN, "<MCP_START>")
            mcp_client_list = [_normalize_mcp_config(item) for item in mcp_host]

            with ToolCollection.from_mcp(mcp_client_list, trust_remote_code=True) as tool_collection:
                nexent = NexentAgent(
                    observer=agent_run_info.observer,
                    model_config_list=agent_run_info.model_config_list,
                    stop_event=agent_run_info.stop_event,
                    mcp_tool_collection=tool_collection,
                    redis_client=agent_run_info.redis_client,
                    user_context=agent_run_info.user_context,
                    sandbox_config=getattr(agent_run_info, "sandbox_config", None),
                    minio_client=getattr(agent_run_info, "minio_client", None),
                    conversation_id=agent_run_info.conversation_id,
                    user_id=agent_run_info.user_id,
                    tenant_id=getattr(agent_run_info, "tenant_id", None),
                    workspace_path=getattr(agent_run_info, "workspace_path", None),
                    workspace_run_id=getattr(agent_run_info, "workspace_run_id", None),
                    minio_files=getattr(agent_run_info, "minio_files", None),
                )
                agent = nexent.create_single_agent(  # NOSONAR - constructs the SDK's trusted CoreAgent implementation.
                    agent_run_info.agent_config,
                    context_items_override=_get_authorized_context_items(agent_run_info),
                )
                nexent.set_agent(agent)

                nexent.add_history_to_agent(_get_authorized_history(agent_run_info))
                try:
                    nexent.agent_run_with_observer(
                        query=agent_run_info.query,
                        reset=False,
                        additional_args=build_run_additional_args(agent_run_info),
                    )
                finally:
                    _log_memory_value_assessment(agent)

    except Exception as e:
        if "Couldn't connect to the MCP server" in str(e):
            mcp_connect_error_str = "MCP服务器连接超时。" if agent_run_info.observer.lang == "zh" else "Couldn't connect to the MCP server."
            agent_run_info.observer.add_message(
                "", ProcessType.FINAL_ANSWER, mcp_connect_error_str)
        else:
            agent_run_info.observer.add_message(
                "", ProcessType.FINAL_ANSWER, f"Run Agent Error: {e}")
        raise ValueError(f"Error in agent_run_thread: {e}")
    finally:
        # Agent construction, MCP setup, and executor initialization can fail
        # before NexentAgent.agent_run_with_observer() enters its own cleanup
        # block. This idempotent outer guard owns the complete worker lifetime.
        cleanup_run_workspace(
            getattr(agent_run_info, "workspace_path", None),
            getattr(agent_run_info, "workspace_run_id", None),
            logger,
        )


async def agent_run(agent_run_info: AgentRunInfo):
    observer = agent_run_info.observer

    ctx = copy_context()
    thread_agent = Thread(target=ctx.run, args=(agent_run_thread, agent_run_info))
    thread_agent.start()

    while thread_agent.is_alive():
        cached_message = observer.get_cached_message()
        for message in cached_message:
            yield message
            if len(cached_message) < 8:
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)

    cached_message = observer.get_cached_message()
    for message in cached_message:
        yield message
