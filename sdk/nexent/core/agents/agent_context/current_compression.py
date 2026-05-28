"""Current run compression for ContextManager."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from smolagents.memory import ActionStep, TaskStep

from ..summary_cache import CompressionCallRecord, CurrentSummaryCache
from ...utils.token_estimation import estimate_tokens_text
from .budget import action_fingerprint, trim_actions_to_budget

logger = logging.getLogger("agent_context.current_compression")


@dataclass
class CurrentCompressResult:
    """Result of a current-run compression operation."""
    summary_text: Optional[str]
    new_cache: Optional[CurrentSummaryCache] = None  # None means no update
    records: List[CompressionCallRecord] = field(default_factory=list)


class CurrentCompressor:
    """Current-run compression logic.

    Owns config, renderer, and llm references. Returns CurrentCompressResult
    with summary text, optional new cache, and records instead of mutating
    shared state.
    """

    def __init__(self, config, renderer, llm):
        self._config = config
        self._renderer = renderer
        self._llm = llm

    def compress(
        self, curr_task: Optional[TaskStep], actions_to_compress: List[ActionStep],
        cache: Optional[CurrentSummaryCache], model,
    ) -> CurrentCompressResult:
        """Compress current-run actions with cache-based optimization.

        Args:
            curr_task: Current run's TaskStep, or None.
            actions_to_compress: List of ActionStep instances to compress.
            cache: Current current-run summary cache, or None.
            model: LLM model for summary generation.

        Returns:
            CurrentCompressResult with summary_text, optional new_cache, and records.
        """
        if not actions_to_compress:
            return CurrentCompressResult(summary_text=None)

        current_last_fp = action_fingerprint(actions_to_compress[-1])
        task_text = f"Current Task: {curr_task.task}\n\n" if curr_task else ""

        # 1) Full cache hit
        if cache is not None and cache.end_steps == len(actions_to_compress):
            if cache.anchor_fingerprint == current_last_fp:
                record = CompressionCallRecord(
                    call_type="current_cache_hit", cache_hit=True,
                    details={"end_steps": cache.end_steps},
                )
                return CurrentCompressResult(
                    summary_text=cache.summary_text,
                    new_cache=None,
                    records=[record],
                )

        # 2) Incremental compression
        if cache is not None and 0 < cache.end_steps < len(actions_to_compress):
            anchor_action = actions_to_compress[cache.end_steps - 1]
            if action_fingerprint(anchor_action) == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_actions = actions_to_compress[cache.end_steps:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Steps\n{task_text}{self._renderer.actions_to_text(new_actions)}"
                )
                input_tokens = estimate_tokens_text(incremental_input)
                if input_tokens <= self._config.max_summary_input_tokens:
                    llm_result = self._llm.generate_summary(
                        incremental_input, model,
                        call_type="current_incremental", prompt_type="incremental"
                    )
                    if llm_result.summary_text:
                        new_cache = CurrentSummaryCache(
                            summary_text=llm_result.summary_text,
                            end_steps=len(actions_to_compress),
                            anchor_fingerprint=current_last_fp,
                        )
                        return CurrentCompressResult(
                            summary_text=llm_result.summary_text,
                            new_cache=new_cache,
                            records=llm_result.records,
                        )
                logger.info(
                    f"current incremental input {input_tokens} tokens exceeds budget "
                    f"({self._config.max_summary_input_tokens}), fallback to full compression or trimmed actions"
                )

        # 3) Fresh compression: no cache or no valid cache or incremental input exceeds max_summary_input_tokens
        records: List[CompressionCallRecord] = []

        safe_actions = trim_actions_to_budget(
            actions_to_compress, task_text, self._config.max_summary_input_tokens,
            render_fn=self._renderer.actions_to_text,
        )
        is_full_coverage = (len(safe_actions) == len(actions_to_compress))
        if not is_full_coverage:
            logger.info(
                f"Current full summary trimmed {len(actions_to_compress) - len(safe_actions)} "
                f"oldest actions, still using cache"
            )

        actions_budget = max(0, self._config.max_summary_input_tokens - estimate_tokens_text(task_text))
        full_text = task_text + self._renderer.render_steps_with_truncation(
            safe_actions, fmt="action", max_tokens=actions_budget,
        )
        llm_result = self._llm.generate_summary(full_text, model, call_type="current_summary", prompt_type="initial")
        records.extend(llm_result.records)

        if llm_result.summary_text:
            new_cache = CurrentSummaryCache(
                summary_text=llm_result.summary_text,
                end_steps=len(actions_to_compress),
                anchor_fingerprint=current_last_fp,
            )
            return CurrentCompressResult(
                summary_text=llm_result.summary_text,
                new_cache=new_cache,
                records=records,
            )
        else:
            reduced_actions = trim_actions_to_budget(
                actions_to_compress, task_text, self._config.max_summary_reduce_tokens,
                render_fn=self._renderer.actions_to_text,
            )
            actions_text = self._renderer.render_steps_with_truncation(
                reduced_actions, fmt="action", max_tokens=self._config.max_summary_reduce_tokens,
            )
            fallback_text = (
                "[CONTEXT COMPACTION \u2014 REFERENCE ONLY] Some recent action steps were removed to free context space. "
                "Continue based on the remaining steps below.\n\n"
                f"Steps removed: {len(actions_to_compress) - len(reduced_actions)} of {len(actions_to_compress)}\n\n"
                "Remaining steps:\n"
                + actions_text
            )
            return CurrentCompressResult(
                summary_text=fallback_text,
                new_cache=None,
                records=records,
            )
