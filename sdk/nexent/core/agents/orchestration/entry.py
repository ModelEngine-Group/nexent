# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import asyncio
import logging
import threading
from concurrent.futures import CancelledError
from contextvars import Context, copy_context
from dataclasses import replace

from nexent.consts.mcp_errors import (
    classify_mcp_failure, describe_exception_leaf, find_mcp_server_url,
    is_mcp_connection_timeout_error, is_mcp_timeout_error, mcp_failure_message,
)
from nexent.core.agents.contracts.adapter import ModelOutputProtocolExhaustedError
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.orchestration.execution import (
    _emit_uncertainty_reserve_warning,
    _get_authorized_context_items,
    _get_authorized_history,
    _get_default_agent_thread_manager,
    build_run_additional_args,
    execute_adapter,
    shutdown_default_agent_thread_manager,
)
from nexent.core.agents.resources.mcp import (
    _create_mcp_http_client_without_proxy,
    _detect_transport,
    _normalize_mcp_config,
    _resolve_mcp_request_timeout_seconds,
)
from nexent.core.agents.resources.workspace import cleanup_run_workspace
from nexent.core.concurrency import (
    ManagedExecution,
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManager,
    get_current_thread_manager,
)
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.concurrency.context import _reset_current_thread_manager, _set_current_thread_manager
from nexent.core.model_errors import ModelInvocationTerminalError
from nexent.core.utils.observer import ProcessType
from nexent.monitor import (
    AgentRunMetadata,
    get_agent_monitoring_context,
    get_monitoring_manager,
    set_monitoring_capacity_snapshot,
    set_monitoring_context_budget_snapshot,
)


logger = logging.getLogger("run_agent")


def _mcp_timeout_message(agent_run_info: AgentRunInfo) -> str:
    """Return a localized MCP tool-execution timeout message."""
    timeout_label = f"{agent_run_info.mcp_tool_timeout_seconds:g}"
    if getattr(agent_run_info.observer, "lang", "en") == "zh":
        return f"MCP 工具调用超时（{timeout_label} 秒）。请确认服务响应状态后重试。"
    return (
        f"MCP tool execution timed out after {timeout_label} seconds. "
        "Please check the service response and try again."
    )


def _mcp_connection_timeout_message(agent_run_info: AgentRunInfo) -> str:
    """Return a localized MCP connection-timeout message for the current run."""
    timeout_label = f"{_resolve_mcp_request_timeout_seconds(agent_run_info):g}"
    if getattr(agent_run_info.observer, "lang", "en") == "zh":
        return f"MCP 服务连接超时（{timeout_label} 秒）。请确认服务地址和网络连通性后重试。"
    return (
        f"MCP connection timed out after {timeout_label} seconds. "
        "Please check the service address and network connectivity, then try again."
    )


def _is_mcp_timeout_error(error: BaseException) -> bool:
    """Identify an MCP timeout, including errors wrapped by the Agent runtime."""
    return is_mcp_timeout_error(error)


def _resolve_mcp_server_url(error: BaseException, mcp_host: list | None) -> str | None:
    """Best-effort server URL for user-facing messages: per-server attribution
    first, then the single configured MCP host when there is exactly one."""
    attributed = find_mcp_server_url(error)
    if attributed:
        return attributed
    urls = []
    for item in mcp_host or []:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url:
            urls.append(url)
    return urls[0] if len(urls) == 1 else None



def _mcp_failure_message(
    agent_run_info: AgentRunInfo,
    mcp_host: list | None,
    error: BaseException,
    category: str,
    leaf: BaseException | None,
) -> str:
    """Return a localized friendly message for a classified MCP failure."""
    return mcp_failure_message(
        category,
        getattr(agent_run_info.observer, "lang", "en"),
        server=_resolve_mcp_server_url(error, mcp_host),
        leaf=leaf,
    )



def _agent_run_error_message(
    agent_run_info: AgentRunInfo,
    mcp_host: list | None,
    error: BaseException,
) -> str:
    """Build the user-facing message for a failed Agent run."""
    if mcp_host and is_mcp_connection_timeout_error(error):
        return _mcp_connection_timeout_message(agent_run_info)
    if mcp_host and is_mcp_timeout_error(error):
        return _mcp_timeout_message(agent_run_info)
    if "Couldn't connect to the MCP server" in str(error):
        return (
            "MCP服务器连接超时。"
            if agent_run_info.observer.lang == "zh"
            else "Couldn't connect to the MCP server."
        )
    if mcp_host:
        category, leaf = classify_mcp_failure(error)
        if category:
            return _mcp_failure_message(agent_run_info, mcp_host, error, category, leaf)
        if isinstance(error, BaseExceptionGroup) and leaf is not None:
            return f"Run Agent Error: {describe_exception_leaf(leaf)}"
    return f"Run Agent Error: {error}"


