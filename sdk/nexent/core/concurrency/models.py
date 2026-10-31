from __future__ import annotations

import threading
import time
import uuid
import weakref
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .errors import InvalidThreadPolicy


class ExecutionState(str, Enum):
    """Lifecycle states for one managed execution."""

    REGISTERED = "registered"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STUCK = "stuck"


class ManagerState(str, Enum):
    """Lifecycle states for one process-local thread manager."""

    CREATED = "created"
    RUNNING = "running"
    DRAINING = "draining"
    CLOSED = "closed"
    CLOSED_WITH_STUCK = "closed_with_stuck"


@dataclass(frozen=True)
class LanePolicy:
    """Capacity and shutdown policy for an isolated execution lane."""

    name: str
    max_workers: int
    max_queue_size: int
    queue_timeout_seconds: float | None = 0
    cancel_grace_seconds: float = 5.0
    shutdown_grace_seconds: float = 15.0

    def __post_init__(self):
        if not self.name:
            raise InvalidThreadPolicy("name must not be empty")
        if self.max_workers <= 0:
            raise InvalidThreadPolicy("max_workers must be greater than zero")
        if self.max_queue_size < 0:
            raise InvalidThreadPolicy("max_queue_size must be non-negative")
        if self.queue_timeout_seconds is not None and self.queue_timeout_seconds < 0:
            raise InvalidThreadPolicy("queue_timeout_seconds must be non-negative")
        if self.cancel_grace_seconds < 0:
            raise InvalidThreadPolicy("cancel_grace_seconds must be non-negative")
        if self.shutdown_grace_seconds <= 0:
            raise InvalidThreadPolicy("shutdown_grace_seconds must be greater than zero")


@dataclass(frozen=True)
class ManagedTaskSpec:
    """Ownership and cancellation metadata for one submitted task."""

    task_name: str
    owner: str
    run_id: str | None = None
    attempt_id: str | None = None
    deadline_monotonic: float | None = None
    close_hook: Callable[[], None] | None = None
    pass_cancel_event: bool = False

    def __post_init__(self):
        if not self.task_name:
            raise ValueError("task_name must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")


@dataclass(frozen=True)
class ManagedThreadSpec:
    """Ownership metadata for a dedicated long-lived service thread."""

    task_name: str
    owner: str
    lane: str = "background-service"
    close_hook: Callable[[], None] | None = None
    run_id: str | None = None
    attempt_id: str | None = None
    daemon: bool = False

    def __post_init__(self):
        if not self.task_name:
            raise ValueError("task_name must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.lane:
            raise ValueError("lane must not be empty")


@dataclass
class ManagedExecution:
    """Mutable internal handle for one managed task."""

    lane: str
    spec: ManagedTaskSpec
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: ExecutionState = ExecutionState.QUEUED
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    thread_ref: weakref.ReferenceType[threading.Thread] | None = None
    created_at_monotonic: float = field(default_factory=time.monotonic)
    started_at_monotonic: float | None = None
    finished_at_monotonic: float | None = None
    terminal_reason: str | None = None
    queue_deadline_monotonic: float | None = None
    started_event: threading.Event = field(default_factory=threading.Event)
    _queue_timeout_requested: bool = False
    _close_called: bool = False


@dataclass(frozen=True)
class CancelResult:
    """Observable result of a cancellation request."""

    execution_id: str
    cancelled: bool
    stuck: bool = False
    already_terminal: bool = False


@dataclass(frozen=True)
class DrainResult:
    """Result of draining or shutting down a manager."""

    stuck_execution_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LaneSnapshot:
    """Capacity and current use for one execution lane."""

    name: str
    max_workers: int
    max_queue_size: int
    capacity: int
    active_count: int
    queued_count: int
    running_count: int
    dedicated_count: int
    available_count: int


@dataclass(frozen=True)
class ExecutionSnapshot:
    """Current identity and liveness of one managed execution."""

    execution_id: str
    lane: str
    task_name: str
    owner: str
    state: ExecutionState
    run_id: str | None
    attempt_id: str | None
    dedicated: bool
    thread_name: str | None
    thread_alive: bool
    age_seconds: float


@dataclass(frozen=True)
class ThreadManagerSnapshot:
    """Immutable aggregate state safe for health and diagnostics endpoints."""

    service_name: str
    state: ManagerState
    active_count: int
    queued_count: int
    running_count: int
    stuck_count: int
    completed_count: int
    rejected_count: int
    active_execution_ids: tuple[str, ...]
    python_active_thread_count: int
    lanes: tuple[LaneSnapshot, ...]
    executions: tuple[ExecutionSnapshot, ...]
