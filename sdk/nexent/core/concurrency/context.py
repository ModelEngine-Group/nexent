import threading
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .manager import ThreadManager


_current_thread_manager: ContextVar["ThreadManager | None"] = ContextVar(
    "nexent_current_thread_manager",
    default=None,
)
_default_thread_manager: "ThreadManager | None" = None
_default_lock = threading.Lock()


def get_current_thread_manager() -> "ThreadManager | None":
    """Return the manager attached to the current managed execution context."""
    return _current_thread_manager.get()


def get_default_thread_manager() -> "ThreadManager | None":
    """Return the process manager installed by the service lifespan."""
    with _default_lock:
        return _default_thread_manager


def set_default_thread_manager(manager: "ThreadManager") -> None:
    """Install the single process-wide fallback used outside task contexts."""
    global _default_thread_manager
    with _default_lock:
        _default_thread_manager = manager


def clear_default_thread_manager(manager: "ThreadManager") -> None:
    """Clear the fallback only when it still points at the closing manager."""
    global _default_thread_manager
    with _default_lock:
        if _default_thread_manager is manager:
            _default_thread_manager = None


def _set_current_thread_manager(manager: "ThreadManager") -> Token:
    return _current_thread_manager.set(manager)


def _reset_current_thread_manager(token: Token) -> None:
    _current_thread_manager.reset(token)
