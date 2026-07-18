"""Unified agent context domain with lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ContextItem": (".models", "ContextItem"),
    "ContextItemInput": (".models", "ContextItemInput"),
    "ContextItemType": (".models", "ContextItemType"),
    "normalize_context_inputs": (".models", "normalize_context_inputs"),
    "ContextItemRenderer": (".rendering", "ContextItemRenderer"),
    "ContextItemRenderingError": (".rendering", "ContextItemRenderingError"),
    "ContextManager": (".manager", "ContextManager"),
    "ContextManagerConfig": (".config", "ContextManagerConfig"),
    "ManagedContextRuntime": (".runtime", "ManagedContextRuntime"),
    "ManagedRunContext": (".summary_step", "ManagedRunContext"),
    "SummaryTaskStep": (".summary_step", "SummaryTaskStep"),
    "compress_history_offline": (".step_renderer", "compress_history_offline"),
    "format_summary_output": (".budget", "format_summary_output"),
    "_is_context_length_error": (".budget", "_is_context_length_error"),
    "AuthorityTier": (".policy", "AuthorityTier"),
    "ContextProcessingMode": (".policy", "ContextProcessingMode"),
    "ContextPolicy": (".policy", "ContextPolicy"),
    "PolicyLayers": (".policy", "PolicyLayers"),
    "resolve_policy": (".policy", "resolve_policy"),
    "ItemDecision": (".selection", "ItemDecision"),
    "SelectionDecision": (".selection", "SelectionDecision"),
    "select_context_items": (".selection", "select_context_items"),
    "CpuEmbeddingProvider": (".scoring", "CpuEmbeddingProvider"),
    "EmbeddingProviderChain": (".scoring", "EmbeddingProviderChain"),
    "ExternalEmbeddingProvider": (".scoring", "ExternalEmbeddingProvider"),
    "rank_by_mmr": (".scoring", "rank_by_mmr"),
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
