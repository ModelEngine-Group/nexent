import asyncio
import json
import logging
import threading
from copy import deepcopy
from typing import Any, Dict, Union

import httpx

from ...monitor import (
    set_monitoring_capacity_snapshot,
    set_monitoring_context_budget_snapshot,
)
from ..concurrency import ManagedExecution, ManagedTaskSpec, RunCancellationScope, ThreadManager
from ..concurrency.helpers import (
    get_fallback_thread_manager,
    shutdown_fallback_thread_manager,
)
from ..human_interaction.contracts import AttemptSuspended, RecoveryRequired, RunTerminated
from .agent_model import AgentRunInfo
from .managed_mcp import ManagedMCPToolCollection
from .nexent_agent import NexentAgent, ProcessType, cleanup_run_workspace


logger = logging.getLogger("run_agent")
logger.setLevel(logging.DEBUG)


class DeferredAgentRun:
    """Managed worker target that waits for request preparation to bind run data."""

    def __init__(self):
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._agent_run_info: AgentRunInfo | None = None
        self._cancelled = False

    def bind(self, agent_run_info: AgentRunInfo) -> None:
        with self._lock:
            if self._agent_run_info is not None:
                raise RuntimeError("Deferred agent run is already bound")
            self._agent_run_info = agent_run_info
            cancelled = self._cancelled
            self._ready.set()
        if cancelled:
            agent_run_info.cancellation_scope.cancel()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            agent_run_info = self._agent_run_info
            self._ready.set()
        if agent_run_info is not None:
            agent_run_info.cancellation_scope.cancel()

    def run(self, cancel_event: threading.Event) -> None:
        while not self._ready.wait(0.05):
            if cancel_event.is_set():
                self.cancel()
                return
        with self._lock:
            agent_run_info = self._agent_run_info
            cancelled = self._cancelled or cancel_event.is_set()
        if agent_run_info is None:
            return
        if cancelled:
            agent_run_info.cancellation_scope.cancel()
            return
        agent_run_thread(agent_run_info)


def _get_default_agent_thread_manager() -> ThreadManager:
    """Return a bounded fallback for direct SDK callers.

    Backend services must inject their process-local manager. The fallback keeps
    the public SDK call compatible and can be closed explicitly with
    ``shutdown_default_agent_thread_manager``.
    """
    return get_fallback_thread_manager()


async def shutdown_default_agent_thread_manager(timeout: float = 15.0):
    """Close the direct-SDK fallback manager when an embedding process exits."""
    return await shutdown_fallback_thread_manager(timeout=timeout)


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


