from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable


class RunTerminated(BaseException):
    """Cooperative cancellation that must bypass ordinary action repair."""


@dataclass(frozen=True)
class ResourceToken:
    value: str


class _LinkedStopEvent(threading.Event):
    """Observe parent stops while keeping set/clear local to this invocation."""

    def __init__(self, parent: threading.Event):
        super().__init__()
        self._parent = parent

    def is_set(self) -> bool:
        return super().is_set() or self._parent.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            super().wait(0.05 if remaining is None else min(0.05, remaining))
        return True


class RunCancellationScope:
    """Thread-safe run cancellation with active resource close hooks."""

    def __init__(self, stop_event: threading.Event | None = None, *, parent_stop_event: threading.Event | None = None):
        self.stop_event = stop_event or (
            _LinkedStopEvent(parent_stop_event) if parent_stop_event is not None else threading.Event()
        )
        self._lock = threading.Lock()
        self._closers: dict[ResourceToken, Callable[[], None]] = {}
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        if self.stop_event.is_set():
            self.cancel()
        with self._lock:
            return self._cancelled

    def register_closer(self, close: Callable[[], None]) -> ResourceToken:
        if self.stop_event.is_set():
            self.cancel()
        token = ResourceToken(uuid.uuid4().hex)
        close_immediately = False
        with self._lock:
            if self._cancelled:
                close_immediately = True
            else:
                self._closers[token] = close
        if close_immediately:
            close()
        return token

    def unregister_closer(self, token: ResourceToken) -> None:
        with self._lock:
            self._closers.pop(token, None)

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self.stop_event.set()
            closers = tuple(self._closers.values())
            self._closers.clear()
        for close in closers:
            try:
                close()
            except Exception:
                continue
