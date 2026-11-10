# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate resources bound by the legacy Agent execution host."""

from nexent.core.concurrency import ThreadManager, get_default_thread_manager


def require_legacy_execution_host(execution_host):
    if execution_host is None:
        raise RuntimeError("Legacy Agent execution requires a Runtime host")
    return execution_host


def require_legacy_thread_manager(thread_manager: ThreadManager | None) -> ThreadManager:
    """Resolve the explicitly bound pool or the process's installed SDK pool."""
    if thread_manager is None:
        thread_manager = get_default_thread_manager()
    if thread_manager is None:
        raise RuntimeError("Legacy Agent execution requires a thread manager")
    return thread_manager
