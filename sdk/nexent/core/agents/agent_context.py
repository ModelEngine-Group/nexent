"""Agent context management for memory compression and summarization.

Provides ContextManager for token-aware compression of agent memory,
supporting incremental summarization with cache-based optimization.

Also provides ContextManager as the single source of truth for:
- Context component registration and lifecycle
- System prompt assembly from components
- Strategy-based component selection
"""

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from .agent_model import ContextComponent, ContextStrategy

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage, MessageRole

from .summary_cache import CompressionCallRecord, CurrentSummaryCache, PreviousSummaryCache
from .summary_config import ContextManagerConfig, StrategyType
from ..context_runtime.contracts import ContextEvidence, FinalContext

logger = logging.getLogger("agent_context")

from ..utils.token_estimation import (
    _extract_text_from_messages,
    estimate_tokens,
    estimate_tokens_for_steps,
    msg_char_count,
    msg_token_count,
    estimate_tokens_for_system_prompt
)


@dataclass
class SummaryTaskStep(TaskStep):
    """TaskStep subclass that contains a compressed summary of earlier steps."""
    is_summary: bool = True
    prefix: str = "Summary of earlier steps in this task:"  # default prefix

    def to_messages(self, summary_mode: bool = False) -> list:
        content = [{"type": "text", "text": f"{self.prefix}:\n{self.task}"}]
        return [ChatMessage(role=MessageRole.USER, content=content)]


# ============================================================
#  Standalone utilities (no ContextManager state required)
# ============================================================

def format_summary_output(raw_output: str) -> Optional[str]:
    """Clean and validate LLM summary output.

    Strips markdown code fences, attempts JSON parse for normalization,
    falls back to plain text if not valid JSON.
    """
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        logger.warning("Summary output is not valid JSON; using as plain text")
        return cleaned


def _is_context_length_error(err: Exception) -> bool:
    """Check if an exception indicates a context length / token limit error."""
    msg = str(err).lower()
    return any(k in msg for k in (
        "context_length", "context length", "maximum context", "maximum context length",
        "prompt is too long", "reduce the length", "too many tokens",
        "token limit", "exceeds the maximum", "input is too long",
        "input length", "exceeds context", "context window",
    ))


