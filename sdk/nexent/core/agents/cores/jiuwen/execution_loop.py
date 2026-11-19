# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own Jiuwen's process-global async state on one managed service loop."""

import asyncio
import logging
import threading
from concurrent.futures import CancelledError
from contextvars import Context
from dataclasses import dataclass

from nexent.core.concurrency import ManagedThreadSpec
from nexent.core.concurrency.cancellation import RunTerminated


logger = logging.getLogger(__name__)
_owner_lock = threading.RLock()
_owner = None


@dataclass
class _Outcome:
    value: object = None
    error: BaseException | None = None


class JiuwenExecutionLoop:
    """A process service, not a lock around individual Agent executions.

    Request and collaboration admission remains owned by the caller's managed
    lanes. Every submitted invocation keeps its context, task and cancel scope.
    Only application/manager shutdown stops the shared native Runner.
    """

    def __init__(self, manager):
        self.manager = manager
        self.loop = None
        self._stop = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._closing = False
        self._tasks = {}
        self._failure = None
        self.execution = manager.register_service(
            ManagedThreadSpec(task_name="jiuwen-execution-loop", owner=__name__,
                              lane="background-service", close_hook=self.stop),
            self._serve,
        )
        try:
            # The process service must not retain the first caller's identity or
            # observer context; run_coroutine_threadsafe copies each caller later.
            Context().run(manager.start_service, self.execution.execution_id)
        except BaseException:
            manager.cancel(self.execution.execution_id, reason="Jiuwen loop startup failed", wait_timeout=0)
            raise

    def stop(self):
        with self._lock:
            self._closing = True
            if self.loop is not None and self._stop is not None and not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self._stop.set)

    def _serve(self, cancel_event):
        try:
            asyncio.run(self._serve_async(cancel_event))
        except BaseException as error:
            self._failure = error
            raise
        finally:
            with self._lock:
                self._closing = True
            self._ready.set()

    async def _serve_async(self, cancel_event):
        with self._lock:
            self.loop = asyncio.get_running_loop()
            self._stop = asyncio.Event()
            if self._closing or cancel_event.is_set():
                self._stop.set()
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            # Each invocation releases its own session before Runner-wide shutdown.
            tasks = tuple(self._tasks.items())
            for task, cancel in tasks:
                if cancel is not None:
                    try:
                        cancel()
                    except Exception as error:
                        logger.warning("Jiuwen shutdown cancel callback failed: %s", type(error).__name__)
                task.cancel()
            if tasks:
                await asyncio.gather(*(task for task, _ in tasks), return_exceptions=True)
            from openjiuwen.core.runner import Runner

            await Runner.stop()

    async def _execute(self, factory, cancel):
        task = asyncio.current_task()
        self._tasks[task] = cancel
        try:
            return _Outcome(value=await factory())
        except BaseException as error:
            # Preserve terminal clarification (a CancelledError subclass) and wait
            # for coroutine cleanup instead of cancelling the bridge Future early.
            return _Outcome(error=error)
        finally:
            self._tasks.pop(task, None)

    def run(self, factory, *, cancel=None):
        if not self._ready.wait(10):
            self.manager.cancel(self.execution.execution_id, reason="Jiuwen loop startup timed out", wait_timeout=1)
            raise TimeoutError("Jiuwen execution loop did not start")
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if self.loop is not None and current is self.loop:
            raise RuntimeError("A synchronous Jiuwen invocation cannot block its own execution loop")
        with self._lock:
            if self._closing or self.execution.future.done():
                raise RunTerminated("Jiuwen execution service is stopping") from self._failure
            coroutine = self._execute(factory, cancel)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except BaseException:
                coroutine.close()
                raise
        try:
            outcome = future.result()
        except CancelledError:
            raise asyncio.CancelledError() from None
        if outcome.error is not None:
            raise outcome.error
        return outcome.value


def get_execution_loop(manager):
    """Use one Runner owner across concurrent callers in this process."""
    global _owner
    with _owner_lock:
        if _owner is None or _owner.execution.future.done():
            _owner = JiuwenExecutionLoop(manager)
        return _owner
