"""Compression of previous run's (TaskStep, ActionStep) pairs."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..summary_cache import CompressionCallRecord, PreviousSummaryCache
from ..summary_config import ContextManagerConfig
from .budget import (
    action_content,
    is_prev_cache_valid,
    pair_fingerprint,
    trim_pairs_to_budget,
)
from .llm_summary import LLMSummary, SummaryResult
from .step_renderer import StepRenderer

logger = logging.getLogger("agent_context.previous_compression")


@dataclass
class PreviousCompressResult:
    """Result from previous-run compression."""
    summary_text: Optional[str] = None
    new_cache: Optional[PreviousSummaryCache] = None
    records: List[CompressionCallRecord] = field(default_factory=list)


class PreviousCompressor:
    """Compresses previous run's (TaskStep, ActionStep) pairs with 3-tier strategy:
    1) Full cache hit
    2) Incremental compression (append new pairs to old summary)
    3) Fresh compression with L2 trim-summary and L3 fallback truncation
    """

    def __init__(self, config: ContextManagerConfig, renderer: StepRenderer, llm: LLMSummary):
        self.config = config
        self._renderer = renderer
        self._llm = llm

    def compress(
        self,
        pairs_to_compress: List[tuple],
        _cache: Optional[PreviousSummaryCache],
        model,
    ) -> PreviousCompressResult:
        """Compress previous-run pairs, using cache when valid.

        Args:
            pairs_to_compress: List of (TaskStep, ActionStep) tuples to compress.
            _cache: Current PreviousSummaryCache (may be None).
            model: LLM model for summary generation.

        Returns:
            PreviousCompressResult with summary_text, updated cache, and records.
        """
        cache = _cache  # alias to avoid Sonar false-positive on "unused"
        if not pairs_to_compress:
            return PreviousCompressResult()

        # 1) Full cache hit
        if cache is not None and cache.covered_pairs == len(pairs_to_compress):
            anchor_t, anchor_a = pairs_to_compress[-1]
            fp = pair_fingerprint(anchor_t.task or "", action_content(anchor_a))
            if fp == cache.anchor_fingerprint:
                record = CompressionCallRecord(
                    call_type="previous_cache_hit", cache_hit=True,
                    details={"covered_pairs": cache.covered_pairs},
                )
                return PreviousCompressResult(
                    summary_text=cache.summary_text,
                    new_cache=cache,
                    records=[record],
                )

        # 2) Incremental compression
        if cache is not None and 0 < cache.covered_pairs < len(pairs_to_compress):
            is_valid, _ = is_prev_cache_valid(pairs_to_compress, cache)
            if is_valid:
                old_summary = cache.summary_text
                new_pairs = pairs_to_compress[cache.covered_pairs:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Conversations\n{self._renderer.pairs_to_text(new_pairs)}"
                )
                input_tokens = self._renderer.estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    result: SummaryResult = self._llm.generate_summary(
                        incremental_input, model,
                        call_type="previous_incremental",
                        prompt_type="incremental",
                    )
                    if result.summary_text:
                        last_t, last_a = pairs_to_compress[-1]
                        new_cache = PreviousSummaryCache(
                            summary_text=result.summary_text,
                            covered_pairs=len(pairs_to_compress),
                            anchor_fingerprint=pair_fingerprint(
                                last_t.task or "", action_content(last_a)
                            ),
                        )
                        return PreviousCompressResult(
                            summary_text=result.summary_text,
                            new_cache=new_cache,
                            records=result.records,
                        )
                    return PreviousCompressResult(records=result.records)
                logger.info(
                    f"Incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), "
                    f"Falling back to full compression."
                )

        # 3) Fresh compression
        return self._summarize_pairs(pairs_to_compress, model, cache)

    def _summarize_pairs(
        self,
        pairs: List[tuple],
        model,
        cache: Optional[PreviousSummaryCache] = None,
    ) -> PreviousCompressResult:
        """Fresh compression entry point.

        L1 full summary -> (text, cacheable)
        L2 trim summary -> (text, cacheable)
        L3 trim origin  -> (text, not cacheable)
        """
        if not pairs:
            return PreviousCompressResult()

        full_text = self._renderer.pairs_to_text(pairs)
        if self._renderer.estimate_text_tokens(full_text) <= self.config.max_summary_input_tokens:
            target_text = full_text
        else:
            trimmed_pairs = trim_pairs_to_budget(
                pairs, self.config.max_summary_input_tokens,
                render_fn=self._renderer.pairs_to_text,
                keep_first=False,
            )
            target_text = self._renderer.render_steps_with_truncation(
                trimmed_pairs, fmt="pair",
                max_tokens=self.config.max_summary_input_tokens,
                task_budget_chars=800, action_budget_chars=1500,
            )

        result: SummaryResult = self._llm.generate_summary(
            target_text, model, call_type="previous_summary"
        )
        if result.summary_text:
            last_t, last_a = pairs[-1]
            new_cache = PreviousSummaryCache(
                summary_text=result.summary_text,
                covered_pairs=len(pairs),
                anchor_fingerprint=pair_fingerprint(
                    last_t.task or "", action_content(last_a)
                ),
            )
            return PreviousCompressResult(
                summary_text=result.summary_text,
                new_cache=new_cache,
                records=result.records,
            )

        # L3 fallback
        logger.warning("previous full/truncated history summary generation failed, triggering L3 fallback truncation")
        reduced_pairs = trim_pairs_to_budget(
            pairs, self.config.max_summary_reduce_tokens,
            render_fn=self._renderer.pairs_to_text,
            keep_first=False,
        )
        reduced_text = self._renderer.render_steps_with_truncation(
            reduced_pairs, fmt="pair", max_tokens=self.config.max_summary_reduce_tokens
        )
        first_task = pairs[0][0].task[:200] if pairs and pairs[0][0].task else ""
        fallback_text = (
            "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier steps were removed to free context space. "
            "The removed content cannot be summarized. Continue based on the steps below.\n\n"
            f"Original task: {first_task}\n\n"
            f"Steps removed: {len(pairs) - len(reduced_pairs)} of {len(pairs)}\n\n"
            "Remaining compressed history:\n"
            + reduced_text
        )
        return PreviousCompressResult(
            summary_text=fallback_text,
            new_cache=None,
            records=result.records,
        )
