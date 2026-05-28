"""Previous run compression for ContextManager."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from smolagents.memory import ActionStep

from ..summary_cache import CompressionCallRecord, PreviousSummaryCache
from ...utils.token_estimation import estimate_tokens_text
from .budget import extract_pairs, action_content, pair_fingerprint, trim_pairs_to_budget
from .summary_step import SummaryTaskStep

logger = logging.getLogger("agent_context.previous_compression")


@dataclass
class PreviousCompressResult:
    """Result of a previous-run compression operation."""
    summary_text: Optional[str]
    new_cache: Optional[PreviousSummaryCache] = None  # None means no update
    records: List[CompressionCallRecord] = field(default_factory=list)


class PreviousCompressor:
    """Previous-run compression logic.

    Owns config, renderer, and llm references. Returns PreviousCompressResult
    with summary text, optional new cache, and records instead of mutating
    shared state.
    """

    def __init__(self, config, renderer, llm):
        self._config = config
        self._renderer = renderer
        self._llm = llm

    def compress(
        self, pairs_to_compress: List[tuple], cache: Optional[PreviousSummaryCache], model,
    ) -> PreviousCompressResult:
        """Compress previous-run pairs with cache-based optimization.

        Args:
            pairs_to_compress: List of (TaskStep, ActionStep) tuples to compress.
            cache: Current previous summary cache, or None.
            model: LLM model for summary generation.

        Returns:
            PreviousCompressResult with summary_text, optional new_cache, and records.
        """
        if not pairs_to_compress:
            return PreviousCompressResult(summary_text=None)

        # 1) Full cache hit
        if cache is not None and cache.covered_pairs == len(pairs_to_compress):
            anchor_t, anchor_a = pairs_to_compress[-1]
            fp = pair_fingerprint(
                anchor_t.task or "", action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                record = CompressionCallRecord(
                    call_type="previous_cache_hit", cache_hit=True,
                    details={"covered_pairs": cache.covered_pairs},
                )
                return PreviousCompressResult(
                    summary_text=cache.summary_text,
                    new_cache=None,
                    records=[record],
                )

        # 2) Incremental compression
        if (cache is not None
                and 0 < cache.covered_pairs < len(pairs_to_compress)):
            anchor_t, anchor_a = pairs_to_compress[cache.covered_pairs - 1]
            fp = pair_fingerprint(
                anchor_t.task or "", action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_pairs = pairs_to_compress[cache.covered_pairs:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Conversations\n{self._renderer.pairs_to_text(new_pairs)}"
                )
                input_tokens = estimate_tokens_text(incremental_input)
                if input_tokens <= self._config.max_summary_input_tokens:
                    llm_result = self._llm.generate_summary(
                        incremental_input, model,
                        call_type="previous_incremental", prompt_type="incremental"
                    )
                    if llm_result.summary_text:
                        last_t, last_a = pairs_to_compress[-1]
                        new_cache = PreviousSummaryCache(
                            summary_text=llm_result.summary_text,
                            covered_pairs=len(pairs_to_compress),
                            anchor_fingerprint=pair_fingerprint(
                                last_t.task or "", action_content(last_a)
                            ),
                        )
                        return PreviousCompressResult(
                            summary_text=llm_result.summary_text,
                            new_cache=new_cache,
                            records=llm_result.records,
                        )
                logger.info(
                    f"Incremental input {input_tokens} tokens exceeds budget "
                    f"({self._config.max_summary_input_tokens}), "
                    f"Falling back to full compression."
                )

        # 3) Fresh compression
        summary_text, is_cacheable, records = self._summarize_pairs(pairs_to_compress, model)
        new_cache = None
        if summary_text and is_cacheable:
            last_t, last_a = pairs_to_compress[-1]
            new_cache = PreviousSummaryCache(
                summary_text=summary_text,
                covered_pairs=len(pairs_to_compress),
                anchor_fingerprint=pair_fingerprint(
                    last_t.task or "", action_content(last_a)
                ),
            )
        # is_cacheable is False: PreviousSummaryCache kept as-is to avoid
        # incremental compression reusing a fallback cache that doesn't
        # represent a true summary.
        return PreviousCompressResult(
            summary_text=summary_text,
            new_cache=new_cache,
            records=records,
        )

    def _summarize_pairs(
        self, pairs: List[tuple], model,
    ) -> Tuple[Optional[str], bool, List[CompressionCallRecord]]:
        """Fresh compression entry point.

        Returns (summary_text, is_cacheable, records).

        L1 full summary -> (text, True, records)
        L2 trim summary -> (text, True, records)    # discard long-lived pairs, then summarize
        L3 trim origin  -> (text, False, records)   # LLM call failed, hard truncated
        """
        records: List[CompressionCallRecord] = []

        if not pairs:
            return None, False, records

        full_text = self._renderer.pairs_to_text(pairs)
        if estimate_tokens_text(full_text) <= self._config.max_summary_input_tokens:
            target_text = full_text
        else:
            trimmed_pairs = trim_pairs_to_budget(
                pairs, self._config.max_summary_input_tokens,
                render_fn=self._renderer.pairs_to_text, keep_first=False,
            )
            target_text = self._renderer.render_steps_with_truncation(
                trimmed_pairs, fmt="pair",
                max_tokens=self._config.max_summary_input_tokens,
                task_budget_chars=800, action_budget_chars=1500,
            )

        llm_result = self._llm.generate_summary(
            target_text, model, call_type="previous_summary", prompt_type="initial"
        )
        records.extend(llm_result.records)
        if llm_result.summary_text:
            return llm_result.summary_text, True, records
        logger.warning("previous full/truncated history summary generation failed, triggering L3 fallback truncation")

        reduced_pairs = trim_pairs_to_budget(
            pairs, self._config.max_summary_reduce_tokens,
            render_fn=self._renderer.pairs_to_text, keep_first=False,
        )
        reduced_text = self._renderer.render_steps_with_truncation(
            reduced_pairs, fmt="pair", max_tokens=self._config.max_summary_reduce_tokens,
        )
        first_task = pairs[0][0].task[:200] if pairs and pairs[0][0].task else ""
        fallback_text = (
            "[CONTEXT COMPACTION \u2014 REFERENCE ONLY] Earlier steps were removed to free context space. "
            "The removed content cannot be summarized. Continue based on the steps below.\n\n"
            f"Original task: {first_task}\n\n"
            f"Steps removed: {len(pairs) - len(reduced_pairs)} of {len(pairs)}\n\n"
            "Remaining compressed history:\n"
            + reduced_text
        )
        return fallback_text, False, records
