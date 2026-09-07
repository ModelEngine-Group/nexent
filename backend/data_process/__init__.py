"""Celery-backed data-processing package.

The package exports legacy names lazily so importing a lightweight helper such as
data_process.parser_runtime does not initialize Celery or parser modules.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "app",
    "process",
    "forward",
    "process_and_forward",
    "process_sync",
    "get_task_info",
    "get_task_details",
]


def __getattr__(name: str) -> Any:
    if name == "app":
        from .app import app
        return app
    if name in {"process", "forward", "process_and_forward", "process_sync"}:
        from . import tasks
        return getattr(tasks, name)
    if name in {"get_task_info", "get_task_details"}:
        from . import utils
        return getattr(utils, name)
    raise AttributeError(name)
