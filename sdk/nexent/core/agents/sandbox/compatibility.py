# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit optional smolagents execution types used by the shared sandbox."""

import logging
from enum import IntEnum
from importlib import import_module
from types import SimpleNamespace
from typing import Any


class _LogLevel(IntEnum):
    """Minimal LogLevel enum compatible with smolagents.monitoring.LogLevel."""

    OFF = -1
    ERROR = 0
    INFO = 1
    DEBUG = 2


class _AgentLoggerAdapter:
    """
    Thin adapter that satisfies ``smolagents.AgentLogger``'s ``.log(*args, level=...)``
    call signature while routing output through the standard ``logging.Logger``.

    ``DockerExecutor`` (and other remote executors) call::

        self.logger.log("message", level=LogLevel.INFO)

    Standard ``logging.Logger`` uses::

        logger.log(level, "message")   # positional: (int, str)

    This adapter bridges the two by accepting the smolagents signature and
    forwarding to the underlying logger with the correct argument order.
    """

    def __init__(self, delegate: logging.Logger) -> None:
        self._delegate = delegate
        self._level_map = {
            _LogLevel.OFF: logging.CRITICAL + 1,
            _LogLevel.ERROR: logging.ERROR,
            _LogLevel.INFO: logging.INFO,
            _LogLevel.DEBUG: logging.DEBUG,
        }

    def log(self, *args: Any, level: int | str | _LogLevel = _LogLevel.INFO, **kwargs: Any) -> None:
        """smolagents-compatible log(): first positional arg is the message."""
        if isinstance(level, str):
            level = _LogLevel[level.upper()]
        numeric = self._level_map.get(_LogLevel(int(level)), logging.INFO)
        if self._delegate.isEnabledFor(numeric):
            # ``*args`` contains the message(s) from smolagents AgentLogger;
            # ``self._delegate.log`` expects (level, msg) — swap argument order.
            self._delegate.log(numeric, " ".join(str(a) for a in args), **kwargs)

    def log_error(self, message: str) -> None:
        self._delegate.error(message)


def _make_smolagents_logger(logger_: logging.Logger) -> _AgentLoggerAdapter:
    """Wrap a standard Logger into an AgentLogger-compatible adapter."""
    return _AgentLoggerAdapter(logger_)


def _make_code_output(logs: str) -> Any:
    """Return the executor result shape expected by the agent runtime."""
    try:
        from smolagents.remote_executors import CodeOutput

        return CodeOutput(output=None, logs=logs, is_final_answer=False)
    except ImportError:
        return SimpleNamespace(output=None, logs=logs, is_final_answer=False)


def _make_local_executor(additional_imports: list[str]) -> Any:
    """Build a LocalPythonExecutor with the standard safe-import list."""
    from smolagents.local_python_executor import LocalPythonExecutor

    executor = LocalPythonExecutor(additional_imports)
    executor._nexent_backend = "local"
    return executor


_REMOTE_TYPES = {
    "DockerExecutor",
    "CodeOutput",
    "_websocket_send_execute_request",
    "WasmExecutor",
    "AgentError",
    "RemotePythonExecutor",
}


def __getattr__(name):
    if name in _REMOTE_TYPES:
        return getattr(import_module("smolagents.remote_executors"), name)
    if name in {"AgentAudio", "AgentImage"}:
        return getattr(import_module("smolagents.agent_types"), name)
    raise AttributeError(name)
