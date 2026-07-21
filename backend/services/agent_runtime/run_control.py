"""Conversation-to-runtime run lookup used by the existing stop endpoint."""

from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class RuntimeRunHandle:
    """One active provider run addressable by conversation and user."""

    run_id: str
    conversation_id: int
    user_id: str
    runtime: Any


class RuntimeRunControlRegistry:
    """Track active runs without introducing a second cancel endpoint."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[int, str], RuntimeRunHandle] = {}
        self._lock = RLock()

    def register(self, handle: RuntimeRunHandle) -> None:
        with self._lock:
            self._by_key[(handle.conversation_id, handle.user_id)] = handle

    def unregister(self, *, run_id: str, conversation_id: int, user_id: str) -> None:
        key = (conversation_id, user_id)
        with self._lock:
            current = self._by_key.get(key)
            if current is not None and current.run_id == run_id:
                self._by_key.pop(key, None)

    def request_stop(self, *, conversation_id: int, user_id: str) -> bool:
        with self._lock:
            handle = self._by_key.get((conversation_id, user_id))
        return bool(handle and handle.runtime.request_stop(handle.run_id))


runtime_run_control_registry = RuntimeRunControlRegistry()


__all__ = [
    "RuntimeRunControlRegistry",
    "RuntimeRunHandle",
    "runtime_run_control_registry",
]
