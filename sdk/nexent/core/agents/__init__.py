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
    "MCPBinding": (_AGENT_MODEL_MODULE, "MCPBinding"),
    "AgentConfig": (_AGENT_MODEL_MODULE, "AgentConfig"),
    "AgentRunInfo": (_AGENT_MODEL_MODULE, "AgentRunInfo"),
    "AgentHistory": (_AGENT_MODEL_MODULE, "AgentHistory"),
    "ContextComponent": (_AGENT_MODEL_MODULE, "ContextComponent"),
    "SystemPromptComponent": (_AGENT_MODEL_MODULE, "SystemPromptComponent"),
    "ToolsComponent": (_AGENT_MODEL_MODULE, "ToolsComponent"),
    "SkillsComponent": (_AGENT_MODEL_MODULE, "SkillsComponent"),
    "MemoryComponent": (_AGENT_MODEL_MODULE, "MemoryComponent"),
    "KnowledgeBaseComponent": (_AGENT_MODEL_MODULE, "KnowledgeBaseComponent"),
    "ManagedAgentsComponent": (_AGENT_MODEL_MODULE, "ManagedAgentsComponent"),
    "ExternalAgentsComponent": (_AGENT_MODEL_MODULE, "ExternalAgentsComponent"),
    "ContextStrategy": (_AGENT_MODEL_MODULE, "ContextStrategy"),
    "FullStrategy": (_AGENT_MODEL_MODULE, "FullStrategy"),
    "TokenBudgetStrategy": (_AGENT_MODEL_MODULE, "TokenBudgetStrategy"),
    "BufferedStrategy": (_AGENT_MODEL_MODULE, "BufferedStrategy"),
    "PriorityWeightedStrategy": (_AGENT_MODEL_MODULE, "PriorityWeightedStrategy"),
    "ComponentType": (_AGENT_MODEL_MODULE, "ComponentType"),
    "ContextManager": (".agent_context", "ContextManager"),
    "SummaryTaskStep": (".agent_context", "SummaryTaskStep"),
    "PreviousSummaryCache": (_SUMMARY_CACHE_MODULE, "PreviousSummaryCache"),
    "CurrentSummaryCache": (_SUMMARY_CACHE_MODULE, "CurrentSummaryCache"),
    "CompressionCallRecord": (_SUMMARY_CACHE_MODULE, "CompressionCallRecord"),
    "ContextManagerConfig": (".summary_config", "ContextManagerConfig"),
    "StrategyType": (".summary_config", "StrategyType"),
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
