from datetime import datetime, timedelta

import pytest

from nexent.memory.dreaming import (
    DreamingCandidate,
    DreamingThresholds,
    analyze_rem_content,
    compute_metrics,
    score_candidate,
    select_candidates,
)


def candidate(**overrides):
    values = {
        "memory_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "agent_id": "agent",
        "content": "The user always prefers PostgreSQL transactions.",
        "recall_count": 3,
        "daily_count": 2,
        "grounded_count": 1,
        "total_retrieval_score": 4.2,
        "query_hashes": ["q1", "q2"],
        "recall_days": ["2026-07-20", "2026-07-22"],
        "concept_tags": ["preference", "transaction"],
        "light_hits": 2,
        "rem_hits": 1,
        "last_recalled_at": datetime(2026, 7, 22),
        "last_light_at": datetime(2026, 7, 22),
        "last_rem_at": datetime(2026, 7, 22),
    }
    values.update(overrides)
    return DreamingCandidate(**values)


def test_ac004_openclaw_score_formula():
    score, metrics = score_candidate(candidate(), now=datetime(2026, 7, 23))
    assert score == pytest.approx(0.7268086998271306)
    assert metrics.signal_count == 6
    assert metrics.context_diversity == 2
    assert metrics.relevance == pytest.approx(0.7)
    assert metrics.consolidation == pytest.approx(0.36544353551179476)


@pytest.mark.parametrize(
    ("changes", "thresholds", "reason"),
    [
        ({"noise": True}, DreamingThresholds(min_score=0), "noise"),
        (
            {"already_promoted": True},
            DreamingThresholds(min_score=0),
            "already_promoted",
        ),
        (
            {"total_retrieval_score": 0},
            DreamingThresholds(min_score=0.7),
            "score_below_threshold",
        ),
        (
            {"recall_count": 0, "daily_count": 0, "grounded_count": 0},
            DreamingThresholds(min_score=0, min_recall_count=1),
            "recall_below_threshold",
        ),
        (
            {"query_hashes": [], "recall_days": []},
            DreamingThresholds(min_score=0, min_unique_queries=1),
            "diversity_below_threshold",
        ),
    ],
)
def test_ac005_gates(changes, thresholds, reason):
    decisions = select_candidates(
        [candidate(**changes)], thresholds=thresholds, now=datetime(2026, 7, 23)
    )
    assert decisions[0].promote is False
    assert decisions[0].reason == reason


def test_ac005_stable_sorting():
    now = datetime(2026, 7, 23)
    first = candidate(memory_id=9)
    second = candidate(memory_id=2)
    decisions = select_candidates(
        [first, second],
        thresholds=DreamingThresholds(
            min_score=0, min_recall_count=0, min_unique_queries=0
        ),
        now=now,
    )
    assert [item.candidate.memory_id for item in decisions] == [2, 9]


def test_ac003_rem_patterns_and_noise():
    tags, noise = analyze_rem_content(
        "I always prefer PostgreSQL transaction rollback."
    )
    assert {"preference", "persistent", "transaction"} <= set(tags)
    assert noise is False
    _, noise = analyze_rem_content("Today's temporary TODO for this session")
    assert noise is True


def test_metrics_boundaries_and_missing_dates():
    metrics = compute_metrics(
        candidate(
            recall_count=-2,
            daily_count=0,
            grounded_count=0,
            total_retrieval_score=100,
            recall_days=[],
            last_recalled_at=None,
            last_light_at=None,
            last_rem_at=None,
        ),
        now=datetime(2026, 7, 23),
    )
    assert metrics.frequency == 0
    assert metrics.relevance == 1
    assert metrics.recency == 0
    assert metrics.consolidation == 0
    assert metrics.phase_boost == 0


def test_future_timestamps_are_clamped_to_full_recency():
    now = datetime(2026, 7, 23)
    metrics = compute_metrics(
        candidate(last_recalled_at=now + timedelta(days=1)), now=now
    )
    assert metrics.recency == 1
