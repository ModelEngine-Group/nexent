# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unified agent context domain with lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ContextItem": (".models", "ContextItem"),
    "ContextItemInput": ("nexent.core.agents.contracts.context", "ContextItemInput"),
    "ContextItemType": ("nexent.core.agents.contracts.context", "ContextItemType"),
    "SystemContextItem": (".models", "SystemContextItem"),
    "ToolContextItem": (".models", "ToolContextItem"),
    "SkillContextItem": (".models", "SkillContextItem"),
    "MemoryContextItem": (".models", "MemoryContextItem"),
    "KnowledgeBaseContextItem": (".models", "KnowledgeBaseContextItem"),
    "WorkerAgentContextItem": (".models", "WorkerAgentContextItem"),
    "ExternalAgentContextItem": (".models", "ExternalAgentContextItem"),
    "HistorySummaryContextItem": (".models", "HistorySummaryContextItem"),
    "ConversationTurnContextItem": (".models", "ConversationTurnContextItem"),
    "CurrentTaskContextItem": (".models", "CurrentTaskContextItem"),
    "CurrentPlanningContextItem": (".models", "CurrentPlanningContextItem"),
    "CurrentActionContextItem": (".models", "CurrentActionContextItem"),
    "normalize_context_inputs": (".models", "normalize_context_inputs"),
    "ContextItemRenderer": (".rendering", "ContextItemRenderer"),
    "ContextItemRenderingError": (".rendering", "ContextItemRenderingError"),
    "ContextManager": (".manager", "ContextManager"),
    "ContextManagerConfig": (".config", "ContextManagerConfig"),
    "ManagedRunContext": (".run_context", "ManagedRunContext"),
    "HistoryCompressor": (".history_compression", "HistoryCompressor"),
    "HistorySummaryCandidate": (".history_compression", "HistorySummaryCandidate"),
    "HistorySummaryInput": (".history_compression", "HistorySummaryInput"),
    "format_summary_output": (".budget", "format_summary_output"),
    "_is_context_length_error": (".budget", "_is_context_length_error"),
    "ContextProcessingMode": (".policy", "ContextProcessingMode"),
    "ContextPolicy": (".policy", "ContextPolicy"),
    "PolicyLayers": (".policy", "PolicyLayers"),
    "resolve_policy": (".policy", "resolve_policy"),
    "ItemDecision": (".selection", "ItemDecision"),
    "SelectionDecision": (".selection", "SelectionDecision"),
    "select_context_items": (".selection", "select_context_items"),
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