def compress_history_offline(
    pairs: List[Tuple[str, str]],
    model,
    config: Optional[ContextManagerConfig] = None,
    previous_summary: Optional[str] = None,
) -> dict:
    """Compress conversation history offline, without ContextManager or AgentMemory.

    This is a standalone function for **Static Compression Inspection** in
    benchmarks. It takes plain-text (user, assistant) pairs and produces a
    summary using the same prompts and schema as the in-agent compression path,
    but without any stateful cache, offload store, or agent runtime.

    Args:
        pairs: List of (user_text, assistant_text) tuples representing
               conversation turns to compress.
        model: An LLM model object compatible with smolagents' call interface.
        config: ContextManagerConfig providing prompts, schema, and token budgets.
                Defaults to a fresh ContextManagerConfig() if not provided.
        previous_summary: Optional existing summary text for incremental
                          compression. If provided, uses the incremental prompt
                          to update rather than create from scratch.

    Returns:
        dict with:
          - "summary": the compressed summary text (str or None on failure)
          - "is_incremental": whether incremental compression was used
          - "is_fallback": whether the LLM failed and fallback truncation was used
          - "input_text": the raw text that was fed to the LLM (for debugging)
          - "input_chars": character count of the input text
    """
    config = config or ContextManagerConfig()
    # Same compensation as ContextManager.__init__: when max_summary_input_tokens
    # is left at the default 0, derive it from token_threshold so that truncation
    # logic doesn't accidentally chop all input.
    if config.max_summary_input_tokens <= 0:
        config.max_summary_input_tokens = int(config.token_threshold * 1.2)
    if not pairs and not previous_summary:
        return {
            "summary": None,
            "is_incremental": False,
            "is_fallback": False,
            "input_text": "",
            "input_chars": 0,
        }

    # Build input text from pairs
    parts = []
    for user_text, assistant_text in pairs:
        parts.append(f"user: {user_text}\nassistant: {assistant_text}")
    pairs_text = "\n\n".join(parts)

    # Determine compression mode
    is_incremental = previous_summary is not None

    if is_incremental:
        input_text = (
            f"## Previous Summary\n{previous_summary}\n\n"
            f"## New Conversations\n{pairs_text}"
        )
    else:
        input_text = pairs_text

    # Truncate if exceeds budget
    from ..utils.token_estimation import estimate_tokens_text
    input_tokens = estimate_tokens_text(input_text)
    if input_tokens > config.max_summary_input_tokens:
        # Simple tail-truncation for offline mode
        approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.9)
        input_text = "...[Earlier content truncated]...\n" + input_text[-approx_chars:]

    # Build prompt
    schema_desc = json.dumps(config.summary_json_schema, ensure_ascii=False, indent=2)
    if is_incremental:
        system_prompt = config.incremental_summary_system_prompt
        user_prompt = (
            f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
            f"{input_text}"
        )
    else:
        system_prompt = config.summary_system_prompt
        user_prompt = (
            f"Create a structured checkpoint summary following this JSON structure:\n{schema_desc}\n\n"
            f"TURNS TO SUMMARIZE:\n{input_text}"
        )

    messages = [
        ChatMessage(role=MessageRole.SYSTEM,
                    content=[{"type": "text", "text": system_prompt}]),
        ChatMessage(role=MessageRole.USER,
                    content=[{"type": "text", "text": user_prompt}]),
    ]

    # Call LLM with error handling
    is_fallback = False
    summary = None

    try:
        response = model(messages, stop_sequences=[])
        raw_output = response.content
        if isinstance(raw_output, list):
            raw_output = " ".join(
                block.get("text", "")
                for block in raw_output
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if not isinstance(raw_output, str):
            raw_output = str(raw_output)
        summary = format_summary_output(raw_output)
    except Exception as e:
        if _is_context_length_error(e):
            logger.warning("Offline compression exceeds context limit; retrying with 2/3 budget")
            approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.6)
            truncated_input = input_text[-approx_chars:] if len(input_text) > approx_chars else input_text
            if is_incremental:
                user_prompt = (
                    f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
                    f"{truncated_input}"
                )
            else:
                user_prompt = (
                    f"Create a structured checkpoint summary following this JSON structure:\n{schema_desc}\n\n"
                    f"TURNS TO SUMMARIZE:\n{truncated_input}"
                )
            messages[-1] = ChatMessage(
                role=MessageRole.USER,
                content=[{"type": "text", "text": user_prompt}],
            )
            try:
                response = model(messages, stop_sequences=[])
                raw_output = response.content
                if isinstance(raw_output, list):
                    raw_output = " ".join(
                        block.get("text", "")
                        for block in raw_output
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                if not isinstance(raw_output, str):
                    raw_output = str(raw_output)
                summary = format_summary_output(raw_output)
            except Exception as e2:
                logger.error(f"Offline compression retry still failed: {e2}")

        if summary is None:
            # L3 fallback: hard truncation
            is_fallback = True
            first_task = pairs[0][0][:200] if pairs else ""
            reduced_chars = int(config.max_summary_reduce_tokens * config.chars_per_token)
            reduced_text = pairs_text[-reduced_chars:] if len(pairs_text) > reduced_chars else pairs_text
            summary = (
                "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier steps were removed to free context space. "
                "The removed content cannot be summarized. Continue based on the steps below.\n\n"
                f"Original task: {first_task}\n\n"
                f"Steps removed: {len(pairs)} of {len(pairs)}\n\n"
                "Remaining compressed history:\n"
                + reduced_text
            )

    return {
        "summary": summary,
        "is_incremental": is_incremental,
        "is_fallback": is_fallback,
        "input_text": input_text,
        "input_chars": len(input_text),
    }


class ContextManager:
    def __init__(self, config: Optional[ContextManagerConfig] = None, max_steps: Optional[int] = None):
        self.config = config or ContextManagerConfig()
        self._previous_summary_cache: Optional[PreviousSummaryCache] = None
        self._current_summary_cache: Optional[CurrentSummaryCache] = None

        self._last_run_start_idx: Optional[int] = None

        if max_steps is not None and self.config.keep_recent_steps >= max_steps:
            self.config.keep_recent_steps = max_steps

        self.compression_calls_log: List[CompressionCallRecord] = []
        self._step_local_log: List[CompressionCallRecord] = []
        self._lock = threading.Lock()

        # Token accounting for benchmark instrumentation.
        # Recorded by compress_if_needed at each return point so benchmarks
        # can compute token_reduction = 1 - last_compressed / last_uncompressed.
        self._last_uncompressed_token_count: Optional[int] = None
        self._last_compressed_token_count: Optional[int] = None

        # W3 prompt/KV-cache-aware assembly state.  This state is owned by
        # ContextManager so managed runtime and CoreAgent do not infer context
        # structure from the outside.
        self._run_component_messages: List[dict] = []
        self._run_stable_messages: List[dict] = []
        self._run_dynamic_messages: List[dict] = []
        self._previous_stable_fingerprint: Optional[str] = None
        self._previous_stable_components: Dict[str, str] = {}

        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)

        self._components: List = []

    # ============================================================
    #  Cache validation
    # ============================================================

    def _is_prev_cache_valid(self, prev_pairs: List[tuple]) -> Tuple[bool, int]:
        """Checks whether the previous cache covers a prefix of prev_pairs.

        Returns (is_valid, covered_idx). When is_valid is True, prev_pairs[0:covered_idx]
        can be replaced by cache.summary_text, and prev_pairs[covered_idx:] represents
        the uncovered incremental portion.
        """
        cache = self._previous_summary_cache
        if cache is None or not prev_pairs:
            return False, 0
        if cache.covered_pairs == 0 or cache.covered_pairs > len(prev_pairs):
            return False, 0
        anchor_t, anchor_a = prev_pairs[cache.covered_pairs - 1]
        fp = self._pair_fingerprint(anchor_t.task or "", self._action_content(anchor_a))
        if fp != cache.anchor_fingerprint:
            return False, 0
        return True, cache.covered_pairs

    def _is_curr_cache_valid(self, action_steps: List[ActionStep]) -> Tuple[bool, int]:
        cache = self._current_summary_cache
        if cache is None or not action_steps:
            return False, 0
        if cache.end_steps == 0 or cache.end_steps > len(action_steps):
            return False, 0
        anchor = action_steps[cache.end_steps - 1]
        if self._action_fingerprint(anchor) != cache.anchor_fingerprint:
            return False, 0
        return True, cache.end_steps

    # ============================================================
    #  Effective token estimation
    # ============================================================

    def _effective_tokens(self, memory: AgentMemory, current_run_start_idx: int) -> int:
        """Estimates the actual token burden of the upcoming _build_messages call.
        Uses summary_text for the covered prefix when cache is valid; falls back to raw otherwise.
        """
        system_prompt_tokens = estimate_tokens_for_system_prompt(memory)
        prev_steps = memory.steps[:current_run_start_idx]
        curr_steps = memory.steps[current_run_start_idx:]
        return (system_prompt_tokens + self._effective_prev_tokens(prev_steps)
                + self._effective_curr_tokens(curr_steps))

    def _effective_prev_tokens(self, prev_steps: List[MemoryStep]) -> int:
        if not prev_steps:
            return 0
        prev_pairs = self._extract_pairs(prev_steps)
        is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
        if not is_valid:
            return self._estimate_tokens_for_steps(prev_steps)
        uncovered = prev_pairs[covered_idx:]
        uncovered_tokens = (
            self._estimate_text_tokens(self._pairs_to_text(uncovered))
            if uncovered else 0
        )
        return (self._estimate_text_tokens(self._previous_summary_cache.summary_text)
                + uncovered_tokens)

    def _effective_curr_tokens(self, curr_steps: List[MemoryStep]) -> int:
        if not curr_steps:
            return 0
        curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
        action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
        is_valid, covered_idx = self._is_curr_cache_valid(action_steps)
        if not is_valid:
            return self._estimate_tokens_for_steps(curr_steps)
        task_tokens = (
            self._estimate_text_tokens(curr_task.task or "") if curr_task else 0
        )
        uncovered = action_steps[covered_idx:]
        uncovered_tokens = (
            self._estimate_text_tokens(self._actions_to_text(uncovered))
            if uncovered else 0
        )
        return (task_tokens
                + self._estimate_text_tokens(self._current_summary_cache.summary_text)
                + uncovered_tokens)

    # ============================================================
    #  Budget helpers
    # ============================================================

    def _estimate_text_tokens(self, text: str) -> int:
        from ..utils.token_estimation import estimate_tokens_text
        return estimate_tokens_text(text)

    def _trim_pairs_to_budget(
        self, pairs: List[tuple], max_tokens: int, keep_first: bool = True,
    ) -> List[tuple]:
        if not pairs:
            return []
        pair_tokens = [
            self._estimate_text_tokens(self._pairs_to_text([p])) for p in pairs
        ]
        sep = self._estimate_text_tokens("\n\n")
        total = sum(pair_tokens) + sep * max(0, len(pairs) - 1)
        if total <= max_tokens:
            return list(pairs)

        if keep_first and len(pairs) > 1:
            budget = max_tokens - pair_tokens[0] - sep
            kept_tail = []
            for i in range(len(pairs) - 1, 0, -1):
                cost = pair_tokens[i] + (sep if kept_tail else 0)
                if cost > budget:
                    break
                kept_tail.append(pairs[i])
                budget -= cost
            return [pairs[0]] + list(reversed(kept_tail))

        budget = max_tokens
        kept = []
        for i in range(len(pairs) - 1, -1, -1):
            cost = pair_tokens[i] + (sep if kept else 0)
            if cost > budget:
                break
            kept.append(pairs[i])
            budget -= cost
        return list(reversed(kept)) if kept else [pairs[-1]]



    def _is_observation_step(self, action: ActionStep) -> bool:
        return action is not None and hasattr(action, 'observations') and action.observations is not None

    def _is_tool_call_step(self, action: ActionStep) -> bool:
        return action is not None and hasattr(action, 'tool_calls') and action.tool_calls is not None

    def _trim_actions_to_budget(
        self, actions: List[ActionStep], task_text: str, max_tokens: int,
    ) -> List[ActionStep]:
        if not actions:
            return []

        def _total_tokens(acts):
            return self._estimate_text_tokens(task_text + self._actions_to_text(acts))

        if _total_tokens(actions) <= max_tokens:
            return list(actions)

        for drop in range(1, len(actions) + 1):
            remaining = actions[drop:]
            if not remaining:
                break
            if self._is_observation_step(remaining[0]) and self._is_tool_call_step(actions[drop - 1]):
                continue
            if _total_tokens(remaining) <= max_tokens:
                return list(remaining)

        return self._fallback_trim_actions(actions)

    def _fallback_trim_actions(self, actions: List[ActionStep]) -> List[ActionStep]:
        last_action = actions[-1]
        if len(actions) >= 2 and self._is_observation_step(last_action):
            prev_action = actions[-2]
            if self._is_tool_call_step(prev_action):
                logger.warning(
                    "Fallback limit triggered: Retaining the last complete ToolCall + Observation pair intact. "
                    "This may exceed the token budget, and downstream truncation will be relied upon."
                )
                return [prev_action, last_action]
        return [last_action]
    
    # ============================================================
    #  Mainly Entry Point
    # ============================================================

    def _soft_input_budget_tokens(self) -> int:
        return self.config.soft_input_budget_tokens or self.config.token_threshold

    def _hard_input_budget_tokens(self) -> int:
        return self.config.hard_input_budget_tokens or int(self.config.token_threshold * 1.1)

    def compress_if_needed(
        self,
        model,
        memory,
        original_messages: List[ChatMessage],
        current_run_start_idx,
        context_overhead_tokens: int = 0,
    ) -> List[ChatMessage]:
        # G1
        if not self.config.enabled:
            return original_messages

        soft_input_budget_tokens = self._soft_input_budget_tokens()
        hard_input_budget_tokens = self._hard_input_budget_tokens()
        soft_history_budget_tokens = max(0, soft_input_budget_tokens - context_overhead_tokens)
        hard_history_budget_tokens = max(0, hard_input_budget_tokens - context_overhead_tokens)

        if self._estimate_tokens(memory) <= soft_history_budget_tokens:
            # No compression needed; record that compressed == uncompressed
            # so benchmark token_reduction reads as zero rather than stale.
            self._last_uncompressed_token_count = self._msg_token_count(original_messages)
            self._last_compressed_token_count = self._last_uncompressed_token_count
            return original_messages

        with self._lock:
            # Run detection
            if (self._last_run_start_idx is not None
                    and current_run_start_idx != self._last_run_start_idx):
                self._current_summary_cache = None
            self._last_run_start_idx = current_run_start_idx

            # Note: The memory here always consists of the unmodified, summary-task-step-free
            # original previous_run + current_run.
            # - previous_run: [(TaskStep, ActionStep), ...]
            # - current_run:  [TaskStep, ActionStep, ActionStep, ...]
            if self._effective_tokens(memory, current_run_start_idx) <= soft_history_budget_tokens:
                # Stable-phase bypass: No LLM call; construct compressed messages directly from existing cache.
                self._step_local_log.clear()

                prev_steps = memory.steps[:current_run_start_idx]
                curr_steps = memory.steps[current_run_start_idx:]

                prev_summary_step = None
                prev_tail_steps = list(prev_steps)
                prev_pairs = self._extract_pairs(prev_steps)
                if prev_pairs:
                    is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
                    if is_valid:
                        prev_summary_step = SummaryTaskStep(
                            task=self._previous_summary_cache.summary_text
                        )
                        uncovered = prev_pairs[covered_idx:]
                        prev_tail_steps = self._pairs_to_steps(uncovered)

                curr_kept_steps = list(curr_steps)
                if curr_steps:
                    curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                    curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
                    if curr_action_steps:
                        is_valid, covered_idx = self._is_curr_cache_valid(curr_action_steps)
                        if is_valid:
                            uncovered = curr_action_steps[covered_idx:]
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
                                + list(uncovered)
                            )

                record = CompressionCallRecord(
                    call_type="stable_bypass", cache_hit=True,
                    details={"reason": "stable_period_effective_under_threshold"},
                )
                self.compression_calls_log.append(record)
                self._step_local_log.append(record)

                compressed_msgs = self._build_messages(
                    memory, prev_summary_step, prev_tail_steps, curr_kept_steps
                )
                self._last_uncompressed_token_count = self._msg_token_count(original_messages)
                self._last_compressed_token_count = self._msg_token_count(compressed_msgs)
                return compressed_msgs

            self._step_local_log.clear()

            self._last_uncompressed_token_count = self._msg_token_count(original_messages)

            prev_steps = memory.steps[:current_run_start_idx]
            curr_steps = memory.steps[current_run_start_idx:]

            prev_tokens = self._effective_prev_tokens(prev_steps)
            curr_tokens = self._effective_curr_tokens(curr_steps)

            compress_prev = prev_tokens > soft_history_budget_tokens * 0.6
            compress_curr = curr_tokens > soft_history_budget_tokens * 0.4

            total_effective_tokens = prev_tokens + curr_tokens + context_overhead_tokens
            if compress_prev or compress_curr:
                logger.info(
                    f"Context compression triggered: total_tokens={total_effective_tokens}, "
                    f"soft_budget={soft_input_budget_tokens}, "
                    f"hard_budget={hard_input_budget_tokens}, "
                    f"context_overhead_tokens={context_overhead_tokens}, "
                    f"prev_tokens={prev_tokens} (compress={compress_prev}), "
                    f"curr_tokens={curr_tokens} (compress={compress_curr})"
                )

            # --------------- Previous phase ---------------
            prev_summary_step: Optional[SummaryTaskStep] = None
            prev_tail_steps: List[MemoryStep] = list(prev_steps)
            prev_pairs = self._extract_pairs(prev_steps)

            if compress_prev and prev_pairs:
                keep_n = min(self.config.keep_recent_pairs, len(prev_pairs))
                pairs_to_compress = prev_pairs[:-keep_n] if keep_n > 0 else prev_pairs
                pairs_to_keep = prev_pairs[-keep_n:] if keep_n > 0 else []
                if pairs_to_compress:
                    summary_text = self._compress_previous_with_cache(
                        pairs_to_compress, model
                    )
                    if summary_text:
                        if "[CONTEXT COMPACTION" in summary_text:
                            prev_summary_step = SummaryTaskStep(task=summary_text, prefix="Context fallback, Truncated raw history:")
                        else:
                            prev_summary_step = SummaryTaskStep(task=summary_text)
                        prev_tail_steps = self._pairs_to_steps(pairs_to_keep)
            elif prev_pairs:
                # if cache is valid, use cache + uncovered display
                is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
                if is_valid:
                    prev_summary_step = SummaryTaskStep(
                        task=self._previous_summary_cache.summary_text
                    )
                    uncovered = prev_pairs[covered_idx:]
                    prev_tail_steps = self._pairs_to_steps(uncovered)

            # --------------- Current phase ---------------
            curr_kept_steps: List[MemoryStep] = list(curr_steps)

            if curr_steps:
                curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]

                if compress_curr and curr_action_steps:
                    keep_n = min(self.config.keep_recent_steps, len(curr_action_steps))
                    if keep_n > 0 and keep_n < len(curr_action_steps):
                        boundary = curr_action_steps[-keep_n]
                        prev_a = curr_action_steps[-keep_n - 1]
                        if (getattr(boundary, "observations", None) is not None
                                and getattr(prev_a, "tool_calls", None) is not None):
                            keep_n += 1

                    actions_to_compress = (
                        curr_action_steps[:-keep_n] if keep_n > 0 else list(curr_action_steps)
                    )
                    actions_to_keep = (
                        curr_action_steps[-keep_n:] if keep_n > 0 else []
                    )
                    if actions_to_compress:
                        curr_summary_text = self._compress_current_with_cache(
                            curr_task, actions_to_compress, model
                        )
                        if curr_summary_text:
                            if "[CONTEXT COMPACTION" in curr_summary_text:
                                curr_summary_step = SummaryTaskStep(task=curr_summary_text, prefix="Truncated recent action steps:")
                            else:
                                curr_summary_step = SummaryTaskStep(task=curr_summary_text)
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [curr_summary_step]
                                + list(actions_to_keep)
                            )
                elif curr_action_steps:
                    is_valid, covered_idx = self._is_curr_cache_valid(curr_action_steps)
                    if is_valid:
                        uncovered = curr_action_steps[covered_idx:]
                        curr_kept_steps = (
                            ([curr_task] if curr_task else [])
                            + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
                            + list(uncovered)
                        )

            final_messages = self._build_messages(
                memory, prev_summary_step, prev_tail_steps, curr_kept_steps
            )
            final_tokens = self._msg_token_count(final_messages)
            self._last_compressed_token_count = final_tokens
            # This situation is unlikely to occur unless the threshold itself is set unreasonably small
            if final_tokens > hard_history_budget_tokens:
                logger.warning(
                    f"Still exceeds hard input budget after compression: {final_tokens} > {hard_input_budget_tokens}. "
                    f"Consider reducing keep_recent_pairs ({self.config.keep_recent_pairs}) "
                    f"or keep_recent_steps({self.config.keep_recent_steps})"
                )
            return final_messages

    # ============================================================
    #  Previous Compression
    # ============================================================

    def _extract_pairs(self, steps):
        pairs = []
        i = 0
        while i < len(steps):
            if isinstance(steps[i], TaskStep) and not isinstance(steps[i], SummaryTaskStep):
                if i + 1 < len(steps) and isinstance(steps[i + 1], ActionStep):
                    pairs.append((steps[i], steps[i + 1]))
                    i += 2
                    continue
            i += 1
        return pairs

    def _compress_previous_with_cache(
        self, pairs_to_compress: List[tuple], model,
    ) -> Optional[str]:
        if not pairs_to_compress:
            return None

        cache = self._previous_summary_cache
        if cache is not None and cache.covered_pairs == len(pairs_to_compress):
            anchor_t, anchor_a = pairs_to_compress[-1]
            fp = self._pair_fingerprint(
                anchor_t.task or "", self._action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                record = CompressionCallRecord(
                    call_type="previous_cache_hit", cache_hit=True,
                    details={"covered_pairs": cache.covered_pairs},
                )
                self.compression_calls_log.append(record)
                self._step_local_log.append(record)
                return cache.summary_text

        # ===== Incremental Compression Path =====
        if (cache is not None
                and 0 < cache.covered_pairs < len(pairs_to_compress)):
            anchor_t, anchor_a = pairs_to_compress[cache.covered_pairs - 1]
            fp = self._pair_fingerprint(
                anchor_t.task or "", self._action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_pairs = pairs_to_compress[cache.covered_pairs:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Conversations\n{self._pairs_to_text(new_pairs)}"
                )
                input_tokens = self._estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    summary_text = self._generate_summary(
                        incremental_input, model,
                        call_type="previous_incremental",
                        prompt_type="incremental",
                    )
                    if summary_text:
                        last_t, last_a = pairs_to_compress[-1]
                        self._previous_summary_cache = PreviousSummaryCache(
                            summary_text=summary_text,
                            covered_pairs=len(pairs_to_compress),
                            anchor_fingerprint=self._pair_fingerprint(
                                last_t.task or "", self._action_content(last_a)
                            ),
                        )
                        return summary_text
                logger.info(
                    f"Incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), "
                    f"Falling back to full compression."
                )

        # Fresh compression
        summary_text, is_cacheable = self._summarize_pairs(pairs_to_compress, model)
        # summary_text is valid, not None
        if summary_text and is_cacheable:
            last_t, last_a = pairs_to_compress[-1]
            self._previous_summary_cache = PreviousSummaryCache(
                summary_text=summary_text,
                covered_pairs=len(pairs_to_compress),
                anchor_fingerprint=self._pair_fingerprint(
                    last_t.task or "", self._action_content(last_a)
                ),
            )
        # is_cacheable is False, PreviousSummaryCache keep as is
        return summary_text

    def _action_content(self, action: ActionStep) -> str:
        return action.action_output or getattr(action, "output", "") or ""

    def _pair_fingerprint(self, task_content: str, action_content: str) -> str:
        raw = (task_content[-200:] + action_content[-200:])
        return hashlib.md5(raw.encode()).hexdigest()

    def _summarize_pairs(
        self, pairs: List[tuple], model,
    ) -> Tuple[Optional[str], bool]:
        """Fresh compression entry point, returns (summary, is_cacheable).

        L1 full summary -> (text, True)
        L2 trim summary -> (text, True)    # discard long-lived pairs, then summarize
        L3 trim origin  -> (text, False)   # LLM call failed, hard truncated, no summary returned
        """
        if not pairs:
            return None, False

        full_text = self._pairs_to_text(pairs)
        if self._estimate_text_tokens(full_text) <= self.config.max_summary_input_tokens:
            target_text = full_text 
        else:
            trimmed_pairs = self._trim_pairs_to_budget(
                pairs, self.config.max_summary_input_tokens, keep_first=False
            )
            target_text = self._render_steps_with_truncation(
                trimmed_pairs, fmt="pair", 
                max_tokens=self.config.max_summary_input_tokens,
                task_budget_chars=800, action_budget_chars=1500
            )
        
        summary_text = self._generate_summary(target_text, model, call_type="previous_summary")
        if summary_text:
            return summary_text, True 
        logger.warning("previous full/truncated history summary generation failed, triggering L3 fallback truncation")
        
        reduced_pairs = self._trim_pairs_to_budget(pairs, self.config.max_summary_reduce_tokens, False)
        reduced_text = self._render_steps_with_truncation(
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
        return fallback_text, False


    # ============================================================
    #  Current compression
    # ============================================================

    def _compress_current_with_cache(
        self, curr_task: Optional[TaskStep], actions_to_compress: List[ActionStep], model,
    ) -> Optional[str]:
        if not actions_to_compress:
            return None

        current_last_fp = self._action_fingerprint(actions_to_compress[-1])
        task_text = f"Current Task: {curr_task.task}\n\n" if curr_task else ""
        cache = self._current_summary_cache
        # 1) Full cache hit
        if cache is not None and cache.end_steps == len(actions_to_compress):
            if cache.anchor_fingerprint == current_last_fp:
                record = CompressionCallRecord(
                    call_type="current_cache_hit", cache_hit=True,
                    details={"end_steps": cache.end_steps},
                )
                self.compression_calls_log.append(record)
                self._step_local_log.append(record)
                return cache.summary_text
            
        # 2) Incremental compression
        if cache is not None and 0 < cache.end_steps < len(actions_to_compress):
            anchor_action = actions_to_compress[cache.end_steps - 1]
            if self._action_fingerprint(anchor_action) == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_actions = actions_to_compress[cache.end_steps:]
                incremental_input = (
                    f"## Previous Summary\n{old_summary}\n\n"
                    f"## New Steps\n{task_text}{self._actions_to_text(new_actions)}"
                )
                input_tokens = self._estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    summary_text = self._generate_summary(
                        incremental_input, model,
                        call_type="current_incremental",
                        prompt_type="incremental",
                    )
                    if summary_text:
                        self._current_summary_cache = CurrentSummaryCache(
                            summary_text=summary_text,
                            end_steps=len(actions_to_compress),
                            anchor_fingerprint=current_last_fp,
                        )
                        return summary_text
                logger.info(
                    f"current incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), fallback to full compression or trimmed actions"
                )


        # 3) Fresh compression: no cache or no valid cache or incremental input exceeds max_summary_input_tokens
        safe_actions = self._trim_actions_to_budget(
            actions_to_compress, task_text, self.config.max_summary_input_tokens,
        )
        is_full_coverage = (len(safe_actions) == len(actions_to_compress))
        if not is_full_coverage:
            logger.info(
                f"Current full summary trimmed {len(actions_to_compress) - len(safe_actions)} "
                f"oldest actions, still using cache"
            )

        actions_budget = max(0, self.config.max_summary_input_tokens - self._estimate_text_tokens(task_text))
        full_text = task_text + self._render_steps_with_truncation(
            safe_actions, fmt="action", max_tokens=actions_budget
        )
        summary_text = self._generate_summary(full_text, model, call_type="current_summary")
        if summary_text:
            self._current_summary_cache = CurrentSummaryCache(
                summary_text=summary_text,
                end_steps=len(actions_to_compress),
                anchor_fingerprint=current_last_fp,
            )
            return summary_text
        else:
            reduced_actions = self._trim_actions_to_budget(
                actions_to_compress, task_text, self.config.max_summary_reduce_tokens
            )
            actions_text = self._render_steps_with_truncation(
                reduced_actions, fmt="action", max_tokens=self.config.max_summary_reduce_tokens
            )
            fallback_text = (
                "[CONTEXT COMPACTION — REFERENCE ONLY] Some recent action steps were removed to free context space. "
                "Continue based on the remaining steps below.\n\n"
                f"Steps removed: {len(actions_to_compress) - len(reduced_actions)} of {len(actions_to_compress)}\n\n"
                "Remaining steps:\n"
                + actions_text
            )
            return fallback_text

    def _actions_to_text(self, actions: List[ActionStep]) -> str:
        parts = []
        for i, step in enumerate(actions):
            text = self._render_action_step(step)
            parts.append(f"[Step {step.step_number or i+1}]\n{text}")
        return "\n\n".join(parts)

    def _render_steps_with_truncation(
        self,
        steps: List,
        fmt: str = "action",
        max_tokens: int = None,
        min_budget_chars: int = 80,
        task_budget_chars: int = 800,
        action_budget_chars: int = None,
    ) -> str:
        if max_tokens is None:
            max_tokens = self.config.max_summary_input_tokens
        if action_budget_chars is None:
            action_budget_chars = self.config.max_memory_step_length

        entries = self._build_step_entries(steps, fmt)
        raw_text = "\n\n".join(task + action for task, action in entries)
        if self._estimate_text_tokens(raw_text) <= max_tokens:
            return raw_text

        return self._truncate_entries_to_budget(entries, max_tokens, min_budget_chars, task_budget_chars, action_budget_chars)

    def _build_step_entries(self, steps: List, fmt: str) -> List[Tuple[str, str]]:
        entries = []
        for step in steps:
            if fmt == "action":
                text = f"[Step {step.step_number or '?'}]\n{self._render_action_step(step)}"
                entries.append(("", text))
            else:
                task_step, action_step = step
                task_str = f"user: {task_step.task or ''}\nassistant: "
                action_str = self._render_action_step(action_step)
                entries.append((task_str, action_str))
        return entries

    def _truncate_entries_to_budget(
        self, entries: List[Tuple[str, str]], max_tokens: int,
        min_budget_chars: int, task_budget_chars: int, action_budget_chars: int,
    ) -> str:
        t_budget = task_budget_chars
        a_budget = action_budget_chars
        all_text = ""

        while True:
            parts = [self._truncate_entry(e, t_budget, a_budget) for e in entries]
            all_text = "\n\n".join(parts)

            if self._estimate_text_tokens(all_text) <= max_tokens:
                break

            t_budget, a_budget = self._reduce_budgets(t_budget, a_budget, min_budget_chars)
            if t_budget == min_budget_chars and a_budget == min_budget_chars:
                break

        return all_text

    def _truncate_entry(self, entry: Tuple[str, str], task_budget: int, action_budget: int) -> str:
        task_str, action_str = entry
        task_trunc = self._truncate_text(task_str, task_budget) if task_str else ""
        action_trunc = self._truncate_text(action_str, action_budget)
        return task_trunc + action_trunc

    def _truncate_text(self, text: str, max_len: int, mark: str = "...[Truncated]") -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len - len(mark)] + mark

    def _reduce_budgets(self, t_budget: int, a_budget: int, min_budget: int) -> Tuple[int, int]:
        if a_budget > min_budget:
            return t_budget, max(min_budget, int(a_budget * 0.8))
        if t_budget > min_budget:
            return max(min_budget, int(t_budget * 0.8)), a_budget
        return t_budget, a_budget

    def _actions_to_text_with_limit(self, actions: List[ActionStep], prefill_tokens: int = 0) -> str:
        rendered_steps = []
        for i, step in enumerate(actions):
            prefix = f"[Step {step.step_number or i+1}]\n"
            content = self._render_action_step(step)
            rendered_steps.append((prefix, content))
        budget_per_action = self.config.max_memory_step_length

        while True:
            parts = [] 
            
            for prefix, content in rendered_steps:
                if len(content) > budget_per_action:
                    text = f"{prefix}{content[:budget_per_action]}\n\n[System Note: Step content too long, partially truncated]"
                else:
                    text = f"{prefix}{content}"
                parts.append(text)
                
            all_text = "\n\n".join(parts)

            if self._estimate_text_tokens(all_text) + prefill_tokens <= self.config.max_summary_input_tokens:
                break 
            budget_per_action = int(budget_per_action * 0.9)
            
            if budget_per_action < 50:
                logger.warning(
                    f"Per-step compression budget has reached minimum threshold "
                    f"(budget={budget_per_action}), possibly due to excessively long preset prompts. "
                    f"Forcing return of truncated result."
                )
                break
        return all_text

    @staticmethod
    def _action_fingerprint(action: ActionStep) -> str:
        raw = (
            str(action.step_number or "")
            + (action.model_output or "")[-200:]
            + (
                action.action_output if isinstance(action.action_output, str)
                else str(action.action_output) if action.action_output else ""
            )[-200:]
        )
        return hashlib.md5(raw.encode()).hexdigest()

    # ============================================================
    #  LLM call
    # ============================================================

    def _is_context_length_error(self, err: Exception) -> bool:
        return _is_context_length_error(err)

    def _generate_summary(self, text: str, model, call_type: str = "summary",
                          prompt_type: str = "initial") -> Optional[str]:
        try:
            return self._do_generate_summary(text, model, call_type, prompt_type)
        except Exception as e:
            if self._is_context_length_error(e):
                logger.warning(f"{call_type} exceeds context limit; retrying with 2/3 budget truncation")
                shrunk = self._truncate_text_to_tokens(
                    text, int(self.config.max_summary_input_tokens * 0.66)
                )
                try:
                    return self._do_generate_summary(shrunk, model, call_type + "_retry", prompt_type)
                except Exception as e2:
                    self._record_failed_compression(call_type + "_retry_failed", str(e2))
                    logger.error(f"Retry still failed: {e2}")
                    return None
            self._record_failed_compression(call_type + "_failed", str(e))
            logger.error(f"Summary generation exception: {e}")
            return None

    def _record_failed_compression(self, call_type: str, error_msg: str):
        """Record a failed compression attempt so stats reflect actual compression triggers."""

        record = CompressionCallRecord(
            call_type=call_type,
            input_tokens=0,
            output_tokens=0,
            input_chars=0,
            output_chars=0,
            cache_hit=False,
            details={"error": error_msg},
        )
        self.compression_calls_log.append(record)
        self._step_local_log.append(record)

    def _do_generate_summary(self, text: str, model, call_type: str = "summary",
                             prompt_type: str = "initial") -> Optional[str]:
        # prompt_type selects which system prompt to render. For "incremental"
        # we use the dedicated incremental_summary_system_prompt (with fallback
        # to summary_system_prompt if it is empty) and a user prompt phrased
        # as an update; "initial" keeps the original fresh-compaction phrasing.
        if prompt_type == "incremental":
            system_prompt = (
                self.config.incremental_summary_system_prompt
                or self.config.summary_system_prompt
            )
        else:
            system_prompt = self.config.summary_system_prompt

        schema_desc = json.dumps(
            self.config.summary_json_schema, ensure_ascii=False, indent=2
        )
        if prompt_type == "incremental":
            # text already contains the "## Previous Summary" + "## New ..."
            # sections; the prompt only needs to instruct the update.
            user_prompt = (
                f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
                f"{text}"
            )
        else:
            user_prompt = (
                f"Output a summary following this JSON structure:\n{schema_desc}\n\n"
                f"Conversation content to summarize:\n{text}"
            )
        messages = [
            ChatMessage(role=MessageRole.SYSTEM,
                        content=[{"type": "text", "text": system_prompt}]),
            ChatMessage(role=MessageRole.USER,
                        content=[{"type": "text", "text": user_prompt}]),
        ]
        response = model(messages, stop_sequences=[])

        raw_output = response.content
        if isinstance(raw_output, list):
            raw_output = " ".join(
                block.get("text", "")
                for block in raw_output
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if not isinstance(raw_output, str):
            raw_output = str(raw_output)

        summary = self._format_summary(raw_output)
        self._record_llm_call_token(
            input_len=self._msg_char_count(messages),
            output_len=len(raw_output),
            response=response, call_type=call_type,
        )
        return summary


    def _record_llm_call_token(self, input_len, output_len, response, call_type):
        record = CompressionCallRecord(
            call_type=call_type,
            input_tokens=getattr(getattr(response, "token_usage", None), "input_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "token_usage", None), "output_tokens", 0) or 0,
            input_chars=input_len, output_chars=output_len,
        )
        self.compression_calls_log.append(record)
        self._step_local_log.append(record)

    def _format_summary(self, raw_output: str) -> Optional[str]:
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        if not cleaned:
            return None
        try:
            parsed = json.loads(cleaned)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            logger.warning("Summary output is not valid JSON; using as plain text")
            return cleaned

    def _render_action_step(self, action: ActionStep) -> str:
        msgs = action.to_messages(summary_mode=False)
        return _extract_text_from_messages(msgs) or ""

    def _truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        if self._estimate_text_tokens(text) <= max_tokens:
            return text
        units = text.split("\n\n")
        kept, total = [], 0
        for u in reversed(units):
            u_tokens = self._estimate_text_tokens(u)
            if total + u_tokens > max_tokens and kept:
                break
            kept.append(u)
            total += u_tokens
        result = "...[Earlier content truncated]...\n\n" + "\n\n".join(reversed(kept))
        if self._estimate_text_tokens(result) > max_tokens:
            approx_chars = int(max_tokens * self.config.chars_per_token * 0.9)
            result = "...[Earlier content truncated]...\n" + result[:approx_chars]
        return result

    def _pairs_to_text(self, pairs: List[tuple]) -> str:
        parts = []
        for i, (task_step, action_step) in enumerate(pairs):
            task_text = task_step.task or ""
            action_text = self._render_action_step(action_step)
            parts.append(f"user: {task_text}\nassistant: {action_text}")
        return "\n\n".join(parts)

    def _pairs_to_steps(self, pairs: List[tuple]) -> List[MemoryStep]:
        steps = []
        for task_step, action_step in pairs:
            steps.append(task_step)
            steps.append(action_step)
        return steps

    def _build_messages(
        self, memory: AgentMemory,
        prev_summary_step: Optional[SummaryTaskStep],
        prev_tail_steps: List[MemoryStep],
        curr_kept_steps: List[MemoryStep],
    ) -> List[ChatMessage]:
        result = []
        if memory.system_prompt:
            result.extend(memory.system_prompt.to_messages())
        if prev_summary_step:
            result.extend(prev_summary_step.to_messages())
        for step in prev_tail_steps:
            result.extend(step.to_messages())
        for step in curr_kept_steps:
            result.extend(step.to_messages())
        return result

    # ============================================================
    #  Token Estimation
    # ============================================================

    def _estimate_tokens_for_steps(self, steps):
        return estimate_tokens_for_steps(steps, self.config.chars_per_token)

    def _estimate_tokens(self, memory: AgentMemory) -> int:
        return estimate_tokens(memory, self.config.chars_per_token)

    def _msg_char_count(self, msg: Union[ChatMessage, List[ChatMessage]]) -> int:
        return msg_char_count(msg)

    def _msg_token_count(self, msg):
        return msg_token_count(msg, self.config.chars_per_token)

    def get_step_compression_stats(self) -> dict:
        with self._lock:
            if not self._step_local_log:
                return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}
            cache_types = [r.call_type for r in self._step_local_log if r.cache_hit]
            return {
                "calls": len([r for r in self._step_local_log if not r.cache_hit]),
                "input_tokens": sum(r.input_tokens for r in self._step_local_log),
                "output_tokens": sum(r.output_tokens for r in self._step_local_log),
                "input_chars": sum(r.input_chars for r in self._step_local_log),
                "output_chars": sum(r.output_chars for r in self._step_local_log),
                "cache_hits": sum(1 for r in self._step_local_log if r.cache_hit),
                "cache_types": cache_types,
            }

    def get_all_compression_stats(self) -> dict:
        with self._lock:
            real_calls = [r for r in self.compression_calls_log if not r.cache_hit]
            return {
                "total_calls": len(real_calls),
                "total_attempts": len(self.compression_calls_log),
                "total_input_tokens": sum(r.input_tokens for r in real_calls),
                "total_output_tokens": sum(r.output_tokens for r in real_calls),
                "total_cache_hits": sum(1 for r in self.compression_calls_log if r.cache_hit),
            }

    # ============================================================
    #  Benchmark export APIs
    # ============================================================

    def build_compressed_snapshot(
        self, model, memory: AgentMemory, current_run_start_idx: int,
    ) -> Tuple[List[ChatMessage], dict]:
        """Build a frozen compressed message snapshot for probe evaluation.

        Returns (compressed_messages, metadata) without modifying internal
        cache state. This enables the Probe Evaluation pattern where each
        probe runs independently against a frozen compressed snapshot.

        metadata contains: token counts, which caches were used, and summary export.
        """
        saved_prev_cache = self._previous_summary_cache
        saved_curr_cache = self._current_summary_cache
        saved_step_log = list(self._step_local_log)
        saved_calls_log = list(self.compression_calls_log)

        try:
            original_messages = memory.system_prompt.to_messages() if memory.system_prompt else []
            for step in memory.steps:
                original_messages.extend(step.to_messages())

            compressed_messages = self.compress_if_needed(
                model, memory, original_messages, current_run_start_idx
            )

            metadata = {
                "token_counts": self.get_token_counts(),
                "summary": self.export_summary(),
                "compression_stats": self.get_step_compression_stats(),
            }
            return compressed_messages, metadata
        finally:
            self._previous_summary_cache = saved_prev_cache
            self._current_summary_cache = saved_curr_cache
            self._step_local_log = saved_step_log
            self.compression_calls_log = saved_calls_log

    def get_token_counts(self) -> dict:
        """Return token counts from the most recent compression pass.

        Returns a dict with ``last_uncompressed`` and ``last_compressed`` token
        counts, enabling accurate ``token_reduction = 1 - compressed/uncompressed``
        measurement in benchmarks. Values are None before the first compress_if_needed
        call on this instance.
        """
        with self._lock:
            return {
                "last_uncompressed": self._last_uncompressed_token_count,
                "last_compressed": self._last_compressed_token_count,
            }

    def export_summary(self) -> dict:
        """Export current compression summary state for benchmark inspection.

        Returns a dict with the cached summary texts, cache metadata, and a
        compression_boundary block describing which pairs/steps fed the
        summary versus which were retained verbatim. Benchmarks use the
        boundary block to validate probe design: probes should only target
        information that was actually compressed.
        """
        with self._lock:
            prev_cache = self._previous_summary_cache
            curr_cache = self._current_summary_cache
            return {
                "previous_summary": prev_cache.summary_text if prev_cache else None,
                "current_summary": curr_cache.summary_text if curr_cache else None,
                "previous_cache_info": (
                    {
                        "covered_pairs": prev_cache.covered_pairs,
                        "is_fallback": "[CONTEXT COMPACTION" in (prev_cache.summary_text or ""),
                    }
                    if prev_cache else None
                ),
                "current_cache_info": (
                    {
                        "end_steps": curr_cache.end_steps,
                        "is_fallback": "[CONTEXT COMPACTION" in (curr_cache.summary_text or ""),
                    }
                    if curr_cache else None
                ),
                "compression_boundary": {
                    "config_keep_recent_pairs": self.config.keep_recent_pairs,
                    "config_keep_recent_steps": self.config.keep_recent_steps,
                    "previous_compressed_pairs": (
                        prev_cache.covered_pairs if prev_cache else 0
                    ),
                    "previous_retained_pairs": self.config.keep_recent_pairs,
                    "current_compressed_steps": (
                        curr_cache.end_steps if curr_cache else 0
                    ),
                    "current_retained_steps": self.config.keep_recent_steps,
                },
            }

    # ============================================================
    #  Managed Context Assembly (W3)
    # ============================================================

    def prepare_run_context(self, memory: AgentMemory, fallback_system_prompt: str) -> None:
        """Initialize managed run context.

        ContextManager owns the selected component messages and the stable prefix.
        Runtime adapters must not split, reorder, or reinterpret these messages.
        """
        from smolagents.memory import SystemPromptStep

        self._run_component_messages = self.build_context_messages()
        self._run_stable_messages = [
            message for message in self._run_component_messages
            if self._message_role(message) in {"system", "developer"}
        ]
        self._run_dynamic_messages = [
            message for message in self._run_component_messages
            if self._message_role(message) not in {"system", "developer"}
        ]

        stable_text = "\n\n".join(
            str(message.get("content", "")) for message in self._run_stable_messages
        )
        memory.system_prompt = SystemPromptStep(
            system_prompt=stable_text or fallback_system_prompt
        )

    def assemble_final_context(
        self,
        *,
        model: Any,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
        purpose: str = "step",
        task: Optional[str] = None,
        final_answer_templates: Optional[Dict[str, Any]] = None,
    ) -> FinalContext:
        """Return the only managed-path payload allowed to enter a model call.

        This is the W3 boundary: component selection, stable-prefix preservation,
        dynamic context insertion, compression budget compensation, final-answer
        augmentation, tool canonicalization, and evidence generation all happen
        here, inside ContextManager.
        """
        if not self._run_component_messages:
            self.prepare_run_context(memory, fallback_system_prompt="")

        tools = self._canonical_tools(tools or ())
        purpose_stable, purpose_dynamic = self._purpose_messages(
            purpose=purpose,
            task=task,
            final_answer_templates=final_answer_templates,
        )

        original_messages = self._messages_from_memory(memory)
        stable_messages = [*self._run_stable_messages, *purpose_stable]
        dynamic_messages = [*self._run_dynamic_messages, *purpose_dynamic]

        context_overhead_tokens = (
            self._msg_token_count(dynamic_messages)
            + self._estimate_tools_tokens(tools)
            + self._msg_token_count(purpose_stable)
        )
        compressed_messages = self.compress_if_needed(
            model,
            memory,
            original_messages,
            current_run_start_idx,
            context_overhead_tokens=context_overhead_tokens,
        )
        history_messages = self._without_leading_stable_messages(compressed_messages)
        messages = [
            *stable_messages,
            *dynamic_messages,
            *history_messages,
        ]

        self._last_compressed_token_count = self._msg_token_count(messages) + self._estimate_tools_tokens(tools)

        fingerprint = self._fingerprint({"messages": stable_messages, "tools": tools})
        component_fingerprints = self._stable_component_fingerprints(purpose_stable)
        if tools:
            component_fingerprints["tools"] = self._fingerprint(tools)
        reasons = self._change_reasons(fingerprint, component_fingerprints)
        self._previous_stable_fingerprint = fingerprint
        self._previous_stable_components = component_fingerprints

        return FinalContext(
            messages=messages,
            tools=tools,
            evidence=ContextEvidence(
                selected_component_types=tuple(
                    getattr(component, "component_type", "unknown")
                    for component in self.get_registered_components()
                ),
                stable_message_count=len(stable_messages),
                dynamic_message_count=len(messages) - len(stable_messages),
                compression_records=tuple(self._step_local_log or ()),
                stable_prefix_fingerprint=fingerprint,
                prefix_change_reasons=tuple(reasons),
            ),
        )

    def _purpose_messages(
        self,
        *,
        purpose: str,
        task: Optional[str],
        final_answer_templates: Optional[Dict[str, Any]],
    ) -> Tuple[List[dict], List[dict]]:
        if purpose != "final_answer":
            return [], []
        if not final_answer_templates:
            raise ValueError("final_answer purpose requires final_answer_templates")
        from jinja2 import StrictUndefined, Template

        final_answer = final_answer_templates["final_answer"]
        pre_messages = final_answer.get("pre_messages", "")
        post_messages = Template(
            final_answer.get("post_messages", ""),
            undefined=StrictUndefined,
        ).render(task=task or "")
        return (
            [{"role": "developer", "content": pre_messages}],
            [{"role": "user", "content": post_messages}],
        )

    @staticmethod
    def _messages_from_memory(memory: AgentMemory) -> List[Any]:
        messages: List[Any] = []
        if memory.system_prompt:
            messages.extend(memory.system_prompt.to_messages())
        for step in memory.steps:
            messages.extend(step.to_messages())
        return messages

    @classmethod
    def _without_leading_stable_messages(cls, messages: Sequence[Any]) -> List[Any]:
        remaining = list(messages)
        while remaining and cls._message_role(remaining[0]) in {"system", "developer"}:
            remaining.pop(0)
        return remaining

    @staticmethod
    def _canonical_tools(tools: Sequence[Any]) -> List[Any]:
        return sorted(
            tools,
            key=lambda tool: json.dumps(
                ContextManager._normalize_for_fingerprint(tool),
                sort_keys=True,
                default=str,
            ),
        )

    def _estimate_tools_tokens(self, tools: Sequence[Any]) -> int:
        if not tools:
            return 0
        return self._estimate_text_tokens(
            json.dumps(self._normalize_for_fingerprint(tools), ensure_ascii=False, sort_keys=True, default=str)
        )

    @staticmethod
    def _message_role(message: Any) -> Optional[str]:
        if isinstance(message, dict):
            return message.get("role")
        role = getattr(message, "role", None)
        return getattr(role, "value", role)

    @staticmethod
    def _normalize_for_fingerprint(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): ContextManager._normalize_for_fingerprint(item)
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, (list, tuple)):
            return [ContextManager._normalize_for_fingerprint(item) for item in value]
        if hasattr(value, "model_dump"):
            return ContextManager._normalize_for_fingerprint(value.model_dump())
        if hasattr(value, "__dict__"):
            return ContextManager._normalize_for_fingerprint(vars(value))
        return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)

    def _fingerprint(self, messages: Sequence[Any]) -> str:
        encoded = json.dumps(
            self._normalize_for_fingerprint(messages),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _stable_component_fingerprints(self, purpose_stable: Sequence[Any] = ()) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for component in self.get_registered_components():
            to_messages = getattr(component, "to_messages", None)
            if not callable(to_messages):
                continue
            stable = [
                message for message in to_messages()
                if self._message_role(message) in {"system", "developer"}
            ]
            if stable:
                result[str(getattr(component, "component_type", "unknown"))] = self._fingerprint(stable)
        if purpose_stable:
            result["purpose"] = self._fingerprint(purpose_stable)
        return result

    def _change_reasons(
        self, current: str, component_fingerprints: Dict[str, str]
    ) -> List[str]:
        if self._previous_stable_fingerprint is None:
            return ["initial_request"]
        if self._previous_stable_fingerprint == current:
            return []
        if self._previous_stable_components.get("tools") != component_fingerprints.get("tools"):
            return ["tool_schema_version"]
        if self._previous_stable_components.get("purpose") != component_fingerprints.get("purpose"):
            return ["context_purpose"]
        if self._previous_stable_components != component_fingerprints:
            return ["system_prompt_version"]
        return ["unexpected_nondeterminism"]

    # ============================================================
    #  Context Component Management
    # ============================================================

    def register_component(self, component) -> None:
        """Register a context component for system prompt assembly.
        
        Components are accumulated and used by build_system_prompt().
        
        Args:
            component: A ContextComponent instance (e.g., ToolsComponent,
                       MemoryComponent, KnowledgeBaseComponent).
        """
        with self._lock:
            if component.token_estimate == 0:
                component.token_estimate = component.estimate_tokens(
                    self.config.chars_per_token
                )
            self._components.append(component)

    def clear_components(self) -> None:
        """Clear all registered context components.
        
        Typically called at the start of a new agent run.
        """
        with self._lock:
            self._components.clear()

    def get_registered_components(self) -> List:
        """Return copy of registered components."""
        with self._lock:
            return list(self._components)

    def replace_components(self, components: List) -> None:
        """Atomically replace all registered components.
        
        Clears existing components and registers new ones under a single
        lock acquisition, preventing race conditions when the ContextManager
        is shared across concurrent runs (e.g., conversation-level CM reuse).
        
        Args:
            components: List of ContextComponent instances to register.
                       Pass empty list to clear all components.
        """
        with self._lock:
            self._components.clear()
            for component in components:
                if component.token_estimate == 0:
                    component.token_estimate = component.estimate_tokens(
                        self.config.chars_per_token
                    )
                self._components.append(component)

    def _get_strategy(self):
        """Factory method to get strategy instance based on config."""
        from .agent_model import (
            FullStrategy, TokenBudgetStrategy, BufferedStrategy, PriorityWeightedStrategy
        )
        strategy_map = {
            "full": FullStrategy,
            "token_budget": TokenBudgetStrategy,
            "buffered": BufferedStrategy,
            "priority": PriorityWeightedStrategy,
        }
        strategy_class = strategy_map.get(self.config.strategy, TokenBudgetStrategy)
        
        if self.config.strategy == "buffered":
            return strategy_class(buffer_size=self.config.buffer_size_per_component)
        elif self.config.strategy == "priority":
            return strategy_class(relevance_threshold=0.5)
        return strategy_class()

    def build_context_messages(self, token_budget: Optional[int] = None) -> List:
        """Build all selected component messages for the managed context path.
        
        Uses configured strategy to select components within token budget,
        then converts each to message format.
        
        Args:
            token_budget: Maximum tokens for all components. Defaults to
                          config.component_budgets total minus conversation_history.
        
        Returns:
            List of message dicts with 'role' and 'content' keys.  Roles are
            preserved: dynamic components such as Memory and KB are intentionally
            returned as ``user`` messages rather than being coerced into a
            system prompt.
        """
        if not self._components:
            return []
        
        from .agent_model import SystemPromptComponent
        
        budget = token_budget or self._calculate_component_budget()
        strategy = self._get_strategy()
        selected = strategy.select_components(
            self._components, budget, self.config.component_budgets
        )
        
        messages = []
        for comp in selected:
            comp_messages = comp.to_messages()
            for msg in comp_messages:
                if not self._message_already_present(messages, msg):
                    messages.append(msg)
        
        return messages

    def build_system_prompt(self, token_budget: Optional[int] = None) -> List:
        """Compatibility alias for callers not yet migrated to managed assembly.

        New code must call :meth:`build_context_messages`; this alias preserves
        historical tests and external callers without reintroducing a
        system-only filtering rule.
        """
        return self.build_context_messages(token_budget)

    def _calculate_component_budget(self) -> int:
        """Calculate total token budget for components (excluding conversation_history)."""
        budgets = self.config.component_budgets
        excluded = ["conversation_history"]
        return sum(v for k, v in budgets.items() if k not in excluded)

    def _message_already_present(self, messages: List, new_msg: dict) -> bool:
        """Check if identical message already exists."""
        for existing in messages:
            if existing.get("role") == new_msg.get("role") and existing.get("content") == new_msg.get("content"):
                return True
        return False
