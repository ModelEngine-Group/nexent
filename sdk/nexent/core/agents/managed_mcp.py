from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from typing import Any, Callable

from ..concurrency import ManagedExecution, ManagedTaskSpec, RunCancellationScope, ThreadManager


logger = logging.getLogger("managed_mcp")


class ManagedMCPToolCollection:
    """Own one MCP ToolCollection context through bounded manager executions."""

    def __init__(
        self,
        *,
        manager: ThreadManager,
        server_parameters: list[dict[str, Any]],
        cancellation_scope: RunCancellationScope,
        tool_timeout_seconds: float,
        close_timeout_seconds: float,
        connect_timeout_seconds: float = 30.0,
        session_context_factory: Callable[..., Any] | None = None,
        tool_adapter_factory: Callable[[], Any] | None = None,
    ):
        if tool_timeout_seconds <= 0:
            raise ValueError("MCP tool timeout must be greater than zero")
        if close_timeout_seconds <= 0:
            raise ValueError("MCP close timeout must be greater than zero")
        if connect_timeout_seconds <= 0:
            raise ValueError("MCP connect timeout must be greater than zero")
        self.manager = manager
        self.server_parameters = server_parameters
        self.cancellation_scope = cancellation_scope
        self.tool_timeout_seconds = tool_timeout_seconds
        self.close_timeout_seconds = close_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._session_context_factory = session_context_factory
        self._tool_adapter_factory = tool_adapter_factory
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
        self._startup_error: BaseException | None = None
        self._public_collection = None
        self.tools: list[Any] = []

    def _session_factory(self):
        if self._session_context_factory is not None:
            return self._session_context_factory
        from mcpadapt.core import mcptools

        return mcptools

    def _adapter_factory(self):
        if self._tool_adapter_factory is not None:
            return self._tool_adapter_factory
        from mcpadapt.smolagents_adapter import SmolAgentsAdapter

        return lambda: SmolAgentsAdapter(structured_output=False)

    def _call_tool(self, session: Any, name: str, arguments: dict | None = None) -> Any:
        with self._lock:
            loop = self._loop
        if loop is None or self._close_requested.is_set():
            raise RuntimeError("MCP session is closing")

        coroutine = session.call_tool(name, arguments)
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

    def _cancel_active_calls(self) -> None:
        with self._active_calls_lock:
            active_calls = tuple(self._active_calls)
        for call_future in active_calls:
            call_future.cancel()

    async def _run_async_session(self) -> None:
        from smolagents import ToolCollection

        session_factory = self._session_factory()
        adapter = self._adapter_factory()()
        async with AsyncExitStack() as stack:
            connections = []
            for parameters in self.server_parameters:
                connection = await stack.enter_async_context(
                    session_factory(
                        parameters,
                        client_session_timeout_seconds=None,
                    )
                )
                connections.append(connection)

            tools = []
            for session, mcp_tools in connections:
                for mcp_tool in mcp_tools:

                    def call_tool(
                        arguments=None,
                        __session=session,
                        __name=mcp_tool.name,
                    ):
                        return self._call_tool(__session, __name, arguments)

                    tools.append(adapter.adapt(call_tool, mcp_tool))

            close_event = asyncio.Event()
            with self._lock:
                self._async_close_event = close_event
                self.tools = self._wrap_tools(tools)
                self._public_collection = ToolCollection(self.tools)
            if self._close_requested.is_set():
                close_event.set()
            self._ready.set()
            await close_event.wait()

    def _wrap_tools(self, tools: list[Any]) -> list[Any]:
        for tool in tools:
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
                        owner="nexent.core.agents.managed_mcp",
                        close_hook=self.request_close,
                    ),
                    __forward,
                    *args,
                    **kwargs,
                )
                try:
                    return execution.future.result(timeout=self.tool_timeout_seconds)
                except FutureTimeoutError:
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
                    raise

            tool.forward = managed_forward
        return tools

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
            loop.close()
            self._ready.set()

    def __enter__(self):
        self._scope_token = self.cancellation_scope.register_closer(self.request_close)
        try:
            self._execution = self.manager.submit(
                "mcp-session",
                ManagedTaskSpec(
                    task_name="mcp-session",
                    owner="nexent.core.agents.managed_mcp",
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
                raise TimeoutError("MCP session startup timed out")

        with self._lock:
            startup_error = self._startup_error
        if startup_error is not None:
            self.close()
            raise startup_error
        return self._public_collection

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
