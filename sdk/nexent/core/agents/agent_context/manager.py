"""ContextManager: agent memory context management and compression.

Composes sub-components (StepRenderer, LLMSummary, PreviousCompressor,
CurrentCompressor) and pure functions (budget, stats_export) to provide
full compression functionality. The main entry point is
``compress_if_needed()`` which orchestrates previous/current compression
phases with cache-based optimization.
"""

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage

from ..summary_cache import CompressionCallRecord, CurrentSummaryCache, PreviousSummaryCache
from ..summary_config import ContextManagerConfig, StrategyType
from ...context_runtime.contracts import ContextEvidence, FinalContext
from .budget import (
    extract_pairs, is_prev_cache_valid, is_curr_cache_valid,
    trim_pairs_to_budget, trim_actions_to_budget,
)
from .current_compression import CurrentCompressor
from .llm_summary import LLMSummary, format_summary_output
from .offload_store import OffloadStore
from .previous_compression import PreviousCompressor
from .stats_export import (
    get_step_compression_stats, get_all_compression_stats,
    export_summary, get_token_counts,
)
from .step_renderer import StepRenderer
from .summary_step import SummaryTaskStep, ManagedRunContext
from ...utils.token_estimation import estimate_tokens, estimate_tokens_for_system_prompt, estimate_tokens_for_steps, estimate_tokens_text, msg_token_count

logger = logging.getLogger("agent_context")


