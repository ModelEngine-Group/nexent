from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class ModelConcurrencyExceeded(TimeoutError):
    """Raised when a model concurrency permit is unavailable before deadline."""


@dataclass
class _LimiterEntry:
    limit: int
    semaphore: threading.BoundedSemaphore
    references: int = 0


class ModelConcurrencyPermit:
    def __init__(self, limiter: "ModelConcurrencyLimiter", key: tuple[str, str, str], entry: _LimiterEntry):
        self._limiter = limiter
        self._key = key
        self._entry = entry
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._entry.semaphore.release()
        self._limiter._release_reference(self._key, self._entry)


class ModelConcurrencyLimiter:
    """Process-local concurrency limits shared by tenant/provider/model key."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, str], _LimiterEntry] = {}

    def acquire(
        self,
        key: tuple[str, str, str],
        limit: int,
        timeout_seconds: float,
        stop_event: threading.Event,
    ) -> ModelConcurrencyPermit:
        if limit <= 0:
            raise ValueError("model concurrency limit must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("model concurrency wait timeout must be greater than zero")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LimiterEntry(limit, threading.BoundedSemaphore(limit))
                self._entries[key] = entry
            elif entry.limit != limit:
                raise ValueError("conflicting concurrency limits for the same model key")
            entry.references += 1

        deadline = time.monotonic() + timeout_seconds
        try:
            while not stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelConcurrencyExceeded(
                        f"model concurrency permit timed out after {timeout_seconds:.3f} seconds"
                    )
                if entry.semaphore.acquire(timeout=min(0.05, remaining)):
                    return ModelConcurrencyPermit(self, key, entry)
            raise RuntimeError("model concurrency wait cancelled")
        except BaseException:
            self._release_reference(key, entry)
            raise

    def _release_reference(self, key: tuple[str, str, str], entry: _LimiterEntry) -> None:
        with self._lock:
            entry.references -= 1
            if entry.references == 0 and self._entries.get(key) is entry:
                self._entries.pop(key, None)


model_concurrency_limiter = ModelConcurrencyLimiter()
