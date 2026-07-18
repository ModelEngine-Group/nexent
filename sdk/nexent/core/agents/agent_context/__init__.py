"""Deprecated compatibility path for :mod:`nexent.core.agents.context`."""

from __future__ import annotations

import sys
import warnings
from importlib import import_module


COMPATIBILITY_REMOVAL_VERSION = "v2.4.0"
warnings.warn(
    "nexent.core.agents.agent_context is deprecated; use nexent.core.agents.context; "
    f"the compatibility path will be removed in {COMPATIBILITY_REMOVAL_VERSION}",
    DeprecationWarning,
    stacklevel=2,
)

_CONTEXT_PACKAGE = f"{__package__.rsplit('.', 1)[0]}.context"
_SUBMODULES = (
    "budget",
    "config",
    "current_compression",
    "llm_summary",
    "manager",
    "previous_compression",
    "stats_export",
    "step_renderer",
    "summary_step",
)
for _name in _SUBMODULES:
    sys.modules[f"{__name__}.{_name}"] = import_module(f"{_CONTEXT_PACKAGE}.{_name}")

from ..context import (  # noqa: E402
    ContextManager,
    ContextManagerConfig,
    ManagedRunContext,
    SummaryTaskStep,
    _is_context_length_error,
    compress_history_offline,
    format_summary_output,
)
from ..summary_cache import (  # noqa: E402
    CompressionCallRecord,
    CurrentSummaryCache,
    PreviousSummaryCache,
)


__all__ = [
    "CompressionCallRecord",
    "COMPATIBILITY_REMOVAL_VERSION",
    "ContextManager",
    "ContextManagerConfig",
    "CurrentSummaryCache",
    "ManagedRunContext",
    "PreviousSummaryCache",
    "SummaryTaskStep",
    "_is_context_length_error",
    "compress_history_offline",
    "format_summary_output",
]