class DeferredAgentRun:
    """Managed worker target that waits for request preparation to bind run data."""

    def __init__(self):
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._agent_run_info: AgentRunInfo | None = None
        self._context: Context | None = None
        self._cancelled = False

    def bind(self, agent_run_info: AgentRunInfo) -> None:
        with self._lock:
            if self._agent_run_info is not None:
                raise RuntimeError("Deferred agent run is already bound")
            self._agent_run_info = agent_run_info
            self._context = copy_context()
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
            context = self._context
            self._context = None
            cancelled = self._cancelled or cancel_event.is_set()
        if agent_run_info is None:
            return
        if cancelled:
            agent_run_info.cancellation_scope.cancel()
            return
        # Admission precedes request preparation. Use the binding-time trace
        # and metadata without shadowing the worker's managed execution owner.
        manager = get_current_thread_manager()

        def run_bound():
            token = _set_current_thread_manager(manager)
            try:
                agent_run_thread(agent_run_info)
            finally:
                _reset_current_thread_manager(token)

        if context is not None:
            context.run(run_bound)


def agent_run_thread(agent_run_info: AgentRunInfo):
    """Trace the complete SDK worker, including setup and resource cleanup."""
    current = get_agent_monitoring_context() or AgentRunMetadata()
    metadata = replace(
        current,
        agent_name=current.agent_name or getattr(agent_run_info.agent_config, "name", None),
        agent_display_name=current.agent_display_name or getattr(agent_run_info.agent_config, "display_name", None),
        query=current.query if current.query is not None else agent_run_info.query,
    )
    with get_monitoring_manager().start_agent_run(metadata):
        _agent_run_thread(agent_run_info)


def _agent_run_thread(agent_run_info: AgentRunInfo):
    mcp_host = getattr(agent_run_info, "mcp_host", None)
    if hasattr(agent_run_info, "run_result"):
        agent_run_info.run_result = None
    try:
        # Keep the runner compatible with legacy/lightweight AgentRunInfo
        # stand-ins used by integrations.  Full AgentRunInfo instances always
        # define this field, but its absence must not prevent a run that does
        # not need tool-side authorization context.
        set_monitoring_capacity_snapshot(
            getattr(agent_run_info, "capacity_snapshot", None)
        )
        set_monitoring_context_budget_snapshot(
            getattr(agent_run_info, "context_budget_snapshot", None)
        )
        _emit_uncertainty_reserve_warning(agent_run_info)
        mcp_host = agent_run_info.mcp_host
        execute_adapter(agent_run_info)

        from nexent.core.agents.contracts.output import RunResult

        result = getattr(agent_run_info, "run_result", None)
        agent_run_info.attempt_outcome = result.status if isinstance(result, RunResult) else (
            "stopped" if agent_run_info.stop_event.is_set() else "completed")
    except (RunTerminated, CancelledError):
        agent_run_info.attempt_outcome = "stopped"
    except (ModelInvocationTerminalError, ModelOutputProtocolExhaustedError):
        agent_run_info.attempt_outcome = "failed"
        raise
    except Exception as e:
        agent_run_info.attempt_outcome = "failed"
        logger.error(
            "event=agent_run_failed conversation_id=%s error=%r",
            getattr(agent_run_info, "conversation_id", None), e, exc_info=True,
        )
        if getattr(agent_run_info, "run_result", None) is None:
            agent_run_info.observer.add_message(
                "", ProcessType.FINAL_ANSWER, _agent_run_error_message(agent_run_info, mcp_host, e),
            )
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
                owner="nexent.core.agents.orchestration.entry",
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
            if (agent_run_info.stop_event.is_set()
                    and getattr(observer, "boundary_reached", False) is not True):
                # Stop consuming the old turn even while provider I/O is blocked.
                # The finally block cancels its managed worker and close hooks.
                raise asyncio.CancelledError
            # A creator card uses the stop signal to halt the model loop. Drain
            # its owned worker and terminal result instead of cancelling cleanup.
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


__all__ = [
    "agent_run", "agent_run_thread", "DeferredAgentRun", "shutdown_default_agent_thread_manager",
    "build_run_additional_args", "_get_authorized_context_items", "_get_authorized_history",
    "_get_default_agent_thread_manager", "_emit_uncertainty_reserve_warning", "_normalize_mcp_config",
    "_detect_transport", "_create_mcp_http_client_without_proxy",
]
