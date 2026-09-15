from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ResourceToken:
    value: str


class RunCancellationScope:
    """Thread-safe run cancellation with active resource close hooks."""

    def __init__(self, stop_event: threading.Event | None = None):
        self.stop_event = stop_event or threading.Event()
        self._lock = threading.Lock()
        self._closers: dict[ResourceToken, Callable[[], None]] = {}
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def register_closer(self, close: Callable[[], None]) -> ResourceToken:
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
