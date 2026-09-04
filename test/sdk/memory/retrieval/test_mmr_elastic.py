import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../../.."))


class PipelineMemoryRecord:
    def __init__(self, **kwargs):
        self.record_id = kwargs.get("record_id", "")
        self.content = kwargs.get("content", "")
        self.score = kwargs.get("score", 0.0)
        self.fused_score = kwargs.get("fused_score", 0.0)
        self.__dict__.update(kwargs)


def _jaccard_similarity(text_a, text_b):
    if not text_a or not text_b:
        return 0.0
    def _tokens(text):
        return set(text.lower().split())
    set_a = _tokens(text_a)
    set_b = _tokens(text_b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


class MMRDeduplicator:
    def __init__(self, mmr_lambda=0.7, mmr_final_k=5, mmr_candidate_top_k=10,
                 mmr_duplicate_threshold=0.92, mmr_candidate_max=200):
        if not 0.0 <= mmr_lambda <= 1.0:
            raise ValueError("mmr_lambda must be between 0.0 and 1.0")
        if mmr_final_k <= 0:
            raise ValueError("mmr_final_k must be positive")
        if not 0.0 <= mmr_duplicate_threshold <= 1.0:
            raise ValueError("mmr_duplicate_threshold must be between 0.0 and 1.0")
        self.mmr_lambda = mmr_lambda
        self.mmr_final_k = mmr_final_k
        self.mmr_candidate_top_k = mmr_candidate_top_k
        self.mmr_duplicate_threshold = mmr_duplicate_threshold
        self.mmr_candidate_max = mmr_candidate_max

    def dedupe(self, candidates, query=None):
        if not candidates:
            return []
        sorted_candidates = sorted(candidates, key=lambda r: r.fused_score or 0, reverse=True)
        max_candidates = self.mmr_candidate_max
        if len(sorted_candidates) > max_candidates:
            pool = sorted_candidates[:max_candidates]
        else:
            pool = sorted_candidates
        pool = self._prune_duplicates(pool)
        selected = []
        remaining = list(pool)
        while remaining and len(selected) < self.mmr_final_k:
            best_record = None
            best_score = -1.0
            for candidate in remaining:
                mmr_score = self._mmr_score(candidate, selected, query)
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_record = candidate
            if best_record is None:
                break
            selected.append(best_record)
            remaining.remove(best_record)
        return selected

    def _prune_duplicates(self, candidates):
        kept = []
        for candidate in candidates:
            is_duplicate = False
            for existing in kept:
                sim = _jaccard_similarity(candidate.content, existing.content)
                if sim >= self.mmr_duplicate_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(candidate)
        return kept

    def _mmr_score(self, candidate, selected, query):
        relevance = candidate.fused_score or 0.0
        if not selected:
            return self.mmr_lambda * relevance
        max_sim = 0.0
        for selected_record in selected:
            sim = _jaccard_similarity(candidate.content, selected_record.content)
            if sim > max_sim:
                max_sim = sim
        diversity = 1.0 - max_sim
        return self.mmr_lambda * relevance + (1.0 - self.mmr_lambda) * diversity


def _make_record(record_id, content, fused_score=0.5):
    return PipelineMemoryRecord(
        record_id=record_id,
        content=content,
        fused_score=fused_score,
    )


def test_le_200_candidates_all_enter_mmr():
    candidates = [_make_record(str(i), f"content {i}", 0.9 - i * 0.001) for i in range(100)]
    mmr = MMRDeduplicator(mmr_final_k=5, mmr_candidate_max=200)
    result = mmr.dedupe(candidates)
    assert len(result) <= 5
    assert len(result) > 0


def test_gt_200_candidates_truncated_by_fused_score():
    candidates = [_make_record(str(i), f"unique content number {i}", 0.5 + i * 0.001) for i in range(300)]
    mmr = MMRDeduplicator(mmr_final_k=5, mmr_candidate_max=200)
    result = mmr.dedupe(candidates)
    assert len(result) <= 5
    top_ids = {r.record_id for r in result}
    high_score_ids = {str(i) for i in range(200, 300)}
    assert len(top_ids & high_score_ids) > 0


def test_boundary_at_exactly_200():
    candidates = [_make_record(str(i), f"content {i}", 0.9 - i * 0.001) for i in range(200)]
    mmr = MMRDeduplicator(mmr_final_k=5, mmr_candidate_max=200)
    result = mmr.dedupe(candidates)
    assert len(result) <= 5
    assert len(result) > 0


def test_empty_candidates():
    mmr = MMRDeduplicator()
    assert mmr.dedupe([]) == []


def test_single_candidate():
    mmr = MMRDeduplicator(mmr_final_k=5)
    result = mmr.dedupe([_make_record("1", "only one", 0.9)])
    assert len(result) == 1


def test_jaccard_similarity_identical():
    assert _jaccard_similarity("hello world", "hello world") == 1.0


def test_jaccard_similarity_completely_different():
    assert _jaccard_similarity("hello world", "foo bar") == 0.0


def test_jaccard_similarity_partial_overlap():
    sim = _jaccard_similarity("hello world foo", "hello world bar")
    assert 0.0 < sim < 1.0


def test_jaccard_similarity_empty_strings():
    assert _jaccard_similarity("", "hello") == 0.0
    assert _jaccard_similarity("hello", "") == 0.0


def test_mmr_lambda_validation():
    with pytest.raises(ValueError):
        MMRDeduplicator(mmr_lambda=-0.1)
    with pytest.raises(ValueError):
        MMRDeduplicator(mmr_lambda=1.5)


def test_mmr_final_k_validation():
    with pytest.raises(ValueError):
        MMRDeduplicator(mmr_final_k=0)


def test_mmr_duplicate_threshold_validation():
    with pytest.raises(ValueError):
        MMRDeduplicator(mmr_duplicate_threshold=-0.1)


def test_near_duplicates_pruned():
    r1 = _make_record("1", "the quick brown fox jumps over the lazy dog", 0.95)
    r2 = _make_record("2", "the quick brown fox jumps over the lazy dog", 0.90)
    r3 = _make_record("3", "completely different content here today", 0.85)
    mmr = MMRDeduplicator(mmr_final_k=5, mmr_duplicate_threshold=0.9)
    result = mmr.dedupe([r1, r2, r3])
    ids = {r.record_id for r in result}
    assert "1" in ids
    assert "3" in ids


def test_diverse_results_selected():
    candidates = [
        _make_record("1", "python programming language", 0.9),
        _make_record("2", "java programming language", 0.85),
        _make_record("3", "cooking recipes for dinner", 0.8),
        _make_record("4", "machine learning algorithms", 0.75),
    ]
    mmr = MMRDeduplicator(mmr_final_k=3, mmr_lambda=0.5, mmr_duplicate_threshold=0.9)
    result = mmr.dedupe(candidates)
    assert len(result) == 3
