"""Agent context management for memory compression and summarization.

Provides ContextManager for token-aware memory compression of agent memory,
supporting incremental summarization with cache-based optimization.
"""

from .manager import ContextManager
from .offload_store import OffloadStore
from .summary_step import SummaryTaskStep
from .llm_summary import format_summary_output, _is_context_length_error
from .step_renderer import compress_history_offline

# Re-export types from sibling modules so that
# ``from agent_context import ContextManagerConfig`` still works.
from ..summary_config import ContextManagerConfig
from ..summary_cache import CompressionCallRecord, PreviousSummaryCache, CurrentSummaryCache

__all__ = [
    "ContextManager",
    "OffloadStore",
    "SummaryTaskStep",
    "format_summary_output",
    "_is_context_length_error",
    "compress_history_offline",
    "ContextManagerConfig",
    "CompressionCallRecord",
    "PreviousSummaryCache",
    "CurrentSummaryCache",
]
