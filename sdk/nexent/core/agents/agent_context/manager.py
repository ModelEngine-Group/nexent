"""ContextManager: agent memory context management and compression.

Composes sub-components (StepRenderer, LLMSummary, PreviousCompressor,
CurrentCompressor) and pure functions (budget, stats_export) to provide
full compression functionality. The main entry point is
``compress_if_needed()`` which orchestrates previous/current compression
phases with cache-based optimization.
"""

import logging
import threading
from typing import List, Optional

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage

from ..summary_cache import CompressionCallRecord, CurrentSummaryCache, PreviousSummaryCache
from ..summary_config import ContextManagerConfig, StrategyType
from .budget import (
    extract_pairs, is_prev_cache_valid, is_curr_cache_valid,
    trim_pairs_to_budget, trim_actions_to_budget,
)
from .current_compression import CurrentCompressor
from .llm_summary import LLMSummary
from .offload_store import OffloadStore
from .previous_compression import PreviousCompressor
from .stats_export import (
    get_step_compression_stats, get_all_compression_stats,
    export_summary, get_token_counts,
)
from .step_renderer import StepRenderer
from .summary_step import SummaryTaskStep
from ...utils.token_estimation import estimate_tokens, estimate_tokens_for_system_prompt, estimate_tokens_for_steps, estimate_tokens_text, msg_token_count

logger = logging.getLogger("agent_context")


