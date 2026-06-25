"""Lazy public exports for agent modules.

Do not eagerly import CoreAgent or ContextManager here.  Python executes package
``__init__`` before loading submodules such as ``nexent.core.agents.agent_model``;
eager imports would collapse the ContextManager-on/off isolation at import time.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "CoreAgent": (".core_agent", "CoreAgent"),
    "ModelConfig": (".agent_model", "ModelConfig"),
    "ToolConfig": (".agent_model", "ToolConfig"),
    "AgentConfig": (".agent_model", "AgentConfig"),
    "AgentRunInfo": (".agent_model", "AgentRunInfo"),
    "AgentHistory": (".agent_model", "AgentHistory"),
    "ContextComponent": (".agent_model", "ContextComponent"),
    "SystemPromptComponent": (".agent_model", "SystemPromptComponent"),
    "ToolsComponent": (".agent_model", "ToolsComponent"),
    "SkillsComponent": (".agent_model", "SkillsComponent"),
    "MemoryComponent": (".agent_model", "MemoryComponent"),
    "KnowledgeBaseComponent": (".agent_model", "KnowledgeBaseComponent"),
    "ManagedAgentsComponent": (".agent_model", "ManagedAgentsComponent"),
    "ExternalAgentsComponent": (".agent_model", "ExternalAgentsComponent"),
    "ContextStrategy": (".agent_model", "ContextStrategy"),
    "FullStrategy": (".agent_model", "FullStrategy"),
    "TokenBudgetStrategy": (".agent_model", "TokenBudgetStrategy"),
    "BufferedStrategy": (".agent_model", "BufferedStrategy"),
    "PriorityWeightedStrategy": (".agent_model", "PriorityWeightedStrategy"),
    "ComponentType": (".agent_model", "ComponentType"),
    "ContextManager": (".agent_context", "ContextManager"),
    "SummaryTaskStep": (".agent_context", "SummaryTaskStep"),
    "PreviousSummaryCache": (".summary_cache", "PreviousSummaryCache"),
    "CurrentSummaryCache": (".summary_cache", "CurrentSummaryCache"),
    "CompressionCallRecord": (".summary_cache", "CompressionCallRecord"),
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