def _emit_uncertainty_reserve_warning(agent_run_info: AgentRunInfo) -> None:
    snapshot = getattr(agent_run_info, "context_budget_snapshot", None)
    if snapshot is None:
        return
    warnings = snapshot.warnings
    if "uncertainty_reserve_active" not in warnings:
        return

    payload = {
        "code": "uncertainty_reserve_active",
        "message": (
            "W2 applied the unified 10% uncertainty reserve because selected "
            "model capability behavior is not fully verified."
        ),
        "budget_fingerprint": snapshot.fingerprint,
        "w1_fingerprint": snapshot.w1_fingerprint,
        "uncertainty_reserve_tokens": snapshot.uncertainty_reserve_tokens,
        "effective_input_limit_tokens": snapshot.effective_input_limit_tokens,
    }
    logger.warning(
        "W2 uncertainty reserve active: budget_fingerprint=%s w1_fingerprint=%s "
        "uncertainty_reserve_tokens=%s effective_input_limit_tokens=%s",
        payload["budget_fingerprint"],
        payload["w1_fingerprint"],
        payload["uncertainty_reserve_tokens"],
        payload["effective_input_limit_tokens"],
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
        set_monitoring_context_budget_snapshot(
            getattr(agent_run_info, "context_budget_snapshot", None)
        )
        _emit_uncertainty_reserve_warning(agent_run_info)
        mcp_host = agent_run_info.mcp_host
        if mcp_host is None or len(mcp_host) == 0:
            nexent = NexentAgent(
                observer=agent_run_info.observer,
                model_config_list=agent_run_info.model_config_list,
                stop_event=agent_run_info.stop_event,
                redis_client=agent_run_info.redis_client,
                sandbox_config=getattr(agent_run_info, "sandbox_config", None),
                minio_client=getattr(agent_run_info, "minio_client", None),
                conversation_id=agent_run_info.conversation_id,
                user_id=agent_run_info.user_id,
                tenant_id=getattr(agent_run_info, "tenant_id", None),
                workspace_path=getattr(agent_run_info, "workspace_path", None),
                workspace_run_id=getattr(agent_run_info, "workspace_run_id", None),
                minio_files=getattr(agent_run_info, "minio_files", None),
                cancellation_scope=agent_run_info.cancellation_scope,
            )
            agent = nexent.create_single_agent(  # NOSONAR - constructs the SDK's trusted CoreAgent implementation.
                agent_run_info.agent_config,
                context_items_override=_get_authorized_context_items(agent_run_info),
            )
            nexent.set_agent(agent)
            if agent_run_info.human_interaction is not None:
                agent_run_info.human_interaction.attach(agent)

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
            agent_run_info.observer.add_message("", ProcessType.AGENT_NEW_RUN, "<MCP_START>")
            mcp_client_list = [_normalize_mcp_config(item) for item in mcp_host]
            mcp_cancellation_scope = agent_run_info.cancellation_scope or RunCancellationScope(
                agent_run_info.stop_event
            )

            with ManagedMCPToolCollection(
                manager=agent_run_info.thread_manager or _get_default_agent_thread_manager(),
                server_parameters=mcp_client_list,
                cancellation_scope=mcp_cancellation_scope,
                tool_timeout_seconds=agent_run_info.mcp_tool_timeout_seconds,
                close_timeout_seconds=agent_run_info.mcp_close_timeout_seconds,
            ) as tool_collection:
                nexent = NexentAgent(
                    observer=agent_run_info.observer,
                    model_config_list=agent_run_info.model_config_list,
                    stop_event=agent_run_info.stop_event,
                    mcp_tool_collection=tool_collection,
                    redis_client=agent_run_info.redis_client,
                    sandbox_config=getattr(agent_run_info, "sandbox_config", None),
                    minio_client=getattr(agent_run_info, "minio_client", None),
                    conversation_id=agent_run_info.conversation_id,
                    user_id=agent_run_info.user_id,
                    tenant_id=getattr(agent_run_info, "tenant_id", None),
                    workspace_path=getattr(agent_run_info, "workspace_path", None),
                    workspace_run_id=getattr(agent_run_info, "workspace_run_id", None),
                    minio_files=getattr(agent_run_info, "minio_files", None),
                    cancellation_scope=agent_run_info.cancellation_scope,
                )
                agent = nexent.create_single_agent(  # NOSONAR - constructs the SDK's trusted CoreAgent implementation.
                    agent_run_info.agent_config,
                    context_items_override=_get_authorized_context_items(agent_run_info),
                )
                nexent.set_agent(agent)
                if agent_run_info.human_interaction is not None:
                    agent_run_info.human_interaction.attach(agent)

                nexent.add_history_to_agent(_get_authorized_history(agent_run_info))
                try:
                    nexent.agent_run_with_observer(
                        query=agent_run_info.query,
                        reset=False,
                        additional_args=build_run_additional_args(agent_run_info),
                    )
                finally:
                    _log_memory_value_assessment(agent)

        agent_run_info.attempt_outcome = "stopped" if agent_run_info.stop_event.is_set() else "completed"
    except AttemptSuspended:
        agent_run_info.attempt_outcome = "waiting_human"
    except RunTerminated:
        agent_run_info.attempt_outcome = "stopped"
    except RecoveryRequired:
        agent_run_info.attempt_outcome = "recovery_required"
        message = (
            "执行进程已中断。为避免重复执行操作，本次任务无法自动恢复，请重新发起任务。"
            if agent_run_info.observer.lang == "zh" else
            "Execution was interrupted. To avoid repeating actions, this task cannot resume automatically. "
            "Please start a new task."
        )
        agent_run_info.observer.add_message("", ProcessType.ERROR, message)
    except Exception as e:
        agent_run_info.attempt_outcome = "failed"
        if "Couldn't connect to the MCP server" in str(e):
            mcp_connect_error_str = (
                "MCP服务器连接超时。"
                if agent_run_info.observer.lang == "zh"
                else "Couldn't connect to the MCP server."
            )
            agent_run_info.observer.add_message("", ProcessType.FINAL_ANSWER, mcp_connect_error_str)
        else:
            agent_run_info.observer.add_message("", ProcessType.FINAL_ANSWER, f"Run Agent Error: {e}")
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


async def agent_run(
    agent_run_info: AgentRunInfo,
    thread_manager: ThreadManager | None = None,
    execution: ManagedExecution | None = None,
    deferred_run: DeferredAgentRun | None = None,
):
    observer = agent_run_info.observer
    manager = thread_manager or _get_default_agent_thread_manager()
    run_id = getattr(agent_run_info, "workspace_run_id", None)
    if run_id is None and getattr(agent_run_info, "conversation_id", None) is not None:
        run_id = str(agent_run_info.conversation_id)
    runtime_metadata = getattr(agent_run_info, "runtime_metadata", {}) or {}
    if agent_run_info.cancellation_scope is None:
        agent_run_info.cancellation_scope = RunCancellationScope(agent_run_info.stop_event)
    agent_run_info.thread_manager = manager
    if execution is None:
        execution = manager.submit(
            "agent-run",
            ManagedTaskSpec(
                task_name="agent-run",
                owner="nexent.core.agents.run_agent",
                run_id=run_id,
                attempt_id=runtime_metadata.get("attempt_id"),
                close_hook=agent_run_info.cancellation_scope.cancel,
            ),
            agent_run_thread,
            agent_run_info,
        )
    elif deferred_run is None:
        raise ValueError("deferred_run is required with a pre-admitted execution")
    else:
        deferred_run.bind(agent_run_info)
    agent_run_info.thread_execution_id = execution.execution_id
    agent_run_info.thread_future = execution.future

    worker_finished = False
    try:
        while not execution.future.done():
            cached_message = observer.get_cached_message()
            for message in cached_message:
                yield message
                if len(cached_message) < 8:
                    await asyncio.sleep(0.05)
            await asyncio.sleep(0.1)
        worker_finished = True

        # Consume the exception so the Future does not emit an unobserved failure.
        # agent_run_thread has already converted it into an observer error message.
        try:
            execution.future.result()
        except Exception:
            logger.debug(
                "event=agent_managed_execution_failed execution_id=%s run_id=%s",
                execution.execution_id,
                run_id or "",
                exc_info=True,
            )

        cached_message = observer.get_cached_message()
        for message in cached_message:
            yield message
    finally:
        if not worker_finished and not execution.future.done():
            agent_run_info.stop_event.set()
            manager.cancel(
                execution.execution_id,
                reason="agent stream consumer closed",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
