from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import weakref
from concurrent.futures import CancelledError, Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import copy_context
from typing import Callable, Mapping

from .bounded_executor import BoundedExecutor
from .context import _reset_current_thread_manager, _set_current_thread_manager
from .errors import (
    ThreadCapacityExceeded,
    ThreadManagerDraining,
    ThreadManagerNotRunning,
    ThreadQueueTimedOut,
)
from .metrics import ThreadMetrics
from .models import (
    CancelResult,
    DrainResult,
    ExecutionSnapshot,
    ExecutionState,
    LanePolicy,
    LaneSnapshot,
    ManagedExecution,
    ManagedTaskSpec,
    ManagedThreadSpec,
    ManagerState,
    ThreadManagerSnapshot,
)
from .telemetry import get_thread_telemetry


logger = logging.getLogger("thread_manager")

_TERMINAL_STATES = {
    ExecutionState.SUCCEEDED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
    ExecutionState.TIMED_OUT,
}


def _structured_event(
    event: str,
    service: str,
    *,
    execution: ManagedExecution | None = None,
    counts: tuple[int, int, int, int] | None = None,
    **fields,
) -> str:
    payload = {
        "event": event,
        "component": "thread_manager",
        "service": service,
    }
    if execution is not None:
        payload["execution"] = {
            "execution_id": execution.execution_id,
            "lane": execution.lane,
            "task_name": execution.spec.task_name,
            "owner": execution.spec.owner,
            "run_id": execution.spec.run_id,
            "attempt_id": execution.spec.attempt_id,
            "state": execution.state.value,
        }
    if counts is not None:
        payload["counts"] = {
            "managed_active": counts[0],
            "queued": counts[1],
            "running": counts[2],
            "stuck": counts[3],
            "python_active_threads": threading.active_count(),
        }
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class ThreadManager:
    """Own bounded thread execution for one service process."""

    def __init__(
        self,
        service_name: str,
        lane_policies: Mapping[str, LanePolicy],
        telemetry=None,
    ):
        if not service_name:
            raise ValueError("service_name must not be empty")
        if not lane_policies:
            raise ValueError("lane_policies must not be empty")
        if set(lane_policies) != {policy.name for policy in lane_policies.values()}:
            raise ValueError("lane policy keys must match policy names")
        self.service_name = service_name
        self._policies = dict(lane_policies)
        self._executors: dict[str, BoundedExecutor] = {}
        self._executions: dict[str, ManagedExecution] = {}
        self._registered_services: dict[str, tuple[Callable, tuple, dict, bool]] = {}
        self._dedicated_execution_ids: set[str] = set()
        self._completed_count = 0
        self._rejected_count = 0
        self._metrics = ThreadMetrics()
        self._telemetry = telemetry or get_thread_telemetry()
        self._lock = threading.RLock()
        self.state = ManagerState.CREATED

    def start(self):
        with self._lock:
            if self.state is ManagerState.RUNNING:
                return
            if self.state is not ManagerState.CREATED:
                raise ThreadManagerNotRunning(f"Thread manager cannot start from state {self.state.value}")
            self._executors = {
                name: BoundedExecutor(self.service_name, policy) for name, policy in self._policies.items()
            }
            self.state = ManagerState.RUNNING

    def submit(
        self,
        lane: str,
        spec: ManagedTaskSpec,
        fn: Callable,
        *args,
        **kwargs,
    ) -> ManagedExecution:
        with self._lock:
            self._ensure_accepting_work()
            executor = self._executors.get(lane)
            if executor is None:
                raise KeyError(f"Unknown thread lane '{lane}'")
            execution = ManagedExecution(lane=lane, spec=spec)
            if executor.policy.queue_timeout_seconds is not None:
                execution.queue_deadline_monotonic = (
                    execution.created_at_monotonic
                    + executor.policy.queue_timeout_seconds
                )
            self._executions[execution.execution_id] = execution
            counts = self._lifecycle_counts_locked()

        self._record_execution_telemetry(
            execution,
            "thread.queued",
            counts,
            dedicated=False,
        )

        context = copy_context()
        try:
            future = executor.submit(
                context.run,
                self._execute,
                execution,
                fn,
                args,
                kwargs,
            )
        except ThreadCapacityExceeded:
            with self._lock:
                self._executions.pop(execution.execution_id, None)
                self._rejected_count += 1
                counts = self._lifecycle_counts_locked()
            self._metrics.rejected(lane, spec.task_name)
            execution.finished_at_monotonic = time.monotonic()
            self._record_execution_telemetry(
                execution,
                "thread.rejected",
                counts,
                result="rejected",
                dedicated=False,
            )
            logger.warning(
                _structured_event(
                    "thread_task_rejected",
                    self.service_name,
                    execution=execution,
                    counts=counts,
                    reason="capacity",
                )
            )
            raise
        except BaseException:
            with self._lock:
                self._executions.pop(execution.execution_id, None)
                counts = self._lifecycle_counts_locked()
            execution.finished_at_monotonic = time.monotonic()
            self._record_execution_telemetry(
                execution,
                "thread.submit_failed",
                counts,
                result="submit_failed",
                dedicated=False,
            )
            raise

        execution.future = future
        self._metrics.queued(lane, spec.task_name)
        future.add_done_callback(lambda completed_future: self._handle_future_done(execution, completed_future))
        return execution

    async def wait_until_started(self, execution: ManagedExecution) -> ManagedExecution:
        """Wait for a queued execution to start or atomically expire its queue deadline."""
        timeout = self._policies[execution.lane].queue_timeout_seconds
        while True:
            with self._lock:
                if execution.started_event.is_set() or execution.state in {
                    ExecutionState.STARTING,
                    ExecutionState.RUNNING,
                    ExecutionState.STOP_REQUESTED,
                    ExecutionState.SUCCEEDED,
                }:
                    return execution
                future = execution.future
                if execution.state is ExecutionState.TIMED_OUT:
                    raise ThreadQueueTimedOut(execution.lane, timeout or 0)
                if execution.state in _TERMINAL_STATES:
                    raise CancelledError(
                        f"Execution {execution.execution_id} ended before starting"
                    )
                deadline = execution.queue_deadline_monotonic

            if deadline is None:
                await asyncio.sleep(0.01)
                continue

            remaining = deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(0.01, remaining))
                continue

            with self._lock:
                if execution.started_event.is_set() or execution.state is not ExecutionState.QUEUED:
                    continue
                execution._queue_timeout_requested = True
                execution.terminal_reason = "queue deadline exceeded before start"
                if future is not None and future.cancel():
                    raise ThreadQueueTimedOut(execution.lane, timeout or 0)
                execution._queue_timeout_requested = False

    def register_service(
        self,
        spec: ManagedThreadSpec,
        fn: Callable,
        *args,
        **kwargs,
    ) -> ManagedExecution:
        """Register a dedicated service thread without starting it."""
        with self._lock:
            self._ensure_accepting_work()
            if spec.lane not in self._policies:
                raise KeyError(f"Unknown thread lane '{spec.lane}'")
            dedicated_count = sum(
                self._executions[execution_id].lane == spec.lane
                for execution_id in self._dedicated_execution_ids
                if execution_id in self._executions
            )
            policy = self._policies[spec.lane]
            if dedicated_count >= policy.max_workers:
                self._rejected_count += 1
                self._metrics.rejected(spec.lane, spec.task_name)
                raise ThreadCapacityExceeded(
                    lane=spec.lane,
                    capacity=policy.max_workers,
                    queued=0,
                )
            task_spec = ManagedTaskSpec(
                task_name=spec.task_name,
                owner=spec.owner,
                run_id=spec.run_id,
                attempt_id=spec.attempt_id,
                close_hook=spec.close_hook,
                pass_cancel_event=True,
            )
            execution = ManagedExecution(
                lane=spec.lane,
                spec=task_spec,
                state=ExecutionState.REGISTERED,
            )
            self._executions[execution.execution_id] = execution
            self._dedicated_execution_ids.add(execution.execution_id)
            self._registered_services[execution.execution_id] = (
                fn,
                args,
                kwargs,
                spec.daemon,
            )
            counts = self._lifecycle_counts_locked()
        self._record_execution_telemetry(
            execution,
            "thread.registered",
            counts,
            dedicated=True,
        )
        return execution

    def start_service(self, execution_id: str) -> ManagedExecution:
        """Start one previously registered dedicated service thread."""
        with self._lock:
            self._ensure_accepting_work()
            execution = self._executions.get(execution_id)
            target = self._registered_services.get(execution_id)
            if execution is None or target is None:
                raise KeyError(f"Unknown registered service '{execution_id}'")
            if execution.state is not ExecutionState.REGISTERED:
                raise RuntimeError(f"Registered service '{execution_id}' is {execution.state.value}")
            fn, args, kwargs, daemon = target
            future = Future()
            execution.future = future
            context = copy_context()
            thread = threading.Thread(
                target=self._run_dedicated,
                args=(context, execution, future, fn, args, kwargs),
                name=f"nexent-{self.service_name}-{execution.spec.task_name}",
                daemon=daemon,
            )
            execution.thread_ref = weakref.ref(thread)
            execution.state = ExecutionState.STARTING
            thread.start()
            return execution

    async def run(
        self,
        lane: str,
        spec: ManagedTaskSpec,
        fn: Callable,
        *args,
        **kwargs,
    ):
        execution = self.submit(lane, spec, fn, *args, **kwargs)
        try:
            return await asyncio.wrap_future(execution.future)
        except asyncio.CancelledError:
            self.cancel(
                execution.execution_id,
                reason="async caller cancelled",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
            raise

    def run_sync(
        self,
        lane: str,
        spec: ManagedTaskSpec,
        fn: Callable,
        *args,
        timeout: float | None = None,
        **kwargs,
    ):
        """Run blocking nested work on a named lane and wait for its result."""
        execution = self.submit(lane, spec, fn, *args, **kwargs)
        try:
            return execution.future.result(timeout=timeout)
        except FutureTimeoutError:
            with self._lock:
                if execution.execution_id in self._executions:
                    execution.state = ExecutionState.TIMED_OUT
                    execution.terminal_reason = "synchronous caller deadline exceeded"
            self.cancel(
                execution.execution_id,
                reason="synchronous caller deadline exceeded",
                wait_timeout=0,
            )
            raise

    def cancel(
        self,
        execution_id: str,
        reason: str,
        wait_timeout: float | None = None,
        mark_stuck_on_timeout: bool = True,
    ) -> CancelResult:
        with self._lock:
            execution = self._executions.get(execution_id)
            if execution is None:
                return CancelResult(
                    execution_id=execution_id,
                    cancelled=False,
                    already_terminal=True,
                )
            future = execution.future
            if future is None and execution.state is ExecutionState.REGISTERED:
                execution.cancel_event.set()
                execution.state = ExecutionState.CANCELLED
                execution.terminal_reason = reason
                execution.finished_at_monotonic = time.monotonic()
                self._registered_services.pop(execution.execution_id, None)
                self._finalize_execution_locked(execution)
                return CancelResult(execution_id=execution_id, cancelled=True)
            if future is not None and future.cancel():
                execution.state = ExecutionState.CANCELLED
                execution.terminal_reason = reason
                execution.finished_at_monotonic = time.monotonic()
                self._finalize_execution_locked(execution)
                return CancelResult(execution_id=execution_id, cancelled=True)

            execution.cancel_event.set()
            stop_requested = False
            if execution.state not in _TERMINAL_STATES:
                execution.state = ExecutionState.STOP_REQUESTED
                execution.terminal_reason = reason
                stop_requested = True
                counts = self._lifecycle_counts_locked()
            close_hook = None
            if execution.spec.close_hook is not None and not execution._close_called:
                execution._close_called = True
                close_hook = execution.spec.close_hook

        if stop_requested:
            self._record_execution_telemetry(
                execution,
                "thread.cancel_requested",
                counts,
                reason=reason,
            )

        if close_hook is not None:
            try:
                close_hook()
            except Exception as exc:
                logger.error(
                    _structured_event(
                        "thread_close_hook_failed",
                        self.service_name,
                        execution=execution,
                        error={"type": type(exc).__name__},
                    )
                )

        policy_timeout = self._policies[execution.lane].cancel_grace_seconds
        timeout = policy_timeout if wait_timeout is None else min(policy_timeout, max(0, wait_timeout))
        if future is not None:
            try:
                future.result(timeout=timeout)
            except (CancelledError, FutureTimeoutError):
                pass
            except BaseException:
                pass

        with self._lock:
            if execution.execution_id not in self._executions:
                return CancelResult(execution_id=execution_id, cancelled=True)
            if future is not None and not future.done():
                if not mark_stuck_on_timeout:
                    return CancelResult(
                        execution_id=execution_id,
                        cancelled=False,
                    )
                was_stuck = execution.state is ExecutionState.STUCK
                execution.state = ExecutionState.STUCK
                if not was_stuck:
                    self._metrics.stuck(execution)
                counts = self._lifecycle_counts_locked()
                self._record_execution_telemetry(
                    execution,
                    "thread.stuck",
                    counts,
                    result="stuck",
                )
                logger.error(
                    _structured_event(
                        "thread_task_stuck",
                        self.service_name,
                        execution=execution,
                        counts=counts,
                    )
                )
                return CancelResult(
                    execution_id=execution_id,
                    cancelled=False,
                    stuck=True,
                )
            return CancelResult(execution_id=execution_id, cancelled=True)

    async def drain(self, timeout: float) -> DrainResult:
        deadline = time.monotonic() + max(0, timeout)
        with self._lock:
            if self.state in {ManagerState.CLOSED, ManagerState.CLOSED_WITH_STUCK}:
                return DrainResult(self._stuck_ids_locked())
            if self.state is ManagerState.CREATED:
                self.state = ManagerState.DRAINING
                return DrainResult()
            self.state = ManagerState.DRAINING
            queued_ids = tuple(
                execution.execution_id
                for execution in self._executions.values()
                if execution.state is ExecutionState.QUEUED
            )
            running_ids = tuple(
                execution.execution_id
                for execution in self._executions.values()
                if execution.state is not ExecutionState.QUEUED
            )
            execution_ids = queued_ids + running_ids

        for execution_id in execution_ids:
            remaining = max(0, deadline - time.monotonic())
            self.cancel(execution_id, reason="manager draining", wait_timeout=remaining)
            await asyncio.sleep(0)
        with self._lock:
            return DrainResult(self._stuck_ids_locked())

    async def shutdown(self, timeout: float) -> DrainResult:
        with self._lock:
            if self.state in {ManagerState.CLOSED, ManagerState.CLOSED_WITH_STUCK}:
                return DrainResult(self._stuck_ids_locked())
        result = await self.drain(timeout)
        with self._lock:
            executors = tuple(self._executors.values())
            self._executors = {}
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            stuck = self._stuck_ids_locked()
            self.state = ManagerState.CLOSED_WITH_STUCK if stuck else ManagerState.CLOSED
        return DrainResult(stuck_execution_ids=stuck or result.stuck_execution_ids)

    def snapshot(self) -> ThreadManagerSnapshot:
        with self._lock:
            executions = tuple(self._executions.values())
            lane_snapshots = []
            for lane, policy in self._policies.items():
                lane_executions = tuple(item for item in executions if item.lane == lane)
                dedicated_count = sum(item.execution_id in self._dedicated_execution_ids for item in lane_executions)
                executor = self._executors.get(lane)
                submitted_count = executor.submitted if executor is not None else 0
                capacity = policy.max_workers + policy.max_queue_size
                lane_snapshots.append(
                    LaneSnapshot(
                        name=lane,
                        max_workers=policy.max_workers,
                        max_queue_size=policy.max_queue_size,
                        capacity=capacity,
                        active_count=len(lane_executions),
                        queued_count=sum(item.state is ExecutionState.QUEUED for item in lane_executions),
                        running_count=sum(
                            item.state
                            in {
                                ExecutionState.STARTING,
                                ExecutionState.RUNNING,
                                ExecutionState.STOP_REQUESTED,
                            }
                            for item in lane_executions
                        ),
                        dedicated_count=dedicated_count,
                        available_count=max(0, capacity - submitted_count - dedicated_count),
                    )
                )
            return ThreadManagerSnapshot(
                service_name=self.service_name,
                state=self.state,
                active_count=len(executions),
                queued_count=sum(item.state is ExecutionState.QUEUED for item in executions),
                running_count=sum(
                    item.state
                    in {
                        ExecutionState.STARTING,
                        ExecutionState.RUNNING,
                        ExecutionState.STOP_REQUESTED,
                    }
                    for item in executions
                ),
                stuck_count=sum(item.state is ExecutionState.STUCK for item in executions),
                completed_count=self._completed_count,
                rejected_count=self._rejected_count,
                active_execution_ids=tuple(item.execution_id for item in executions),
                python_active_thread_count=threading.active_count(),
                lanes=tuple(lane_snapshots),
                executions=tuple(
                    self._execution_snapshot_locked(item)
                    for item in executions
                ),
            )

    def metrics_snapshot(self):
        """Return stable-label counters and aggregate durations."""
        return self._metrics.snapshot()

    def _execute(self, execution, fn, args, kwargs):
        with self._lock:
            execution.state = ExecutionState.STARTING
            execution.started_at_monotonic = time.monotonic()
            execution.thread_ref = weakref.ref(threading.current_thread())
            execution.started_event.set()
            execution.state = ExecutionState.RUNNING
            counts = self._lifecycle_counts_locked()
        self._metrics.started(execution)
        self._record_execution_telemetry(
            execution,
            "thread.started",
            counts,
        )
        context_token = _set_current_thread_manager(self)
        try:
            if execution.spec.deadline_monotonic is not None and time.monotonic() >= execution.spec.deadline_monotonic:
                with self._lock:
                    execution.state = ExecutionState.TIMED_OUT
                    execution.terminal_reason = "task deadline expired before start"
                raise FutureTimeoutError("task deadline expired before start")
            if execution.spec.pass_cancel_event:
                result = fn(execution.cancel_event, *args, **kwargs)
            else:
                result = fn(*args, **kwargs)
        except BaseException:
            with self._lock:
                if execution.state is not ExecutionState.TIMED_OUT:
                    execution.state = (
                        ExecutionState.CANCELLED if execution.cancel_event.is_set() else ExecutionState.FAILED
                    )
            raise
        else:
            with self._lock:
                if execution.state is not ExecutionState.TIMED_OUT:
                    execution.state = (
                        ExecutionState.CANCELLED if execution.cancel_event.is_set() else ExecutionState.SUCCEEDED
                    )
            return result
        finally:
            _reset_current_thread_manager(context_token)
            with self._lock:
                execution.finished_at_monotonic = time.monotonic()
                self._finalize_execution_locked(execution)

    def _run_dedicated(self, context, execution, future, fn, args, kwargs):
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = context.run(self._execute, execution, fn, args, kwargs)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)
        finally:
            with self._lock:
                self._registered_services.pop(execution.execution_id, None)

    def _handle_future_done(self, execution, future):
        if not future.cancelled():
            return
        with self._lock:
            if execution.execution_id not in self._executions:
                return
            execution.state = (
                ExecutionState.TIMED_OUT
                if execution._queue_timeout_requested
                else ExecutionState.CANCELLED
            )
            execution.finished_at_monotonic = time.monotonic()
            self._finalize_execution_locked(execution)

    def _finalize_execution_locked(self, execution):
        current = self._executions.get(execution.execution_id)
        if current is not execution:
            return
        if execution.state is ExecutionState.STUCK:
            return
        was_dedicated = execution.execution_id in self._dedicated_execution_ids
        self._executions.pop(execution.execution_id, None)
        self._dedicated_execution_ids.discard(execution.execution_id)
        self._completed_count += 1
        self._metrics.finished(execution)
        counts = self._lifecycle_counts_locked()
        self._record_execution_telemetry(
            execution,
            "thread.finished",
            counts,
            result=execution.state.value,
            dedicated=was_dedicated,
        )

    def _record_execution_telemetry(
        self,
        execution,
        event,
        counts,
        *,
        dedicated=None,
        **fields,
    ):
        if dedicated is None:
            dedicated = execution.execution_id in self._dedicated_execution_ids
        try:
            self._telemetry.record_snapshot(
                self.service_name,
                event,
                execution,
                counts,
                dedicated=dedicated,
                **fields,
            )
        except Exception:
            return

    def _execution_snapshot_locked(self, execution):
        thread = execution.thread_ref() if execution.thread_ref is not None else None
        return ExecutionSnapshot(
            execution_id=execution.execution_id,
            lane=execution.lane,
            task_name=execution.spec.task_name,
            owner=execution.spec.owner,
            state=execution.state,
            run_id=execution.spec.run_id,
            attempt_id=execution.spec.attempt_id,
            dedicated=execution.execution_id in self._dedicated_execution_ids,
            thread_name=thread.name if thread is not None else None,
            thread_alive=thread.is_alive() if thread is not None else False,
            age_seconds=max(0.0, time.monotonic() - execution.created_at_monotonic),
        )

    def _lifecycle_counts_locked(self) -> tuple[int, int, int, int]:
        executions = tuple(self._executions.values())
        return (
            len(executions),
            sum(item.state is ExecutionState.QUEUED for item in executions),
            sum(
                item.state
                in {
                    ExecutionState.STARTING,
                    ExecutionState.RUNNING,
                    ExecutionState.STOP_REQUESTED,
                }
                for item in executions
            ),
            sum(item.state is ExecutionState.STUCK for item in executions),
        )

    def _ensure_accepting_work(self):
        if self.state is ManagerState.DRAINING:
            raise ThreadManagerDraining(f"Thread manager for {self.service_name} is draining")
        if self.state is not ManagerState.RUNNING:
            raise ThreadManagerNotRunning(f"Thread manager for {self.service_name} is {self.state.value}")

    def _stuck_ids_locked(self) -> tuple[str, ...]:
        return tuple(
            execution.execution_id
            for execution in self._executions.values()
            if execution.state is ExecutionState.STUCK
        )
