"""Storage-independent Dreaming consolidation primitives."""

from .models import (
    DreamingCandidate,
    DreamingDecision,
    DreamingMetrics,
    DreamingThresholds,
)
from .scoring import compute_metrics, score_candidate, select_candidates
from .service import analyze_rem_content, build_candidate


__all__ = [
    "DreamingCandidate",
    "DreamingDecision",
    "DreamingMetrics",
    "DreamingThresholds",
    "analyze_rem_content",
    "build_candidate",
    "compute_metrics",
    "score_candidate",
    "select_candidates",
]
