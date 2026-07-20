"""Normalizer for the Phase 4 retrieval pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from ..models import (
    ExternalMemoryItem,
    MemoryLayer,
    MemorySearchResult,
    MemoryType,
    RetrievalSource,
)
from .token_counter import count_tokens


logger = logging.getLogger("memory_retrieval.normalizer")


def _compute_age_days(created_at: Optional[datetime]) -> Optional[float]:
    """Return the age of a record in days, or None if creation time is absent."""
    if created_at is None:
        return None
    delta = datetime.utcnow() - created_at
    return delta.total_seconds() / 86400.0


class Normalizer:
    """Converts retrieval results into the pipeline's internal representation."""

    def normalize(
        self,
        internal_results: List[MemorySearchResult],
        external_results: Optional[List[ExternalMemoryItem]] = None,
        *,
        created_at_for_id: Optional[dict[int, datetime]] = None,
    ) -> List["PipelineMemoryRecord"]:
        """Normalize all retrieval results into PipelineMemoryRecord instances."""
        candidates: List["PipelineMemoryRecord"] = []

        for result in internal_results:
            rec = self._normalize_internal(result, created_at_for_id)
            candidates.append(rec)
            logger.debug(
                "[normalize] id=%s content=%r score=%.4f source=%s layer=%s "
                "memory_type=%s age_days=%s tokens=%d is_external=%s",
                rec.record_id,
                rec.content[:60],
                rec.score,
                rec.source.value,
                rec.layer.value,
                rec.memory_type.value if rec.memory_type else None,
                f"{rec.age_days:.1f}" if rec.age_days is not None else None,
                rec.token_count,
                rec.is_external,
            )

        if external_results:
            for item in external_results:
                rec = self._normalize_external(item)
                candidates.append(rec)
                logger.debug(
                    "[normalize] id=%s content=%r score=%.4f source=%s layer=%s "
                    "memory_type=%s age_days=%s tokens=%d is_external=%s",
                    rec.record_id,
                    rec.content[:60],
                    rec.score,
                    rec.source.value,
                    rec.layer.value,
                    rec.memory_type.value if rec.memory_type else None,
                    f"{rec.age_days:.1f}" if rec.age_days is not None else None,
                    rec.token_count,
                    rec.is_external,
                )

        logger.debug(
            "[normalize] done: internal=%d external=%d total=%d",
            len(internal_results),
            len(external_results) if external_results else 0,
            len(candidates),
        )
        return candidates

    def _normalize_internal(
        self,
        result: MemorySearchResult,
        created_at_for_id: Optional[dict[int, datetime]] = None,
    ) -> "PipelineMemoryRecord":
        """Convert a single internal MemorySearchResult."""
        layer_value = result.layer.value if result.layer else MemoryLayer.AGENT.value
        memory_type_str = (result.metadata or {}).get("memory_type", "short_term")
        try:
            memory_type = MemoryType(memory_type_str)
        except ValueError:
            memory_type = MemoryType.SHORT_TERM

        is_external = result.is_external or result.source != "internal"
        source = RetrievalSource.EXTERNAL if is_external else RetrievalSource.AGENT_SHORT_TERM

        age_days: Optional[float] = None
        if result.memory_id is not None and created_at_for_id:
            try:
                mem_id_int = int(result.memory_id)
                created_at = created_at_for_id.get(mem_id_int)
                age_days = _compute_age_days(created_at)
            except (TypeError, ValueError):
                pass

        token_count = count_tokens(result.content)
        metadata = result.metadata or {}

        return PipelineMemoryRecord(
            record_id=str(result.memory_id) if result.memory_id else f"ext_{result.external_id}",
            content=result.content,
            score=result.score,
            source=source,
            is_external=is_external,
            tenant_id=metadata.get("tenant_id", ""),
            user_id=metadata.get("user_id"),
            agent_id=metadata.get("agent_id"),
            conversation_id=metadata.get("conversation_id"),
            layer=MemoryLayer(layer_value),
            memory_type=memory_type,
            source_weight=1.0,
            fused_score=None,
            token_count=token_count,
            age_days=age_days,
            metadata=metadata,
        )

    def _normalize_external(self, item: ExternalMemoryItem) -> "PipelineMemoryRecord":
        """Convert a single ExternalMemoryItem."""
        token_count = count_tokens(item.content)
        meta = item.metadata or {}
        return PipelineMemoryRecord(
            record_id=item.id,
            content=item.content,
            score=item.score,
            source=RetrievalSource.EXTERNAL,
            is_external=True,
            tenant_id=meta.get("tenant_id", ""),
            user_id=meta.get("user_id"),
            agent_id=meta.get("agent_id"),
            conversation_id=meta.get("conversation_id"),
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            source_weight=1.0,
            fused_score=None,
            token_count=token_count,
            age_days=None,
            metadata=meta,
        )


from ..models import PipelineMemoryRecord
