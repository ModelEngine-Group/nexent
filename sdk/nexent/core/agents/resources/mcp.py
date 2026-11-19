# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from typing import Any, Callable, Dict, Union

import httpx

from nexent.consts.mcp_errors import (
    MCPConnectionFailure,
    MCPConnectionTimeoutError,
    MCPToolNotFoundError,
    MCPToolTimeoutError,
)
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.concurrency import ManagedExecution, ManagedTaskSpec, RunCancellationScope, ThreadManager


logger = logging.getLogger("managed_mcp")


class ManagedMCPToolCollection:
    """Own MCP server sessions lazily with bounded manager executions.

    Entering the collection starts the dedicated session event loop but does
    not contact any server. Each server connects on the first tool call that
    routes to it (bounded by ``connect_timeout_seconds``), the session is
    reused for the rest of the run, and all opened sessions close together on
    ``close()`` (bounded by ``close_timeout_seconds``).
    """

    def __init__(
        self,
        *,
        manager: ThreadManager,
        server_parameters: list,
        cancellation_scope: RunCancellationScope,
        tool_timeout_seconds: float,
        close_timeout_seconds: float,
        request_timeout_seconds: float | None = None,
        connect_timeout_seconds: float | None = None,
        session_context_factory: Callable[..., Any] | None = None,
        tool_builder: Callable[..., Any] | None = None,
    ):
        if tool_timeout_seconds <= 0:
            raise ValueError("MCP tool timeout must be greater than zero")
        if close_timeout_seconds <= 0:
            raise ValueError("MCP close timeout must be greater than zero")
        if request_timeout_seconds is not None and request_timeout_seconds <= 0:
            raise ValueError("MCP request timeout must be greater than zero")
        # Keep the old keyword as a compatibility alias, but use it only for
        # session startup. It must never become a per-tool request timeout.
        if connect_timeout_seconds is None:
            connect_timeout_seconds = request_timeout_seconds or 30.0
        if connect_timeout_seconds <= 0:
            raise ValueError("MCP connect timeout must be greater than zero")
        self.manager = manager
        self.cancellation_scope = cancellation_scope
        self.tool_timeout_seconds = tool_timeout_seconds
        self.close_timeout_seconds = close_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._session_context_factory = session_context_factory
        self._tool_builder = tool_builder
        # Normalize once so lazy routing works whether callers pass raw
        # strings/dicts or already-normalized entries; entries may carry a
        # server "name" for tool->server routing.
        normalized = [_normalize_mcp_config(item) for item in server_parameters]
        self.server_parameters = normalized
        self._servers: Dict[str, Dict[str, Any]] = {}
        self._server_index: Dict[str, str] = {}
        for parameters in normalized:
            canonical = parameters.get("name") or parameters["url"]
            self._servers[canonical] = parameters
            self._server_index[parameters["url"]] = canonical
            if parameters.get("name"):
                self._server_index[parameters["name"]] = canonical
        self._execution: ManagedExecution | None = None
        self._scope_token = None
        self._ready = threading.Event()
        self._close_requested = threading.Event()
        self._lock = threading.Lock()
        self._active_calls_lock = threading.Lock()
        self._active_calls: set[ConcurrentFuture] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_task: asyncio.Task | None = None
        self._async_close_event: asyncio.Event | None = None
        self._stack: AsyncExitStack | None = None
        self._startup_error: BaseException | None = None
        self._sessions: Dict[str, Any] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._live_tool_names: Dict[str, set[str]] = {}
        self.tools: list[Any] = []

    def _session_factory(self):
        if self._session_context_factory is not None:
            return self._session_context_factory
        from mcpadapt.core import mcptools

        return mcptools

    # ------------------------------------------------------------------
    # Tool construction (no network I/O; safe at agent construction time)
    # ------------------------------------------------------------------

    def _resolve_server_key(self, tool_config: Any) -> str:
        """Resolve the server a tool routes to from its ToolConfig.usage."""
        usage = getattr(tool_config, "usage", None)
        if usage and usage in self._server_index:
            return self._server_index[usage]
        if len(self._servers) == 1:
            return next(iter(self._servers))
        raise ValueError(
            f"MCP server '{usage}' is not configured for this run; "
            "check the tool's MCP binding and the run's mcp_host list"
        )

    def _wire_name_for(self, tool_config: Any) -> str:
        """Return the raw name used to invoke the tool on the server."""
        wire_name = (
            getattr(tool_config, "origin_name", None)
            or getattr(tool_config, "class_name", None)
            or getattr(tool_config, "name", None)
        )
        if not wire_name:
            raise ValueError("MCP tool config must carry a callable tool name")
        return wire_name

    def create_tool(self, tool_config: Any) -> Any:
        """Build a lazy tool object for one authorized MCP tool config.

        No connection is opened here; the returned tool connects to its
        server on first invocation through :meth:`call_tool`.
        """
        if self._tool_builder is None:
            raise ValueError("MCP tool builder is required to construct lazy MCP tools")
        server_key = self._resolve_server_key(tool_config)
        wire_name = self._wire_name_for(tool_config)

        def call_fn(arguments=None):
            return self.call_tool(server_key, wire_name, arguments)

        tool = self._tool_builder(tool_config, call_fn)
        self.tools.append(tool)
        return self.wrap_tool(tool)

    # ------------------------------------------------------------------
    # Lazy session ownership
    # ------------------------------------------------------------------

    async def _connect_server(self, parameters: Dict[str, Any]) -> tuple[Any, set[str] | None]:
        """Connect one server on the session loop; return (session, live names).

        The default implementation uses the smolagents-compatible mcpadapt
        session factory; cores with native clients override this method.
        """
        session_factory = self._session_factory()
        try:
            connection = await asyncio.wait_for(
                self._stack.enter_async_context(
                    session_factory(
                        parameters,
                        client_session_timeout_seconds=None,
                    )
                ),
                timeout=self.connect_timeout_seconds,
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except asyncio.TimeoutError as exc:
            raise MCPConnectionTimeoutError(
                f"MCP connection timed out after {self.connect_timeout_seconds:g} seconds"
            ) from exc
        except Exception as exc:
            # Attribute the failure to this server so terminal messages
            # can name it; the original error stays on __cause__.
            raise MCPConnectionFailure(
                url=str(parameters.get("url", "unknown")),
                transport=str(parameters.get("transport", "unknown")),
            ) from exc
        session, mcp_tools = connection
        return session, {mcp_tool.name for mcp_tool in mcp_tools}

    async def _ensure_session_coro(self, server_key: str) -> Any:
        """Connect the server once per run; later calls reuse the session."""
        existing = self._sessions.get(server_key)
        if existing is not None:
            return existing
        lock = self._session_locks.get(server_key)
        if lock is None:
            # All ensure coroutines run on the one session loop, so plain
            # dict mutation is serialized.
            lock = self._session_locks[server_key] = asyncio.Lock()
        async with lock:
            existing = self._sessions.get(server_key)
            if existing is not None:
                return existing
            parameters = self._servers[server_key]
            session, live_names = await self._connect_server(parameters)
            self._sessions[server_key] = session
            self._live_tool_names[server_key] = live_names
            return session

    async def _ensure_and_call_coro(self, server_key: str, wire_name: str, arguments: dict | None) -> Any:
        try:
            session = await asyncio.wait_for(
                self._ensure_session_coro(server_key),
                timeout=self.connect_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise MCPConnectionTimeoutError(
                f"MCP connection timed out after {self.connect_timeout_seconds:g} seconds"
            ) from exc
        live_names = self._live_tool_names.get(server_key)
        if live_names is not None and wire_name not in live_names:
            raise MCPToolNotFoundError(
                tool=wire_name, server=str(self._servers[server_key].get("url", "unknown"))
            )
        return await session.call_tool(wire_name, arguments)

    def call_tool(self, server_key: str, wire_name: str, arguments: dict | None = None) -> Any:
        """Run one MCP tool call, connecting to the server first if needed.

        Called from tool-execution lanes; the coroutine is bridged onto the
        dedicated session loop and tracked for cancellation on close.
        """
        with self._lock:
            loop = self._loop
        if loop is None or self._close_requested.is_set():
            raise RuntimeError("MCP session is closing")

        coroutine = self._ensure_and_call_coro(server_key, wire_name, arguments)
        try:
            call_future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except BaseException:
            coroutine.close()
            raise

        with self._active_calls_lock:
            self._active_calls.add(call_future)
        if self._close_requested.is_set():
            call_future.cancel()
        try:
            return call_future.result()
        finally:
            with self._active_calls_lock:
                self._active_calls.discard(call_future)

    def wrap_tool(self, tool: Any) -> Any:
        """Bound one tool's ``forward`` to a managed lane with a hard deadline."""
        original_forward = tool.forward
        task_name = f"mcp-tool-{getattr(tool, 'name', 'unknown')}"

        def managed_forward(
            *args,
            __forward=original_forward,
            __task_name=task_name,
            __tool_name=getattr(tool, "name", "unknown"),
            **kwargs,
        ):
            if self.cancellation_scope.cancelled:
                raise RuntimeError("MCP tool call cancelled")
            execution = self.manager.submit(
                "model-tool-io",
                ManagedTaskSpec(
                    task_name=__task_name,
                    owner="nexent.core.agents.resources.mcp",
                    close_hook=self.request_close,
                ),
                __forward,
                *args,
                **kwargs,
            )
            try:
                return execution.future.result(timeout=self.tool_timeout_seconds)
            except MCPConnectionTimeoutError:
                # Lazy connect failed inside the tool call. Since Python 3.11
                # FutureTimeoutError is an alias of the builtin TimeoutError,
                # so this subclass would otherwise be misreported as a tool
                # deadline; propagate the connection error unchanged.
                raise
            except FutureTimeoutError as exc:
                logger.warning(
                    "event=mcp_tool_timeout tool_name=%s timeout_seconds=%.3f execution_id=%s error_type=%s",
                    __tool_name,
                    self.tool_timeout_seconds,
                    execution.execution_id,
                    "TimeoutError",
                )
                self.request_close()
                self.manager.cancel(
                    execution.execution_id,
                    reason="MCP tool deadline exceeded",
                    wait_timeout=self.close_timeout_seconds,
                    mark_stuck_on_timeout=True,
                )
                raise MCPToolTimeoutError(
                    f"MCP tool request timed out after {self.tool_timeout_seconds:g} seconds"
                ) from exc

        tool.forward = managed_forward
        return tool

    # ------------------------------------------------------------------
    # Session loop lifecycle
    # ------------------------------------------------------------------

    async def _run_async_session(self) -> None:
        async with AsyncExitStack() as stack:
            # Sessions are entered lazily into this stack as tools connect;
            # the stack owns their teardown when the run closes.
            with self._lock:
                self._stack = stack
            close_event = asyncio.Event()
            with self._lock:
                self._async_close_event = close_event
            if self._close_requested.is_set():
                close_event.set()
            self._ready.set()
            await close_event.wait()

    def _run_session(self, cancel_event: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        session_task = loop.create_task(self._run_async_session())
        with self._lock:
            self._session_task = session_task
        try:
            loop.run_until_complete(session_task)
        except asyncio.CancelledError:
            if not self._close_requested.is_set() and not cancel_event.is_set():
                raise
        except BaseException as exc:
            with self._lock:
                if self._startup_error is None:
                    self._startup_error = exc
            raise
        finally:
            self._cancel_active_calls()
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            with self._lock:
                self._async_close_event = None
                self._session_task = None
                self._loop = None
                self._stack = None
                self._sessions.clear()
                self._live_tool_names.clear()
            loop.close()
            self._ready.set()

    def __enter__(self):
        self._scope_token = self.cancellation_scope.register_closer(self.request_close)
        try:
            self._execution = self.manager.submit(
                "mcp-session",
                ManagedTaskSpec(
                    task_name="mcp-session",
                    owner="nexent.core.agents.resources.mcp",
                    close_hook=self.request_close,
                    pass_cancel_event=True,
                ),
                self._run_session,
            )
        except BaseException:
            self.cancellation_scope.unregister_closer(self._scope_token)
            self._scope_token = None
            raise

        deadline = time.monotonic() + self.connect_timeout_seconds
        while not self._ready.wait(0.05):
            if self.cancellation_scope.cancelled:
                self.close()
                raise RuntimeError("MCP session startup cancelled")
            if time.monotonic() >= deadline:
                logger.warning(
                    "event=mcp_session_startup_timeout timeout_seconds=%.3f execution_id=%s error_type=%s",
                    self.connect_timeout_seconds,
                    self._execution.execution_id if self._execution is not None else "unknown",
                    "TimeoutError",
                )
                self.close()
                raise MCPConnectionTimeoutError(
                    f"MCP connection timed out after {self.connect_timeout_seconds:g} seconds"
                )

        with self._lock:
            startup_error = self._startup_error
        if startup_error is not None:
            self.close()
            raise startup_error
        return self

    def _cancel_active_calls(self) -> None:
        with self._active_calls_lock:
            active_calls = tuple(self._active_calls)
        for call_future in active_calls:
            call_future.cancel()

    def request_close(self) -> None:
        self._close_requested.set()
        self._cancel_active_calls()
        with self._lock:
            loop = self._loop
            close_event = self._async_close_event
            session_task = self._session_task
        if loop is not None:

            def request_async_close() -> None:
                if close_event is not None:
                    close_event.set()
                elif session_task is not None and not session_task.done():
                    session_task.cancel()

            try:
                loop.call_soon_threadsafe(request_async_close)
            except RuntimeError:
                pass
        execution = self._execution
        if execution is not None and not execution.future.done():
            self.manager.cancel(
                execution.execution_id,
                reason="MCP session close requested",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )

    def close(self) -> None:
        self.request_close()
        execution = self._execution
        if execution is not None and not execution.future.done():
            try:
                execution.future.result(timeout=self.close_timeout_seconds)
            except FutureTimeoutError:
                logger.warning(
                    "event=mcp_session_close_timeout timeout_seconds=%.3f execution_id=%s error_type=%s",
                    self.close_timeout_seconds,
                    execution.execution_id,
                    "TimeoutError",
                )
                self.manager.cancel(
                    execution.execution_id,
                    reason="MCP session close timed out",
                    wait_timeout=0,
                    mark_stuck_on_timeout=True,
                )
            except BaseException:
                pass
        if self._scope_token is not None:
            self.cancellation_scope.unregister_closer(self._scope_token)
            self._scope_token = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


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
        mcp_host_item: Either a string URL or a dict with 'url', optional 'name',
                       'transport', 'headers', 'authorization', or 'httpx_client_factory'

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

        # Server name enables tool->server routing for lazy connections.
        name = mcp_host_item.get("name")
        if name:
            result["name"] = str(name)

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


def _resolve_mcp_request_timeout_seconds(agent_run_info: AgentRunInfo) -> float:
    """Return a positive finite timeout for one MCP tool request."""
    timeout = getattr(agent_run_info, "mcp_request_timeout_seconds", None)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 10.0
    if not math.isfinite(timeout) or timeout <= 0:
        return 10.0
    return timeout