class ContextManager:
    """Agent memory context management and compression.

    Orchestrates token-aware compression of agent memory, supporting
    incremental summarization with cache-based optimization.

    Composes (not inherits) sub-components. Owns all state and
    delegates computation to pure functions and sub-component methods.
    """

    def __init__(self, config: Optional[ContextManagerConfig] = None,
                 max_steps: Optional[int] = None, offload_store: Optional[OffloadStore] = None):
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
        self._offload_store = offload_store or OffloadStore(
            max_entries=self.config.max_offload_entries,
            max_entry_chars=self.config.max_offload_entry_chars,
            max_total_chars=self.config.max_offload_total_chars,
        )
        self._last_uncompressed_token_count: Optional[int] = None
        self._last_compressed_token_count: Optional[int] = None

        # W3 stable-prefix fingerprint cache is conversation-level.  Per-run
        # component message partitions are held by ManagedContextRuntime, not
        # here, so concurrent runs sharing a ContextManager cannot overwrite
        # each other's dynamic context.
        self._previous_stable_fingerprint: Optional[str] = None
        self._previous_stable_components: Dict[str, str] = {}

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

    def _soft_input_budget_tokens(self) -> int:
        return self.config.soft_input_budget_tokens or self.config.token_threshold

    def _hard_input_budget_tokens(self) -> int:
        return self.config.hard_input_budget_tokens or int(self.config.token_threshold * 1.1)

    def _estimate_text_tokens(self, text: str) -> int:
        return estimate_tokens_text(text)

    def _msg_char_count(self, msg) -> int:
        from ...utils.token_estimation import msg_char_count
        return msg_char_count(msg)

    def _msg_token_count(self, msg) -> int:
        return msg_token_count(msg, self.config.chars_per_token)

    def _estimate_tokens_for_steps(self, steps) -> int:
        return estimate_tokens_for_steps(steps, self.config.chars_per_token)

    def _actions_to_text_with_limit(self, actions: List[ActionStep], prefill_tokens: int = 0) -> str:
        rendered_steps = []
        for i, step in enumerate(actions):
            prefix = f"[Step {step.step_number or i+1}]\n"
            content = self._renderer.render_action_step(step)
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

    def _format_summary(self, raw_output: str) -> Optional[str]:
        return format_summary_output(raw_output)

    def compress_if_needed(
        self,
        model,
        memory,
        original_messages: List[ChatMessage],
        current_run_start_idx,
        context_overhead_tokens: int = 0,
    ) -> List[ChatMessage]:
        if not self.config.enabled:
            return original_messages

        soft_input_budget_tokens = self._soft_input_budget_tokens()
        hard_input_budget_tokens = self._hard_input_budget_tokens()
        soft_history_budget_tokens = max(0, soft_input_budget_tokens - context_overhead_tokens)
        hard_history_budget_tokens = max(0, hard_input_budget_tokens - context_overhead_tokens)

        if estimate_tokens(memory, self.config.chars_per_token) <= soft_history_budget_tokens:
            self._last_uncompressed_token_count = msg_token_count(original_messages, self.config.chars_per_token)
            self._last_compressed_token_count = self._last_uncompressed_token_count
            return original_messages

        with self._lock:
            # Run detection
            if (self._last_run_start_idx is not None
                    and current_run_start_idx != self._last_run_start_idx):
                # Only the per-run compression cache is run-scoped and reset here.
                # The offload store is intentionally NOT cleared: it is now
                # session-scoped and owned externally (injected via the
                # ``offload_store`` parameter), so archived content survives across
                # runs within the same session and can be re-listed + reloaded.
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
                # Refresh the uncompressed baseline here too, so the per-step
                # compression ratio (est_raw_i) reflects THIS step's full
                # uncompressed memory instead of a stale value from the last
                # full compression. Mirrors the bookkeeping on the full path
                # below. Without this, stable_bypass steps (cache hits) report a
                # frozen baseline and understate savings.
                self._last_uncompressed_token_count = msg_token_count(original_messages, self.config.chars_per_token)
                self._last_compressed_token_count = msg_token_count(compressed_msgs, self.config.chars_per_token)
                return compressed_msgs

            self._step_local_log.clear()

            self._last_uncompressed_token_count = msg_token_count(original_messages, self.config.chars_per_token)

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
            if final_tokens > hard_history_budget_tokens:
                logger.warning(
                    f"Still exceeds hard input budget after compression: {final_tokens} > {hard_input_budget_tokens}. "
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
    #  Managed Context Assembly (W3)
    # ============================================================

    def prepare_run_context(
        self,
        memory: AgentMemory,
        fallback_system_prompt: str,
        components: Optional[Sequence[Any]] = None,
    ) -> ManagedRunContext:
        """Initialize and return a run-local managed context snapshot.

        ContextManager owns the selected component messages and the stable prefix.
        Runtime adapters must not reorder or reinterpret these messages, but the
        run-scoped partition itself must stay outside shared ContextManager
        state to avoid cross-run interference.
        """
        from smolagents.memory import SystemPromptStep

        component_messages = self.build_context_messages(components=components)
        stable_messages = [
            message for message in component_messages
            if self._message_role(message) in {"system", "developer"}
        ]
        dynamic_messages = [
            message for message in component_messages
            if self._message_role(message) not in {"system", "developer"}
        ]

        stable_text = "\n\n".join(
            str(message.get("content", "")) for message in stable_messages
        )
        memory.system_prompt = SystemPromptStep(
            system_prompt=stable_text or fallback_system_prompt
        )
        source_components = tuple(self._component_source(components))
        selected_component_types = tuple(
            str(getattr(component, "component_type", "unknown"))
            for component in source_components
        )
        return ManagedRunContext(
            component_messages=tuple(component_messages),
            stable_messages=tuple(stable_messages),
            dynamic_messages=tuple(dynamic_messages),
            selected_component_types=selected_component_types,
            components=source_components,
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
        run_context: Optional[ManagedRunContext] = None,
    ) -> FinalContext:
        """Return the only managed-path payload allowed to enter a model call.

        This is the W3 boundary: component selection, stable-prefix preservation,
        dynamic context insertion, compression budget compensation, final-answer
        augmentation, tool canonicalization, and evidence generation all happen
        here, inside ContextManager.  Provider adapters must not reorder
        ``messages``; cache protocol behavior is decided later from provider
        capabilities only.
        """
        if run_context is None:
            run_context = self.prepare_run_context(memory, fallback_system_prompt="")

        tools = self._canonical_tools(tools or ())
        purpose_stable, purpose_dynamic = self._purpose_messages(
            purpose=purpose,
            task=task,
            final_answer_templates=final_answer_templates,
        )

        original_messages = self._messages_from_memory(memory)
        stable_messages = [*run_context.stable_messages, *purpose_stable]
        dynamic_messages = [*run_context.dynamic_messages, *purpose_dynamic]

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
        component_fingerprints = self._stable_component_fingerprints(
            purpose_stable,
            components=run_context.components,
        )
        if tools:
            component_fingerprints["tools"] = self._fingerprint(tools)
        reasons = self._change_reasons(fingerprint, component_fingerprints)
        self._previous_stable_fingerprint = fingerprint
        self._previous_stable_components = component_fingerprints

        return FinalContext(
            messages=messages,
            tools=tools,
            evidence=ContextEvidence(
                selected_component_types=run_context.selected_component_types,
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
        if "pre_messages" not in final_answer or "post_messages" not in final_answer:
            raise ValueError("final_answer template requires pre_messages and post_messages")
        pre_messages = final_answer["pre_messages"]
        post_messages = Template(
            final_answer["post_messages"],
            undefined=StrictUndefined,
        ).render(task=task or "")
        return (
            [{"role": "system", "content": pre_messages}],
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
        indexed_tools = [
            (index, tool, ContextManager._normalize_for_fingerprint(tool))
            for index, tool in enumerate(tools)
        ]
        return [
            tool for _, tool, _ in sorted(
                indexed_tools,
                key=lambda item: (
                    json.dumps(
                        item[2],
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                    item[0],
                ),
            )
        ]

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
        name = getattr(value, "name", None)
        if isinstance(name, str) and name:
            return {"__class__": value.__class__.__name__, "name": name}
        if hasattr(value, "__dict__"):
            public_attrs = {
                key: item for key, item in vars(value).items()
                if not key.startswith("_")
            }
            if public_attrs:
                return ContextManager._normalize_for_fingerprint(public_attrs)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return {
            "__class__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
        }

    def _fingerprint(self, messages: Sequence[Any]) -> str:
        encoded = json.dumps(
            self._normalize_for_fingerprint(messages),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _stable_component_fingerprints(
        self,
        purpose_stable: Sequence[Any] = (),
        components: Optional[Sequence[Any]] = None,
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for component in self._component_source(components):
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
        reasons: List[str] = []
        if self._previous_stable_components.get("tools") != component_fingerprints.get("tools"):
            reasons.append("tool_schema_version")
        if self._previous_stable_components.get("purpose") != component_fingerprints.get("purpose"):
            reasons.append("context_purpose")
        previous_components = {
            key: value for key, value in self._previous_stable_components.items()
            if key not in {"tools", "purpose"}
        }
        current_components = {
            key: value for key, value in component_fingerprints.items()
            if key not in {"tools", "purpose"}
        }
        if previous_components != current_components:
            reasons.append("system_prompt_version")
        return reasons or ["unexpected_nondeterminism"]

    def _component_source(self, components: Optional[Sequence[Any]]) -> List[Any]:
        return list(components) if components is not None else self.get_registered_components()

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

    def build_context_messages(
        self,
        token_budget: Optional[int] = None,
        components: Optional[Sequence[Any]] = None,
    ) -> List:
        """Build all selected component messages for the managed context path.

        Uses configured strategy to select components within token budget,
        then converts each to message format.

        Args:
            token_budget: Maximum tokens for all components. Defaults to
                          config.component_budgets total minus conversation_history.
            components: Optional explicit component list. If None, uses the
                        registered component list.

        Returns:
            List of message dicts with 'role' and 'content' keys.  Roles are
            preserved: dynamic components such as Memory and KB are intentionally
            returned as ``user`` messages rather than being coerced into a
            system prompt.
        """
        source_components = self._component_source(components)
        if not source_components:
            return []

        from ..agent_model import SystemPromptComponent

        budget = token_budget or self._calculate_component_budget()
        strategy = self._get_strategy()
        selected = strategy.select_components(
            source_components, budget, self.config.component_budgets
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
