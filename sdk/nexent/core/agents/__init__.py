"""Lazy public exports for agent modules.

Do not eagerly import CoreAgent or ContextManager here.  Python executes package
``__init__`` before loading submodules such as ``nexent.core.agents.agent_model``;
eager imports would collapse the ContextManager-on/off isolation at import time.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_AGENT_MODEL_MODULE = ".agent_model"
_SUMMARY_CACHE_MODULE = ".summary_cache"

_EXPORTS = {
    "CoreAgent": (".core_agent", "CoreAgent"),
    "ModelConfig": (_AGENT_MODEL_MODULE, "ModelConfig"),
    "ToolConfig": (_AGENT_MODEL_MODULE, "ToolConfig"),
    "AgentConfig": (_AGENT_MODEL_MODULE, "AgentConfig"),
    "AgentRunInfo": (_AGENT_MODEL_MODULE, "AgentRunInfo"),
    "AgentHistory": (_AGENT_MODEL_MODULE, "AgentHistory"),
    "ContextItem": (".context", "ContextItem"),
    "ContextItemInput": (".context", "ContextItemInput"),
    "ContextItemType": (".context", "ContextItemType"),
    "ContextManager": (".context", "ContextManager"),
    "SummaryTaskStep": (".context", "SummaryTaskStep"),
    "PreviousSummaryCache": (_SUMMARY_CACHE_MODULE, "PreviousSummaryCache"),
    "CurrentSummaryCache": (_SUMMARY_CACHE_MODULE, "CurrentSummaryCache"),
    "CompressionCallRecord": (_SUMMARY_CACHE_MODULE, "CompressionCallRecord"),
    "ContextManagerConfig": (".context", "ContextManagerConfig"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