class ContextManager:
    """Agent memory context management and compression.

    Orchestrates token-aware compression of agent memory, supporting
    incremental summarization with cache-based optimization.

    Composes (not inherits) sub-components. Owns all state and
    delegates computation to pure functions and sub-component methods.
    """

    def __init__(self, config: Optional[ContextManagerConfig] = None, max_steps: Optional[int] = None):
        self.config = config or ContextManagerConfig()

        # --- Owned state ---
        self._previous_summary_cache: Optional[PreviousSummaryCache] = None
        self._current_summary_cache: Optional[CurrentSummaryCache] = None

        # Run boundary self-detection. The current cache fingerprint is only reused
        # within the current run and must be explicitly cleared at the start of a new run.
        # The previous cache is managed and updated across runs.
        self._last_run_start_idx: Optional[int] = None

        if max_steps is not None and self.config.keep_recent_steps >= max_steps:
            self.config.keep_recent_steps = max_steps

        self.compression_calls_log: List[CompressionCallRecord] = []
        self._step_local_log: List[CompressionCallRecord] = []
        self._lock = threading.Lock()
        self._offload_store = OffloadStore(max_entries=self.config.max_offload_entries)
        self._last_uncompressed_token_count: Optional[int] = None
        self._last_compressed_token_count: Optional[int] = None

        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)

        # --- Composed sub-components ---
        self._renderer = StepRenderer(self.config, self._offload_store)
        self._llm = LLMSummary(self.config, self._renderer)
        self._prev_compressor = PreviousCompressor(self.config, self._renderer, self._llm)
        self._curr_compressor = CurrentCompressor(self.config, self._renderer, self._llm)

        self._components: List = []

    @property
    def offload_store(self) -> OffloadStore:
        return self._offload_store

    # ============================================================
    #  Effective token estimation (orchestration-level, uses state)
    # ============================================================

    def _effective_tokens(self, memory: AgentMemory, current_run_start_idx: int) -> int:
        """Estimates the actual token burden of the upcoming build_messages call."""
        system_prompt_tokens = estimate_tokens_for_system_prompt(memory)
        prev_steps = memory.steps[:current_run_start_idx]
        curr_steps = memory.steps[current_run_start_idx:]
        return (system_prompt_tokens + self._effective_prev_tokens(prev_steps)
                + self._effective_curr_tokens(curr_steps))

    def _effective_prev_tokens(self, prev_steps: List[MemoryStep]) -> int:
        if not prev_steps:
            return 0
        prev_pairs = extract_pairs(prev_steps)
        is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
        if not is_valid:
            return estimate_tokens_for_steps(prev_steps, self.config.chars_per_token)
        uncovered = prev_pairs[covered_idx:]
        uncovered_tokens = (
            estimate_tokens_text(self._renderer.pairs_to_text(uncovered))
            if uncovered else 0
        )
        return (estimate_tokens_text(self._previous_summary_cache.summary_text)
                + uncovered_tokens)

    def _effective_curr_tokens(self, curr_steps: List[MemoryStep]) -> int:
        if not curr_steps:
            return 0
        curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
        action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
        is_valid, covered_idx = is_curr_cache_valid(action_steps, self._current_summary_cache)
        if not is_valid:
            return estimate_tokens_for_steps(curr_steps, self.config.chars_per_token)
        task_tokens = (
            estimate_tokens_text(curr_task.task or "") if curr_task else 0
        )
        uncovered = action_steps[covered_idx:]
        uncovered_tokens = (
            estimate_tokens_text(self._renderer.actions_to_text(uncovered))
            if uncovered else 0
        )
        return (task_tokens
                + estimate_tokens_text(self._current_summary_cache.summary_text)
                + uncovered_tokens)

    # ============================================================
    #  Main Entry Point
    # ============================================================

    def compress_if_needed(
        self, model, memory, original_messages: List[ChatMessage], current_run_start_idx,
    ) -> List[ChatMessage]:
        if not self.config.enabled:
            return original_messages

        if estimate_tokens(memory, self.config.chars_per_token) <= self.config.token_threshold:
            self._last_uncompressed_token_count = msg_token_count(original_messages, self.config.chars_per_token)
            self._last_compressed_token_count = self._last_uncompressed_token_count
            return original_messages

        with self._lock:
            # Run detection
            if (self._last_run_start_idx is not None
                    and current_run_start_idx != self._last_run_start_idx):
                self._current_summary_cache = None
                self._offload_store.clear()
            self._last_run_start_idx = current_run_start_idx

            # Note: The memory here always consists of the unmodified, summary-task-step-free
            # original previous_run + current_run.
            # - previous_run: [(TaskStep, ActionStep), ...]
            # - current_run:  [TaskStep, ActionStep, ActionStep, ...]
            if self._effective_tokens(memory, current_run_start_idx) <= self.config.token_threshold:
                # Stable-phase bypass: No LLM call; construct compressed messages directly from existing cache.
                self._step_local_log.clear()

                prev_steps = memory.steps[:current_run_start_idx]
                curr_steps = memory.steps[current_run_start_idx:]

                prev_summary_step = None
                prev_tail_steps = list(prev_steps)
                prev_pairs = extract_pairs(prev_steps)
                if prev_pairs:
                    is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
                    if is_valid:
                        prev_summary_step = SummaryTaskStep(
                            task=self._previous_summary_cache.summary_text,
                            prefix="Summary of earlier steps in this task:",
                        )
                        uncovered = prev_pairs[covered_idx:]
                        prev_tail_steps = self._renderer.pairs_to_steps(uncovered)

                curr_kept_steps = list(curr_steps)
                if curr_steps:
                    curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                    curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
                    if curr_action_steps:
                        is_valid, covered_idx = is_curr_cache_valid(curr_action_steps, self._current_summary_cache)
                        if is_valid:
                            uncovered = curr_action_steps[covered_idx:]
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [SummaryTaskStep(task=self._current_summary_cache.summary_text, prefix="Summary of earlier steps in this task:")]
                                + list(uncovered)
                            )

                record = CompressionCallRecord(
                    call_type="stable_bypass", cache_hit=True,
                    details={"reason": "stable_period_effective_under_threshold"},
                )
                self.compression_calls_log.append(record)
                self._step_local_log.append(record)

                compressed_msgs = self._renderer.build_messages(
                    memory, prev_summary_step, prev_tail_steps, curr_kept_steps
                )
                self._last_compressed_token_count = msg_token_count(compressed_msgs, self.config.chars_per_token)
                return compressed_msgs

            self._step_local_log.clear()

            self._last_uncompressed_token_count = msg_token_count(original_messages, self.config.chars_per_token)

            prev_steps = memory.steps[:current_run_start_idx]
            curr_steps = memory.steps[current_run_start_idx:]

            prev_tokens = self._effective_prev_tokens(prev_steps)
            curr_tokens = self._effective_curr_tokens(curr_steps)

            compress_prev = prev_tokens > self.config.token_threshold * 0.6
            compress_curr = curr_tokens > self.config.token_threshold * 0.4

            total_effective_tokens = prev_tokens + curr_tokens
            if compress_prev or compress_curr:
                logger.info(
                    f"Context compression triggered: total_tokens={total_effective_tokens}, "
                    f"threshold={self.config.token_threshold}, "
                    f"prev_tokens={prev_tokens} (compress={compress_prev}), "
                    f"curr_tokens={curr_tokens} (compress={compress_curr})"
                )

            # --------------- Previous phase ---------------
            prev_summary_step: Optional[SummaryTaskStep] = None
            prev_tail_steps: List[MemoryStep] = list(prev_steps)
            prev_pairs = extract_pairs(prev_steps)

            if compress_prev and prev_pairs:
                keep_n = min(self.config.keep_recent_pairs, len(prev_pairs))
                pairs_to_compress = prev_pairs[:-keep_n] if keep_n > 0 else prev_pairs
                pairs_to_keep = prev_pairs[-keep_n:] if keep_n > 0 else []
                if pairs_to_compress:
                    prev_result = self._prev_compressor.compress(
                        pairs_to_compress, self._previous_summary_cache, model,
                    )
                    self.compression_calls_log.extend(prev_result.records)
                    self._step_local_log.extend(prev_result.records)
                    if prev_result.new_cache is not None:
                        self._previous_summary_cache = prev_result.new_cache
                    if prev_result.summary_text:
                        is_fallback = "[CONTEXT COMPACTION" in prev_result.summary_text
                        prev_summary_step = SummaryTaskStep(
                            task=prev_result.summary_text,
                            prefix="Context fallback, Truncated raw history:" if is_fallback else "Summary of earlier steps in this task:"
                        )
                        prev_tail_steps = self._renderer.pairs_to_steps(pairs_to_keep)
            elif prev_pairs:
                # if cache is valid, use cache + uncovered display
                is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
                if is_valid:
                    prev_summary_step = SummaryTaskStep(
                        task=self._previous_summary_cache.summary_text,
                        prefix="Summary of earlier steps in this task:",
                    )
                    uncovered = prev_pairs[covered_idx:]
                    prev_tail_steps = self._renderer.pairs_to_steps(uncovered)

            # --------------- Current phase ---------------
            curr_kept_steps: List[MemoryStep] = list(curr_steps)

            if curr_steps:
                curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]

                if compress_curr and curr_action_steps:
                    keep_n = min(self.config.keep_recent_steps, len(curr_action_steps))
                    # Note: No cross-step pair detection needed here. Each ActionStep
                    # is self-contained — tool_calls and observations always belong to
                    # the same step (set in _step_stream), so there is no risk of
                    # splitting a call-observation pair across the compression boundary.

                    actions_to_compress = (
                        curr_action_steps[:-keep_n] if keep_n > 0 else list(curr_action_steps)
                    )

                    actions_to_compress = (
                        curr_action_steps[:-keep_n] if keep_n > 0 else list(curr_action_steps)
                    )
                    actions_to_keep = (
                        curr_action_steps[-keep_n:] if keep_n > 0 else []
                    )
                    if actions_to_compress:
                        curr_result = self._curr_compressor.compress(
                            curr_task, actions_to_compress, self._current_summary_cache, model,
                        )
                        self.compression_calls_log.extend(curr_result.records)
                        self._step_local_log.extend(curr_result.records)
                        if curr_result.new_cache is not None:
                            self._current_summary_cache = curr_result.new_cache
                        if curr_result.summary_text:
                            is_fallback = "[CONTEXT COMPACTION" in curr_result.summary_text
                            curr_summary_step = SummaryTaskStep(
                                task=curr_result.summary_text,
                                prefix="Truncated recent action steps:" if is_fallback else "Summary of earlier steps in this task:"
                            )
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [curr_summary_step]
                                + list(actions_to_keep)
                            )
                elif curr_action_steps:
                    is_valid, covered_idx = is_curr_cache_valid(curr_action_steps, self._current_summary_cache)
                    if is_valid:
                        uncovered = curr_action_steps[covered_idx:]
                        curr_kept_steps = (
                            ([curr_task] if curr_task else [])
                            + [SummaryTaskStep(task=self._current_summary_cache.summary_text, prefix="Summary of earlier steps in this task:")]
                            + list(uncovered)
                        )

            final_messages = self._renderer.build_messages(
                memory, prev_summary_step, prev_tail_steps, curr_kept_steps
            )
            final_tokens = msg_token_count(final_messages, self.config.chars_per_token)
            self._last_compressed_token_count = final_tokens
            # This situation is unlikely to occur unless the threshold itself is set unreasonably small
            if final_tokens > int(self.config.token_threshold * 1.1):
                logger.warning(
                    f"Still exceeds threshold after compression: {final_tokens} > {self.config.token_threshold}. "
                    f"Consider reducing keep_recent_pairs ({self.config.keep_recent_pairs}) "
                    f"or keep_recent_steps({self.config.keep_recent_steps})"
                )
            return final_messages

    # ============================================================
    #  Stats and Export (delegate to pure functions)
    # ============================================================

    def get_step_compression_stats(self) -> dict:
        with self._lock:
            return get_step_compression_stats(self._step_local_log)

    def get_all_compression_stats(self) -> dict:
        with self._lock:
            return get_all_compression_stats(self.compression_calls_log)

    def export_summary(self) -> dict:
        with self._lock:
            return export_summary(self._previous_summary_cache, self._current_summary_cache, self.config)

    def get_token_counts(self) -> dict:
        with self._lock:
            return get_token_counts(self._last_uncompressed_token_count, self._last_compressed_token_count)

    def build_compressed_snapshot(
        self, model, memory: AgentMemory, current_run_start_idx: int,
    ) -> tuple:
        """Build a frozen compressed message snapshot for probe evaluation.

        Returns (compressed_messages, metadata) without modifying internal
        cache state.
        """
        # Save current state before compression (no lock -- compress_if_needed
        # acquires its own lock, so we must not hold one here)
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
            # Restore original state -- snapshot must not mutate cache
            self._previous_summary_cache = saved_prev_cache
            self._current_summary_cache = saved_curr_cache
            self._step_local_log = saved_step_log
            self.compression_calls_log = saved_calls_log

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

    def _get_strategy(self):
        """Factory method to get strategy instance based on config."""
        from ..agent_model import (
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

    def build_system_prompt(self, token_budget: Optional[int] = None) -> List:
        """Build system prompt messages from registered components.

        Uses configured strategy to select components within token budget,
        then converts each to message format.

        Args:
            token_budget: Maximum tokens for all components. Defaults to
                          config.component_budgets total minus conversation_history.

        Returns:
            List of message dicts with 'role' and 'content' keys.
        """
        if not self._components:
            return []

        from ..agent_model import SystemPromptComponent

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
