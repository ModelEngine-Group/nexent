from __future__ import annotations

import threading
from typing import Callable

from .context import get_current_thread_manager, get_default_thread_manager
from .models import LanePolicy, ManagedTaskSpec


_fallback_lock = threading.Lock()
_fallback_thread_manager = None


def get_fallback_thread_manager():
    """Return the bounded manager used by direct SDK and isolated callers."""
    global _fallback_thread_manager
    if _fallback_thread_manager is None:
        with _fallback_lock:
            if _fallback_thread_manager is None:
                from .manager import ThreadManager

                policies = {
                    name: LanePolicy(
                        name=name,
                        max_workers=workers,
                        max_queue_size=queue_size,
                        queue_timeout_seconds=0,
                        cancel_grace_seconds=5,
                        shutdown_grace_seconds=15,
                    )
                    for name, workers, queue_size in (
                        ("agent-run", 4, 16),
                        ("model-tool-io", 4, 16),
                        ("control-io", 16, 8),
                        ("evaluation", 2, 8),
                        ("background-service", 12, 4),
                        ("mcp-session", 4, 0),
                        ("sandbox", 200, 4),
                    )
                }
                manager = ThreadManager(service_name="sdk-fallback", lane_policies=policies)
                manager.start()
                _fallback_thread_manager = manager
    return _fallback_thread_manager


async def shutdown_fallback_thread_manager(timeout: float = 15.0):
    global _fallback_thread_manager
    with _fallback_lock:
        manager = _fallback_thread_manager
        _fallback_thread_manager = None
    if manager is not None:
        return await manager.shutdown(timeout=timeout)
    return None


async def run_blocking(
    task_name: str,
    fn: Callable,
    *args,
    lane: str = "model-tool-io",
    owner: str = "sdk",
    **kwargs,
):
    """Run blocking SDK work through the current process manager."""
    manager = get_current_thread_manager() or get_default_thread_manager()
    if manager is None:
        manager = get_fallback_thread_manager()
    return await manager.run(
        lane,
        ManagedTaskSpec(task_name=task_name, owner=owner),
        fn,
        *args,
        **kwargs,
    )
