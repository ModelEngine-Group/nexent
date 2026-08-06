"""Token-budget selection for the Phase 4 retrieval pipeline."""

from __future__ import annotations

import logging
from typing import List

from ..models import PipelineMemoryRecord


logger = logging.getLogger("memory_retrieval.token_budget")


class TokenBudgetSelector:
    """Select records greedily by fused score until the token budget is exhausted."""

    def __init__(self, token_budget: int = 2000):
        """Initialize the budget selector."""
        if token_budget < 0:
            raise ValueError("token_budget must be non-negative")
        self.token_budget = token_budget

    def select(self, candidates: List[PipelineMemoryRecord]) -> List[PipelineMemoryRecord]:
        """Select records greedily while staying within the token budget.

        Records are iterated in descending order of fused_score; each record
        is included only if the cumulative token count after its inclusion
        would not exceed token_budget.
        """
        if not candidates or self.token_budget <= 0:
            return []

        sorted_records = sorted(candidates, key=lambda r: r.fused_score or 0, reverse=True)

        selected: List[PipelineMemoryRecord] = []
        used_tokens = 0

        logger.debug(
            "[budget] start: candidates=%d budget=%d",
            len(candidates),
            self.token_budget,
        )
        for record in sorted_records:
            token_count = max(record.token_count, 0)
            new_total = used_tokens + token_count
            if new_total > self.token_budget:
                logger.debug(
                    "[budget] STOP id=%s fused_score=%.4f tokens=%d "
                    "used=%d new_total=%d exceeds_budget=%d",
                    record.record_id,
                    record.fused_score or 0.0,
                    token_count,
                    used_tokens,
                    new_total,
                    self.token_budget,
                )
                break

            selected.append(record)
            used_tokens = new_total
            logger.debug(
                "[budget]     ADD id=%s fused_score=%.4f tokens=%d "
                "used=%d/%d remaining=%d",
                record.record_id,
                record.fused_score or 0.0,
                token_count,
                used_tokens,
                self.token_budget,
                self.token_budget - used_tokens,
            )

        logger.debug(
            "[budget] done: selected=%d used_tokens=%d budget=%d",
            len(selected),
            used_tokens,
            self.token_budget,
        )
        return selected
