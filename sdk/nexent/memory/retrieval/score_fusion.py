"""Score fusion for the Phase 4 retrieval pipeline."""

from __future__ import annotations

import logging
from typing import List

from ..models import PipelineMemoryRecord, RetrievalSource


logger = logging.getLogger("memory_retrieval.score_fusion")


class ScoreFusion:
    """Apply source-weight fusion to retrieval candidates."""

    def __init__(
        self,
        w_agent_short_term: float = 1.0,
        w_external: float = 0.8,
    ):
        """Initialize the fuser with source weights."""
        self.w_agent_short_term = w_agent_short_term
        self.w_external = w_external

    def fuse(self, candidates: List[PipelineMemoryRecord]) -> List[PipelineMemoryRecord]:
        """Apply source-weight fusion to the candidate list.

        For each candidate, sets source_weight based on its source and
        computes fused_score = source_weight * retrieval_score.
        If fused_score is already set (idempotency guard), the record is
        returned unchanged.
        """
        for record in candidates:
            before = record.fused_score
            if before is not None:
                logger.debug(
                    "[fusion] id=%s fused_score=%.4f already_set (skipped)",
                    record.record_id,
                    before,
                )
                continue
            weight = self._get_weight(record.source)
            record.source_weight = weight
            after = weight * record.score
            record.fused_score = after
            delta = after - record.score
            logger.debug(
                "[fusion] id=%s raw_score=%.4f weight=%.2f "
                "fused_score=%.4f delta=%+.4f source=%s",
                record.record_id,
                record.score,
                weight,
                after,
                delta,
                record.source.value,
            )

        logger.debug(
            "[fusion] done: candidates=%d w_agent_short_term=%.2f w_external=%.2f",
            len(candidates),
            self.w_agent_short_term,
            self.w_external,
        )
        return candidates

    def _get_weight(self, source: RetrievalSource) -> float:
        """Return the source weight for a given retrieval source."""
        if source == RetrievalSource.AGENT_SHORT_TERM:
            return self.w_agent_short_term
        elif source == RetrievalSource.EXTERNAL:
            return self.w_external
        return 1.0
