"""Retrieval pipeline orchestrator for Phase 4."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from ..models import (
    ExternalMemoryItem,
    MemoryLayer,
    MemorySearchContext,
    MemorySearchResult,
    PipelineConfig,
    PipelineMemoryRecord,
)
from .mmr import MMRDeduplicator
from .normalizer import Normalizer
from .score_fusion import ScoreFusion
from .temporal_decay import TemporalDecayer
from .token_budget import TokenBudgetSelector


logger = logging.getLogger("memory_retrieval.pipeline")


def enable_debug_logging(
    level: int = logging.DEBUG,
    *,
    to_console: bool = True,
    fmt: str = "%(asctime)s %(name)s %(levelname)s %(message)s",
) -> logging.Logger:
    """Turn on DEBUG-level logging for every stage of the retrieval pipeline.

    The pipeline orchestrator already emits step-by-step debug output
    (record list, per-record scores, MMR-decision and decay impact). Call
    this helper at startup to surface those traces in the console without
    having to configure the logging stack yourself.

    Parameters
    ----------
    level:
        Logging level to assign to the ``memory_retrieval`` logger hierarchy.
        Defaults to ``logging.DEBUG``.
    to_console:
        When True (default), a ``StreamHandler`` is attached to the package
        logger so messages flow to ``stderr``. Disable this when the host
        application already configures logging.
    fmt:
        Log record format string used by the console handler when
        ``to_console=True``.

    Returns
    -------
    logging.Logger
        The package-level ``memory_retrieval`` logger, configured.
    """
    pkg_logger = logging.getLogger("memory_retrieval")
    pkg_logger.setLevel(level)

    if to_console:
        has_stream_handler = any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            for h in pkg_logger.handlers
        )
        if not has_stream_handler:
            handler = logging.StreamHandler()
            handler.setLevel(level)
            handler.setFormatter(logging.Formatter(fmt))
            pkg_logger.addHandler(handler)
        pkg_logger.propagate = True

    logger.debug(
        "debug logging enabled for memory_retrieval at level=%s",
        logging.getLevelName(level),
    )
    return pkg_logger


def _fmt_record(rec: PipelineMemoryRecord, show_content: bool = False) -> str:
    """Format a PipelineMemoryRecord for debug logging."""
    age = f"{rec.age_days:.1f}d" if rec.age_days is not None else "?"
    score = rec.fused_score if rec.fused_score is not None else rec.score
    extra = f" content={rec.content[:40]!r}" if show_content else ""
    return (
        f"[id={rec.record_id} score={score:.4f} age={age} "
        f"tokens={rec.token_count} src={rec.source.value} layer={rec.layer.value}{extra}]"
    )


class RetrievalPipeline:
    """Multi-stage memory retrieval pipeline for agent short-term + external memory."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        """Initialize the pipeline with configuration."""
        cfg = config or PipelineConfig()
        self._normalizer = Normalizer()
        self._fuser = ScoreFusion(
            w_agent_short_term=cfg.w_agent_short_term,
            w_external=cfg.w_external,
        )
        self._decayer = TemporalDecayer(half_life_days=cfg.half_life_days)
        self._mmr = MMRDeduplicator(
            mmr_lambda=cfg.mmr_lambda,
            mmr_final_k=cfg.mmr_final_top_k,
            mmr_candidate_top_k=cfg.mmr_candidate_top_k,
            mmr_duplicate_threshold=cfg.mmr_duplicate_threshold,
        )
        self._budget = TokenBudgetSelector(token_budget=cfg.token_budget)
        self._mmr_final_k = cfg.mmr_final_top_k
        self._token_budget = cfg.token_budget

    def run(
        self,
        internal_results: List[MemorySearchResult],
        query: str,
        external_results: Optional[List[ExternalMemoryItem]] = None,
        *,
        created_at_for_id: Optional[dict[int, Any]] = None,
    ) -> "PipelineResult":
        """Execute the full retrieval pipeline."""
        tenant_long, user_long, agent_short = self._split_by_layer(internal_results)

        logger.debug(
            "[pipeline] start: tenant=%d user=%d agent=%d external=%d query=%r",
            len(tenant_long),
            len(user_long),
            len(agent_short),
            len(external_results) if external_results else 0,
            query[:80],
        )

        # ── Step 1: Normalize ──────────────────────────────────────────────
        normalized = self._normalizer.normalize(
            internal_results=agent_short,
            external_results=external_results,
            created_at_for_id=created_at_for_id,
        )
        logger.debug("[pipeline] STEP=normalize count=%d", len(normalized))
        for rec in sorted(normalized, key=lambda r: r.score, reverse=True):
            logger.debug("       %s", _fmt_record(rec))

        # ── Step 2: Score Fusion ──────────────────────────────────────────
        fused = self._fuser.fuse(normalized)
        logger.debug(
            "[pipeline] STEP=fusion count=%d "
            "w_agent=%.2f w_external=%.2f",
            len(fused),
            self._fuser.w_agent_short_term,
            self._fuser.w_external,
        )
        for rec in sorted(fused, key=lambda r: r.fused_score or 0, reverse=True):
            logger.debug(
                "       %s weight=%.2f delta=%+.4f",
                _fmt_record(rec),
                rec.source_weight,
                (rec.fused_score or 0) - rec.score,
            )

        # ── Step 3: Temporal Decay ────────────────────────────────────────
        decayed = self._decayer.apply_decay(fused)
        changed = [r for r in decayed if r.fused_score != next(
            (f for f in fused if f.record_id == r.record_id), r.fused_score
        )]
        if changed:
            logger.debug(
                "[pipeline] STEP=decay count=%d half_life=%dd changed=%d",
                len(decayed),
                self._decayer.half_life_days,
                len(changed),
            )
            for rec in changed:
                orig = next(f.fused_score for f in fused if f.record_id == rec.record_id)
                logger.debug(
                    "       %s decay=%.4f %.4f -> %.4f (delta=%+.4f)",
                    _fmt_record(rec),
                    (rec.fused_score or 0) / (orig or 1),
                    orig,
                    rec.fused_score,
                    rec.fused_score - orig,
                )
        else:
            logger.debug(
                "[pipeline] STEP=decay count=%d (no changes)",
                len(decayed),
            )
        for rec in sorted(decayed, key=lambda r: r.fused_score or 0, reverse=True):
            logger.debug("       %s", _fmt_record(rec))

        # ── Step 4: MMR Deduplication ──────────────────────────────────────
        mmr_selected = self._mmr.dedupe(decayed, query=query)
        logger.debug(
            "[pipeline] STEP=mmr count=%d lambda=%.2f final_k=%d threshold=%.2f",
            len(mmr_selected),
            self._mmr.mmr_lambda,
            self._mmr_final_k,
            self._mmr.mmr_duplicate_threshold,
        )
        for rec in sorted(mmr_selected, key=lambda r: r.fused_score or 0, reverse=True):
            logger.debug("       %s", _fmt_record(rec))

        # ── Step 5: Token Budget ──────────────────────────────────────────
        budget_selected = self._budget.select(mmr_selected)
        total_tokens = sum(r.token_count for r in budget_selected)
        logger.debug(
            "[pipeline] STEP=budget count=%d tokens=%d budget=%d",
            len(budget_selected),
            total_tokens,
            self._token_budget,
        )
        for rec in budget_selected:
            logger.debug(
                "       %s",
                _fmt_record(rec),
            )

        # ── Final Result ──────────────────────────────────────────────────
        result = PipelineResult(
            tenant_long_term=tenant_long,
            user_long_term=user_long,
            agent_short_term=self._to_search_result_list(budget_selected),
            final_memory_records=[self._to_search_result(r) for r in budget_selected],
        )
        logger.debug(
            "[pipeline] done: final=%d tenant=%d user=%d agent=%d",
            len(budget_selected),
            len(tenant_long),
            len(user_long),
            len(budget_selected),
        )
        return result

    def _split_by_layer(
        self,
        results: List[MemorySearchResult],
    ) -> tuple[List[MemorySearchResult], List[MemorySearchResult], List[MemorySearchResult]]:
        """Split a flat list of results into tenant / user / agent buckets."""
        tenant: List[MemorySearchResult] = []
        user: List[MemorySearchResult] = []
        agent: List[MemorySearchResult] = []
        for result in results:
            layer = result.layer
            if layer == MemoryLayer.TENANT:
                tenant.append(result)
            elif layer == MemoryLayer.USER:
                user.append(result)
            else:
                agent.append(result)
        return tenant, user, agent

    @staticmethod
    def _to_search_result(record: PipelineMemoryRecord) -> MemorySearchResult:
        """Convert a PipelineMemoryRecord back to MemorySearchResult."""
        return MemorySearchResult(
            memory_id=int(record.record_id) if record.record_id.isdigit() else None,
            external_id=record.record_id if record.is_external else None,
            content=record.content,
            score=record.fused_score if record.fused_score is not None else record.score,
            layer=record.layer,
            source="external" if record.is_external else "internal",
            is_external=record.is_external,
            metadata={
                "source": record.source.value,
                "memory_type": (record.memory_type.value if record.memory_type else None),
                "tenant_id": record.tenant_id,
                "user_id": record.user_id,
                "agent_id": record.agent_id,
                "conversation_id": record.conversation_id,
            },
        )

    @staticmethod
    def _to_search_result_list(
        records: List[PipelineMemoryRecord],
    ) -> List[MemorySearchResult]:
        """Convert a list of PipelineMemoryRecord to MemorySearchResult."""
        return [RetrievalPipeline._to_search_result(r) for r in records]


class PipelineResult:
    """Result of running the retrieval pipeline."""

    def __init__(
        self,
        tenant_long_term: List[MemorySearchResult],
        user_long_term: List[MemorySearchResult],
        agent_short_term: List[MemorySearchResult],
        final_memory_records: List[MemorySearchResult],
    ):
        self.tenant_long_term = tenant_long_term
        self.user_long_term = user_long_term
        self.agent_short_term = agent_short_term
        self.final_memory_records = final_memory_records

    def into_memory_search_context(self) -> MemorySearchContext:
        """Convert to the legacy MemorySearchContext format."""
        ctx = MemorySearchContext()
        ctx.tenant_long_term = self.tenant_long_term
        ctx.user_long_term = self.user_long_term
        ctx.agent_short_term = self.agent_short_term
        external = [r for r in self.agent_short_term if r.is_external]
        non_external_agent = [r for r in self.agent_short_term if not r.is_external]
        ctx.agent_short_term = non_external_agent
        ctx.external = external
        return ctx


__all__ = ["RetrievalPipeline", "PipelineResult", "enable_debug_logging"]
