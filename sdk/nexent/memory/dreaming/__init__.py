"""Storage-independent Dreaming consolidation primitives."""

from .models import (
    DreamingCandidate,
    DreamingDecision,
    DreamingMetrics,
    DreamingThresholds,
)
from .scoring import compute_metrics, score_candidate, select_candidates
from .service import analyze_rem_content, build_candidate
from .version_builder import (
    DreamingSummarizationOutput,
    DreamingSummarizationRequest,
    DreamingMemoryUnit,
    DreamingVersionBuildResult,
    build_user_memory_summary,
    units_from_decisions,
)


__all__ = [
    "DreamingCandidate",
    "DreamingDecision",
    "DreamingMetrics",
    "DreamingThresholds",
    "DreamingSummarizationOutput",
    "DreamingSummarizationRequest",
    "DreamingMemoryUnit",
    "DreamingVersionBuildResult",
    "analyze_rem_content",
    "build_candidate",
    "compute_metrics",
    "build_user_memory_summary",
    "score_candidate",
    "select_candidates",
    "units_from_decisions",
]
