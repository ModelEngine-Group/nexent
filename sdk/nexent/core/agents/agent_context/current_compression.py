"""Compression of the current run's action steps."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from smolagents.memory import ActionStep, TaskStep

from ..summary_cache import CompressionCallRecord, CurrentSummaryCache
from ..summary_config import ContextManagerConfig
from .budget import (
    action_fingerprint,
    is_curr_cache_valid,
    is_observation_step,
    is_tool_call_step,
    trim_actions_to_budget,
)
from .llm_summary import LLMSummary, SummaryResult
from .step_renderer import StepRenderer

logger = logging.getLogger("agent_context.current_compression")


@dataclass
class CurrentCompressResult:
    """Result from current-run compression."""
    summary_text: Optional[str] = None
    new_cache: Optional[CurrentSummaryCache] = None
    records: List[CompressionCallRecord] = field(default_factory=list)


class CurrentCompressor:
    """Compresses the current run's action steps with 3-tier strategy:
    1) Full cache hit
    2) Incremental compression (append new steps to old summary)
    3) Fresh compression with L2 trim and L3 fallback truncation
    """

    def __init__(self, config: ContextManagerConfig, renderer: StepRenderer, llm: LLMSummary):
        self.config = config
        self._renderer = renderer
        self._llm = llm

    def compress(
        self,
        curr_task: Optional[TaskStep],
        actions_to_compress: List[ActionStep],
        _cache: Optional[CurrentSummaryCache],
        model,
    ) -> CurrentCompressResult:
        """Compress current-run action steps, using cache when valid.

        Args:
            curr_task: The current TaskStep (may be None).
            actions_to_compress: ActionSteps from the current run.
            _cache: Current CurrentSummaryCache (may be None).
            model: LLM model for summary generation.

        Returns:
            CurrentCompressResult with summary_text, updated cache, and records.
        """
        cache = _cache  # alias to avoid Sonar false-positive on "unused"
        if not actions_to_compress:
            return CurrentCompressResult()

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
                    new_cache=cache,
                    records=[record],
                )

        # 2) Incremental compression
        if cache is not None and 0 < cache.end_steps < len(actions_to_compress):
            is_valid, _ = is_curr_cache_valid(actions_to_compress, cache)
            if is_valid:
                old_summary = cache.summary_text
                new_actions = actions_to_compress[cache.end_steps:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Steps\n{task_text}{self._renderer.actions_to_text(new_actions)}"
                )
                input_tokens = self._renderer.estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    result: SummaryResult = self._llm.generate_summary(
                        incremental_input, model,
                        call_type="current_incremental",
                        prompt_type="incremental",
                    )
                    if result.summary_text:
                        new_cache = CurrentSummaryCache(
                            summary_text=result.summary_text,
                            end_steps=len(actions_to_compress),
                            anchor_fingerprint=current_last_fp,
                        )
                        return CurrentCompressResult(
                            summary_text=result.summary_text,
                            new_cache=new_cache,
                            records=result.records,
                        )
                    return CurrentCompressResult(records=result.records)
                logger.info(
                    f"current incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), fallback to full compression or trimmed actions"
                )

        # 3) Fresh compression
        safe_actions = trim_actions_to_budget(
            actions_to_compress, task_text, self.config.max_summary_input_tokens,
            render_fn=self._renderer.actions_to_text,
        )
        is_full_coverage = (len(safe_actions) == len(actions_to_compress))
        if not is_full_coverage:
            logger.info(
                f"Current full summary trimmed {len(actions_to_compress) - len(safe_actions)} "
                f"oldest actions, still using cache"
            )

        actions_budget = max(0, self.config.max_summary_input_tokens - self._renderer.estimate_text_tokens(task_text))
        full_text = task_text + self._renderer.render_steps_with_truncation(
            safe_actions, fmt="action", max_tokens=actions_budget
        )
        result: SummaryResult = self._llm.generate_summary(
            full_text, model, call_type="current_summary"
        )
        if result.summary_text:
            new_cache = CurrentSummaryCache(
                summary_text=result.summary_text,
                end_steps=len(actions_to_compress),
                anchor_fingerprint=current_last_fp,
            )
            return CurrentCompressResult(
                summary_text=result.summary_text,
                new_cache=new_cache,
                records=result.records,
            )

        # L3 fallback
        reduced_actions = trim_actions_to_budget(
            actions_to_compress, task_text, self.config.max_summary_reduce_tokens,
            render_fn=self._renderer.actions_to_text,
        )
        actions_text = self._renderer.render_steps_with_truncation(
            reduced_actions, fmt="action", max_tokens=self.config.max_summary_reduce_tokens
        )
        fallback_text = (
            "[CONTEXT COMPACTION — REFERENCE ONLY] Some recent action steps were removed to free context space. "
            "Continue based on the remaining steps below.\n\n"
            f"Steps removed: {len(actions_to_compress) - len(reduced_actions)} of {len(actions_to_compress)}\n\n"
            "Remaining steps:\n"
            + actions_text
        )
        return CurrentCompressResult(
            summary_text=fallback_text,
            new_cache=None,
            records=result.records,
        )
