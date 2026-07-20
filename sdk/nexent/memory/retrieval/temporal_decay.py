"""Temporal decay for the Phase 4 retrieval pipeline."""

from __future__ import annotations

import logging
from typing import List

from ..models import MemoryLayer, MemoryType, PipelineMemoryRecord


logger = logging.getLogger("memory_retrieval.temporal_decay")


class TemporalDecayer:
    """Apply exponential time-decay to agent short-term memory."""

    def __init__(self, half_life_days: int = 14):
        """Initialize the decayer."""
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        self.half_life_days = half_life_days

    def apply_decay(self, candidates: List[PipelineMemoryRecord]) -> List[PipelineMemoryRecord]:
        """Apply exponential time-decay to eligible candidates.

        Only agent short-term memory is decayed.
        Tenant/user long-term and external items are returned unchanged.
        """
        for record in candidates:
            eligible, reason = self._is_eligible(record)
            if not eligible:
                logger.debug(
                    "[decay] id=%s fused_score=%.4f skipped (%s)",
                    record.record_id,
                    record.fused_score or 0.0,
                    reason,
                )
                continue
            if record.age_days is None:
                logger.debug(
                    "[decay] id=%s fused_score=%.4f skipped (no age_days)",
                    record.record_id,
                    record.fused_score or 0.0,
                )
                continue

            decay = self._compute_decay(record.age_days)
            original = record.fused_score or 0.0
            record.fused_score = original * decay
            logger.debug(
                "[decay] id=%s age_days=%.2f decay=%.4f "
                "%.4f -> %.4f (delta=%+.4f)",
                record.record_id,
                record.age_days,
                decay,
                original,
                record.fused_score,
                record.fused_score - original,
            )
        return candidates

    def _is_eligible(self, record: PipelineMemoryRecord) -> tuple[bool, str]:
        """Return (eligible, reason) for temporal decay."""
        if record.is_external:
            return False, "is_external=True"
        if record.layer != MemoryLayer.AGENT:
            return False, f"layer={record.layer.value} (not AGENT)"
        memory_type = record.memory_type or MemoryType.SHORT_TERM
        if memory_type != MemoryType.SHORT_TERM:
            return False, f"memory_type={memory_type.value} (not SHORT_TERM)"
        return True, "agent+short-term"

    def _compute_decay(self, age_days: float) -> float:
        """Compute the exponential decay factor: 0.5 ^ (age_days / half_life_days)."""
        return 0.5 ** (age_days / self.half_life_days)
