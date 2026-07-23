"""OpenClaw-compatible Deep Sleep scoring and deterministic selection."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, List, Optional

from .models import (
    DreamingCandidate,
    DreamingDecision,
    DreamingMetrics,
    DreamingThresholds,
)


WEIGHTS = {
    "frequency": 0.24,
    "relevance": 0.30,
    "query_diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "conceptual_richness": 0.06,
}


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _age_days(value: Optional[datetime], now: datetime) -> float:
    if value is None:
        return float("inf")
    return max(0.0, (now - value).total_seconds() / 86400.0)


def _recency(value: Optional[datetime], now: datetime, half_life_days: float) -> float:
    if value is None:
        return 0.0
    decay_lambda = math.log(2) / max(1.0, half_life_days)
    return clamp_score(math.exp(-decay_lambda * _age_days(value, now)))


def compute_metrics(
    candidate: DreamingCandidate,
    *,
    now: Optional[datetime] = None,
    recency_half_life_days: float = 14,
) -> DreamingMetrics:
    now = now or datetime.utcnow()
    signal_count = max(0, candidate.recall_count) + max(0, candidate.daily_count) + max(0, candidate.grounded_count)
    unique_queries = len(set(candidate.query_hashes))
    unique_days = len(set(candidate.recall_days))
    context_diversity = max(unique_queries, unique_days)
    frequency = clamp_score(math.log1p(signal_count) / math.log1p(10))
    relevance = clamp_score(candidate.total_retrieval_score / max(1, signal_count))
    query_diversity = clamp_score(context_diversity / 5)
    recency = _recency(candidate.last_recalled_at, now, recency_half_life_days)

    if unique_days == 0:
        consolidation = 0.0
    elif unique_days == 1:
        consolidation = 0.2
    else:
        parsed_days = sorted(datetime.fromisoformat(day).date() for day in set(candidate.recall_days))
        span_days = (parsed_days[-1] - parsed_days[0]).days
        spacing = clamp_score(math.log1p(unique_days - 1) / math.log1p(4))
        span = clamp_score(span_days / 7)
        consolidation = max(
            clamp_score(0.55 * spacing + 0.45 * span),
            clamp_score(candidate.grounded_count / 3),
        )

    conceptual_richness = clamp_score(len(set(candidate.concept_tags)) / 6)
    light_strength = clamp_score(math.log1p(max(0, candidate.light_hits)) / math.log1p(6))
    rem_strength = clamp_score(math.log1p(max(0, candidate.rem_hits)) / math.log1p(6))
    phase_boost = clamp_score(
        0.06 * light_strength * _recency(candidate.last_light_at, now, 14)
        + 0.09 * rem_strength * _recency(candidate.last_rem_at, now, 14)
    )
    return DreamingMetrics(
        signal_count=signal_count,
        context_diversity=context_diversity,
        frequency=frequency,
        relevance=relevance,
        query_diversity=query_diversity,
        recency=recency,
        consolidation=consolidation,
        conceptual_richness=conceptual_richness,
        phase_boost=phase_boost,
    )


def score_candidate(
    candidate: DreamingCandidate,
    *,
    now: Optional[datetime] = None,
    recency_half_life_days: float = 14,
) -> tuple[float, DreamingMetrics]:
    metrics = compute_metrics(candidate, now=now, recency_half_life_days=recency_half_life_days)
    score = sum(getattr(metrics, name) * weight for name, weight in WEIGHTS.items())
    return clamp_score(score + metrics.phase_boost), metrics


def select_candidates(
    candidates: Iterable[DreamingCandidate],
    *,
    thresholds: Optional[DreamingThresholds] = None,
    now: Optional[datetime] = None,
    recency_half_life_days: float = 14,
) -> List[DreamingDecision]:
    thresholds = thresholds or DreamingThresholds()
    decisions: List[DreamingDecision] = []
    for candidate in candidates:
        score, metrics = score_candidate(candidate, now=now, recency_half_life_days=recency_half_life_days)
        reason = "eligible"
        promote = True
        if candidate.noise:
            promote, reason = False, "noise"
        elif candidate.already_promoted and not thresholds.include_promoted:
            promote, reason = False, "already_promoted"
        elif score < thresholds.min_score:
            promote, reason = False, "score_below_threshold"
        elif metrics.signal_count < thresholds.min_recall_count:
            promote, reason = False, "recall_below_threshold"
        elif metrics.context_diversity < thresholds.min_unique_queries:
            promote, reason = False, "diversity_below_threshold"
        decisions.append(
            DreamingDecision(
                candidate=candidate,
                metrics=metrics,
                score=score,
                promote=promote,
                reason=reason,
                archive_suggested=promote,
            )
        )
    return sorted(
        decisions,
        key=lambda item: (
            not item.promote,
            -item.score,
            -item.metrics.signal_count,
            item.candidate.memory_id,
        ),
    )
