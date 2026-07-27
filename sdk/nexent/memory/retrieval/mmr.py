"""MMR (Maximal Marginal Relevance) deduplication for the Phase 4 retrieval pipeline."""

from __future__ import annotations

import logging
from typing import List, Optional

from ..models import PipelineMemoryRecord


logger = logging.getLogger("memory_retrieval.mmr")


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Return a 0-1 word-level Jaccard similarity between two strings."""
    if not text_a or not text_b:
        return 0.0

    def _tokens(text: str) -> set:
        return set(text.lower().split())

    set_a = _tokens(text_a)
    set_b = _tokens(text_b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


class MMRDeduplicator:
    """Select a diverse top-k using Maximal Marginal Relevance."""

    def __init__(
        self,
        mmr_lambda: float = 0.7,
        mmr_final_k: int = 5,
        mmr_candidate_top_k: int = 10,
        mmr_duplicate_threshold: float = 0.92,
    ):
        """Initialize the MMR deduplicator."""
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

    def dedupe(
        self,
        candidates: List[PipelineMemoryRecord],
        query: Optional[str] = None,
    ) -> List[PipelineMemoryRecord]:
        """Run MMR deduplication over the candidate list."""
        if not candidates:
            return []

        sorted_candidates = sorted(candidates, key=lambda r: r.fused_score or 0, reverse=True)
        pool = sorted_candidates[: self.mmr_candidate_top_k]

        logger.debug(
            "[mmr] input=%d candidate_pool=%d lambda=%.2f final_k=%d threshold=%.2f",
            len(candidates),
            len(pool),
            self.mmr_lambda,
            self.mmr_final_k,
            self.mmr_duplicate_threshold,
        )
        for rec in pool:
            logger.debug(
                "       cand  id=%s score=%.4f content=%r",
                rec.record_id,
                rec.fused_score or 0.0,
                rec.content[:50],
            )

        pool = self._prune_duplicates(pool)

        selected: List[PipelineMemoryRecord] = []
        remaining = list(pool)

        logger.debug("[mmr] after_prune=%d", len(pool))
        for rec in remaining:
            logger.debug(
                "       prune cand id=%s score=%.4f content=%r",
                rec.record_id,
                rec.fused_score or 0.0,
                rec.content[:50],
            )

        step = 0
        while remaining and len(selected) < self.mmr_final_k:
            step += 1
            best_record = None
            best_score = -1.0

            for candidate in remaining:
                mmr_score = self._mmr_score(candidate, selected, query)
                logger.debug(
                    "[mmr] step=%d candidate id=%s score=%.4f mmr_score=%.4f",
                    step,
                    candidate.record_id,
                    candidate.fused_score or 0.0,
                    mmr_score,
                )
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_record = candidate

            if best_record is None:
                break

            selected.append(best_record)
            remaining.remove(best_record)
            logger.debug(
                "[mmr] step=%d SELECTED id=%s fused_score=%.4f mmr_score=%.4f "
                "selected_count=%d remaining=%d",
                step,
                best_record.record_id,
                best_record.fused_score or 0.0,
                best_score,
                len(selected),
                len(remaining),
            )

        logger.debug(
            "[mmr] done: selected=%d",
            len(selected),
        )
        return selected

    def _prune_duplicates(
        self,
        candidates: List[PipelineMemoryRecord],
    ) -> List[PipelineMemoryRecord]:
        """Remove near-duplicate records, keeping the higher-scoring one."""
        kept: List[PipelineMemoryRecord] = []
        for candidate in candidates:
            is_duplicate = False
            for existing in kept:
                sim = _jaccard_similarity(candidate.content, existing.content)
                if sim >= self.mmr_duplicate_threshold:
                    is_duplicate = True
                    logger.debug(
                        "prune: removed record_id=%s (Jaccard=%.3f >= %.3f with %s)",
                        candidate.record_id,
                        sim,
                        self.mmr_duplicate_threshold,
                        existing.record_id,
                    )
                    break
            if not is_duplicate:
                kept.append(candidate)
        return kept

    def _mmr_score(
        self,
        candidate: PipelineMemoryRecord,
        selected: List[PipelineMemoryRecord],
        query: Optional[str],
    ) -> float:
        """Compute the MMR score for a candidate.

        MMR(c) = lambda * relevance - (1 - lambda) * max_similarity
        """
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
