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
    DreamingCompressionOutput,
    DreamingCompressionRequest,
    DreamingMemoryUnit,
    DreamingVersionBuildResult,
    build_dreaming_version,
    units_from_decisions,
)


__all__ = [
    "DreamingCandidate",
    "DreamingDecision",
    "DreamingMetrics",
    "DreamingThresholds",
    "DreamingCompressionOutput",
    "DreamingCompressionRequest",
    "DreamingMemoryUnit",
    "DreamingVersionBuildResult",
    "analyze_rem_content",
    "build_candidate",
    "compute_metrics",
    "build_dreaming_version",
    "score_candidate",
    "select_candidates",
    "units_from_decisions",
]
