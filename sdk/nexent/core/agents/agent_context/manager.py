"""ContextManager: the main orchestrator for agent context compression and managed context assembly.

Owns sub-component instances (StepRenderer, LLMSummary, PreviousCompressor, CurrentCompressor)
and delegates compression/rendering to them. W3 managed context and component management
remain directly on ContextManager.
"""

import hashlib
import json
import logging
import threading
from collections.abc import Iterable as IterableABC
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union


if TYPE_CHECKING:
    from ...context_runtime.contracts import FinalContext

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage

from nexent.monitor import (
    OPENINFERENCE_INPUT_VALUE,
    OPENINFERENCE_SPAN_KIND_CHAIN,
    get_monitoring_manager,
)

from ...utils.token_estimation import (
    estimate_tokens,
    estimate_tokens_for_steps,
    estimate_tokens_for_system_prompt,
    msg_char_count,
    msg_token_count,
)
from ..summary_cache import CompressionCallRecord, CurrentSummaryCache, PreviousSummaryCache
from ..summary_config import ContextManagerConfig
from .budget import (
    extract_message_text,
    extract_pairs,
    is_curr_cache_valid,
    is_prev_cache_valid,
    message_role,
)
from .current_compression import CurrentCompressor
from .llm_summary import LLMSummary
from .previous_compression import PreviousCompressor
from .stats_export import (
    export_summary as _export_summary,
)
from .stats_export import (
    get_all_compression_stats as _get_all_compression_stats,
)
from .stats_export import (
    get_step_compression_stats as _get_step_compression_stats,
)
from .stats_export import (
    get_token_counts as _get_token_counts,
)
from .step_renderer import StepRenderer
from .summary_step import ManagedRunContext, SummaryTaskStep


logger = logging.getLogger("agent_context")

_handlers_registered = False


def _ensure_handlers_registered():
    """Lazily register all context item handlers (idempotent)."""
    global _handlers_registered
    if not _handlers_registered:
        from ..context.handlers import register_all
        register_all()
        _handlers_registered = True



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

        self._last_uncompressed_token_count: Optional[int] = None
        self._last_compressed_token_count: Optional[int] = None

        self._previous_stable_fingerprint: Optional[str] = None
        self._previous_stable_components: Dict[str, str] = {}

        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)

        self._components: List = []

        # Compose sub-components
        self._renderer = StepRenderer(self.config)
        self._llm = LLMSummary(self.config, self._renderer)
        self._prev_compressor = PreviousCompressor(self.config, self._renderer, self._llm)
        self._curr_compressor = CurrentCompressor(self.config, self._renderer, self._llm)

    # ============================================================
    #  Effective token estimation
    # ============================================================

    def _effective_tokens(self, memory: AgentMemory, current_run_start_idx: int) -> int:
        system_prompt_tokens = estimate_tokens_for_system_prompt(memory)
        prev_steps = memory.steps[:current_run_start_idx]
        curr_steps = memory.steps[current_run_start_idx:]
        return (system_prompt_tokens + self._effective_prev_tokens(prev_steps)
                + self._effective_curr_tokens(curr_steps))

    def _effective_prev_tokens(self, prev_steps: Sequence[Any]) -> int:
        if not prev_steps:
            return 0
        prev_pairs = extract_pairs(prev_steps)
        is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
        previous_cache = self._previous_summary_cache
        if not is_valid or previous_cache is None:
            return estimate_tokens_for_steps(list(prev_steps), self.config.chars_per_token)
        uncovered = prev_pairs[covered_idx:]
        uncovered_tokens = (
            self._renderer.estimate_text_tokens(self._renderer.pairs_to_text(uncovered))
            if uncovered else 0
        )
        return (self._renderer.estimate_text_tokens(previous_cache.summary_text)
                + uncovered_tokens)

    def _effective_curr_tokens(self, curr_steps: Sequence[Any]) -> int:
        if not curr_steps:
            return 0
        curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
        action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
        is_valid, covered_idx = is_curr_cache_valid(action_steps, self._current_summary_cache)
        current_cache = self._current_summary_cache
        if not is_valid or current_cache is None:
            return estimate_tokens_for_steps(list(curr_steps), self.config.chars_per_token)
        task_tokens = (
            self._renderer.estimate_text_tokens(curr_task.task or "") if curr_task else 0
        )
        uncovered = action_steps[covered_idx:]
        uncovered_tokens = (
            self._renderer.estimate_text_tokens(self._renderer.actions_to_text(uncovered))
            if uncovered else 0
        )
        return (task_tokens
                + self._renderer.estimate_text_tokens(current_cache.summary_text)
                + uncovered_tokens)

    # ============================================================
    #  Main Entry Point
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
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.compress_if_needed",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.context_overhead_tokens": context_overhead_tokens,
                "context.current_run_start_idx": current_run_start_idx,
                OPENINFERENCE_INPUT_VALUE: {
                    "memory_steps": len(memory.steps) if hasattr(memory, 'steps') else 0,
                    "original_message_count": len(original_messages),
                    "current_run_start_idx": current_run_start_idx,
                },
            },
        ):
            if not self.config.enabled:
                if monitoring_manager.is_enabled:
                    monitoring_manager.set_openinference_output({"decision": "disabled", "message_count": len(original_messages)})
                return original_messages

            soft_input_budget_tokens = self._soft_input_budget_tokens()
            hard_input_budget_tokens = self._hard_input_budget_tokens()
            soft_history_budget_tokens = max(0, soft_input_budget_tokens - context_overhead_tokens)
            hard_history_budget_tokens = max(0, hard_input_budget_tokens - context_overhead_tokens)

            if estimate_tokens(memory, self.config.chars_per_token) <= soft_history_budget_tokens:
                self._last_uncompressed_token_count = self._msg_token_count(original_messages)
                self._last_compressed_token_count = self._last_uncompressed_token_count

                if monitoring_manager.is_enabled:
                    monitoring_manager.add_span_event(
                        "context.compress.skipped",
                        {
                            "context.reason": "under_budget",
                            "context.estimated_tokens": estimate_tokens(memory, self.config.chars_per_token),
                            "context.soft_budget": soft_history_budget_tokens,
                        },
                    )
                    monitoring_manager.set_openinference_output({"decision": "skipped", "message_count": len(original_messages), "reason": "under_budget"})

                return original_messages

            with self._lock:
                # Run detection
                if (self._last_run_start_idx is not None
                        and current_run_start_idx != self._last_run_start_idx):
                    self._current_summary_cache = None
                self._last_run_start_idx = current_run_start_idx

                if self._effective_tokens(memory, current_run_start_idx) <= soft_history_budget_tokens:
                    # Stable-phase bypass
                    self._step_local_log.clear()

                    prev_steps = memory.steps[:current_run_start_idx]
                    curr_steps = memory.steps[current_run_start_idx:]

                    prev_summary_step = None
                    prev_tail_steps = list(prev_steps)
                    prev_pairs = extract_pairs(prev_steps)
                    if prev_pairs:
                        is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
                        previous_cache = self._previous_summary_cache
                        if is_valid and previous_cache is not None:
                            prev_summary_step = SummaryTaskStep(
                                task=previous_cache.summary_text
                            )
                            uncovered = prev_pairs[covered_idx:]
                            prev_tail_steps = self._renderer.pairs_to_steps(uncovered)

                    curr_kept_steps = list(curr_steps)
                    if curr_steps:
                        curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                        curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
                        if curr_action_steps:
                            is_valid, covered_idx = is_curr_cache_valid(curr_action_steps, self._current_summary_cache)
                            current_cache = self._current_summary_cache
                            if is_valid and current_cache is not None:
                                uncovered = curr_action_steps[covered_idx:]
                                curr_kept_steps = (
                                    ([curr_task] if curr_task else [])
                                    + [SummaryTaskStep(task=current_cache.summary_text)]
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
                    self._last_uncompressed_token_count = self._msg_token_count(original_messages)
                    self._last_compressed_token_count = self._msg_token_count(compressed_msgs)
                    if monitoring_manager.is_enabled:
                        monitoring_manager.set_openinference_output({"decision": "stable_bypass", "message_count": len(compressed_msgs), "cache_hit": True})
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
                prev_pairs = extract_pairs(prev_steps)

                if compress_prev and prev_pairs:
                    keep_n = min(self.config.keep_recent_pairs, len(prev_pairs))
                    pairs_to_compress = prev_pairs[:-keep_n] if keep_n > 0 else prev_pairs
                    pairs_to_keep = prev_pairs[-keep_n:] if keep_n > 0 else []
                    if pairs_to_compress:
                        result = self._prev_compressor.compress(
                            pairs_to_compress, self._previous_summary_cache, model
                        )
                        summary_text = result.summary_text
                        if summary_text:
                            if "[CONTEXT COMPACTION" in summary_text:
                                prev_summary_step = SummaryTaskStep(task=summary_text, prefix="Context fallback, Truncated raw history:")
                            else:
                                prev_summary_step = SummaryTaskStep(task=summary_text)
                            prev_tail_steps = self._renderer.pairs_to_steps(pairs_to_keep)
                        if result.new_cache:
                            self._previous_summary_cache = result.new_cache
                        self.compression_calls_log.extend(result.records)
                        self._step_local_log.extend(result.records)
                elif prev_pairs:
                    is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
                    previous_cache = self._previous_summary_cache
                    if is_valid and previous_cache is not None:
                        prev_summary_step = SummaryTaskStep(
                            task=previous_cache.summary_text
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
                            result = self._curr_compressor.compress(
                                curr_task, actions_to_compress,
                                self._current_summary_cache, model,
                            )
                            curr_summary_text = result.summary_text
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
                            if result.new_cache:
                                self._current_summary_cache = result.new_cache
                            self.compression_calls_log.extend(result.records)
                            self._step_local_log.extend(result.records)
                    elif curr_action_steps:
                        is_valid, covered_idx = is_curr_cache_valid(curr_action_steps, self._current_summary_cache)
                        current_cache = self._current_summary_cache
                        if is_valid and current_cache is not None:
                            uncovered = curr_action_steps[covered_idx:]
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [SummaryTaskStep(task=current_cache.summary_text)]
                                + list(uncovered)
                            )

                final_messages = self._renderer.build_messages(
                    memory, prev_summary_step, prev_tail_steps, curr_kept_steps
                )
                final_tokens = self._msg_token_count(final_messages)
                self._last_compressed_token_count = final_tokens
                if final_tokens > hard_history_budget_tokens:
                    logger.warning(
                        f"Still exceeds hard input budget after compression: {final_tokens} > {hard_history_budget_tokens}. "
                        f"Consider reducing keep_recent_pairs ({self.config.keep_recent_pairs}) "
                        f"or keep_recent_steps({self.config.keep_recent_steps})"
                    )
                if monitoring_manager.is_enabled:
                    monitoring_manager.set_openinference_output({
                        "decision": "compressed",
                        "message_count": len(final_messages),
                        "uncompressed_tokens": self._last_uncompressed_token_count,
                        "compressed_tokens": self._last_compressed_token_count,
                    })
                return final_messages

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

    # ============================================================
    #  Stats delegation
    # ============================================================

    def get_step_compression_stats(self) -> dict:
        with self._lock:
            return _get_step_compression_stats(self._step_local_log)

    def get_all_compression_stats(self) -> dict:
        with self._lock:
            return _get_all_compression_stats(self.compression_calls_log)

    # ============================================================
    #  Benchmark export APIs
    # ============================================================

    def build_compressed_snapshot(
        self, model, memory: AgentMemory, current_run_start_idx: int,
    ) -> Tuple[List[ChatMessage], dict]:
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
        with self._lock:
            return _get_token_counts(
                self._last_uncompressed_token_count,
                self._last_compressed_token_count,
            )

    def export_summary(self) -> dict:
        with self._lock:
            return _export_summary(
                self._previous_summary_cache,
                self._current_summary_cache,
                self.config,
            )

    # ============================================================
    #  Managed Context Assembly (W3)
    # ============================================================

    def prepare_run_context(
        self,
        memory: AgentMemory,
        fallback_system_prompt: str,
        components: Optional[Sequence[Any]] = None,
    ) -> ManagedRunContext:
        from smolagents.memory import SystemPromptStep

        component_messages = self.build_context_messages(components=components)
        stable_messages = [
            message for message in component_messages
            if message_role(message) in {"system", "developer"}
        ]
        dynamic_messages = [
            message for message in component_messages
            if message_role(message) not in {"system", "developer"}
        ]

        stable_text = "\n\n".join(
            extract_message_text(message) for message in stable_messages
        )
        memory.system_prompt = SystemPromptStep(
            system_prompt=stable_text or fallback_system_prompt
        )
        source_components = tuple(self._component_source(components))
        if source_components:
            budget = self._calculate_component_budget()
            strategy = self._get_strategy()
            selected_components = tuple(strategy.select_components(
                source_components, budget, self.config.component_budgets
            ))
        else:
            selected_components = ()

        selected_component_types = tuple(
            str(getattr(component, "component_type", "unknown"))
            for component in selected_components
        )
        return ManagedRunContext(
            component_messages=tuple(component_messages),
            stable_messages=tuple(stable_messages),
            dynamic_messages=tuple(dynamic_messages),
            selected_component_types=selected_component_types,
            selected_components=selected_components,
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
        conversation_id: Optional[int] = None,
    ) -> "FinalContext":
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.assemble_final_context",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.purpose": purpose,
                "context.conversation_id": conversation_id,
                "context.use_context_items": self.config.use_context_items,
                "context.current_run_start_idx": current_run_start_idx,
                OPENINFERENCE_INPUT_VALUE: {
                    "purpose": purpose,
                    "memory_steps": len(memory.steps) if hasattr(memory, 'steps') else 0,
                    "has_tools": bool(tools),
                    "has_run_context": run_context is not None,
                },
            },
        ):
            if run_context is None:
                run_context = self.prepare_run_context(memory, fallback_system_prompt="")

            tools = self._canonical_tools(tools or ())
            purpose_stable, purpose_dynamic = self._purpose_messages(
                purpose=purpose,
                task=task,
                final_answer_templates=final_answer_templates,
            )

            context_items_for_evidence: tuple = ()
            selection_decision_for_evidence = None
            reduction_warnings_for_evidence: tuple = ()

            if self.config.use_context_items:
                projected_items = self.project_context_items(run_context.selected_components)

                history_projector = self.config.history_projector
                if history_projector is not None and conversation_id is not None:
                    try:
                        history_items = history_projector.project(
                            conversation_id=conversation_id,
                            purpose=purpose if purpose in ("model_context", "resume", "chat") else "model_context",
                        )
                        projected_items.extend(history_items)
                    except Exception:
                        logger.warning("History projection failed, continuing without history items", exc_info=True)

                context_items_for_evidence = tuple(projected_items)

                # Run selection engine and apply reduction
                from ..context.context_item import ContextItem as _ContextItem
                from ..context.item_handler_registry import ItemHandlerRegistry
                from ..context.policy_models import resolve_policy
                from ..context.selection_engine import select_context

                safe_budget = self._calculate_safe_input_budget(model, tools, purpose_stable)
                policy = resolve_policy()
                decision = select_context(policy, projected_items, safe_budget)
                selection_decision_for_evidence = decision

                reduced_items = []
                reduction_warnings = []
                for item in projected_items:
                    if item.item_id in decision.selected_item_ids:
                        target_tier = (
                            decision.representation_requirements.get(item.item_id)
                            or item.current_representation
                        )
                        if target_tier != item.current_representation:
                            try:
                                result = ItemHandlerRegistry.reduce_item(
                                    item, target_tier, safe_budget, policy
                                )
                                if result.admissible:
                                    reduced_item = _ContextItem(
                                        item_id=item.item_id,
                                        item_type=item.item_type,
                                        source_refs=item.source_refs,
                                        authority_tier=item.authority_tier,
                                        minimum_fidelity=item.minimum_fidelity,
                                        current_representation=target_tier,
                                        content=result.content,
                                        token_estimate=result.token_count,
                                        metadata={**item.metadata, "_reduced": True},
                                        lifecycle_status=item.lifecycle_status,
                                        recompute_cost=item.recompute_cost,
                                    )
                                    reduced_items.append(reduced_item)
                                else:
                                    reduction_warnings.append({
                                        "item_id": item.item_id,
                                        "reason": result.loss_metadata.get("reason", "unknown"),
                                    })
                                    reduced_items.append(item)
                            except Exception:
                                logger.warning(
                                    "Reduction failed for item %s, using original",
                                    item.item_id,
                                    exc_info=True,
                                )
                                reduction_warnings.append({
                                    "item_id": item.item_id,
                                    "reason": "reduction_exception",
                                })
                                reduced_items.append(item)
                        else:
                            reduced_items.append(item)
                reduction_warnings_for_evidence = tuple(reduction_warnings)
                projected_items = reduced_items

                seen_components = set()
                item_messages = []
                for item in projected_items:
                    source_component = item.metadata.get("_source_component")
                    to_messages = getattr(source_component, "to_messages", None)
                    if source_component and id(source_component) not in seen_components and callable(to_messages):
                        seen_components.add(id(source_component))
                        item_messages.extend(self._message_sequence(to_messages()))

                for item in projected_items:
                    if item.metadata.get("_source_component") is None:
                        handler = ItemHandlerRegistry.get(item.item_type)
                        for msg in handler.to_messages(item):
                            item_messages.append(msg)

                stable_from_items = [m for m in item_messages if message_role(m) in ("system", "developer")]
                dynamic_from_items = [m for m in item_messages if message_role(m) not in ("system", "developer")]

                run_context = ManagedRunContext(
                    component_messages=tuple(item_messages),
                    stable_messages=tuple(stable_from_items),
                    dynamic_messages=tuple(dynamic_from_items),
                    selected_component_types=run_context.selected_component_types,
                    selected_components=run_context.selected_components,
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
                components=run_context.selected_components,
            )
            if tools:
                component_fingerprints["tools"] = self._fingerprint(tools)
            reasons = self._change_reasons(fingerprint, component_fingerprints)
            self._previous_stable_fingerprint = fingerprint
            self._previous_stable_components = component_fingerprints

            if monitoring_manager.is_enabled:
                monitoring_manager.set_openinference_output({
                    "message_count": len(messages),
                    "stable_count": len(stable_messages),
                    "dynamic_count": len(dynamic_messages),
                    "tool_count": len(tools),
                    "context_items": len(context_items_for_evidence),
                    "total_tokens": self._last_compressed_token_count,
                })

            from ...context_runtime.contracts import ContextEvidence, FinalContext

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
                    context_items=context_items_for_evidence,
                    selection_decision=selection_decision_for_evidence,
                    reduction_warnings=reduction_warnings_for_evidence,
                ),
            )

    def _calculate_safe_input_budget(self, model: Any, tools: Sequence[Any], purpose_stable: Sequence[Any]) -> int:
        """Estimate remaining token budget for context items."""
        if self.config.soft_input_budget_tokens > 0:
            budget = self.config.soft_input_budget_tokens
        else:
            budget = self.config.token_threshold

        overhead = (
            self._estimate_tools_tokens(tools)
            + self._msg_token_count(purpose_stable)
            + 500
        )
        return max(0, budget - overhead)

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
            [{"role": "system", "content": [{"type": "text", "text": pre_messages}]}],
            [{"role": "user", "content": [{"type": "text", "text": post_messages}]}],
        )


    @staticmethod
    def _message_sequence(value: Any) -> List[Any]:
        if isinstance(value, IterableABC) and not isinstance(value, (str, bytes, dict)):
            return list(value)
        return []

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
        while remaining and message_role(remaining[0]) in {"system", "developer"}:
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
        return self._renderer.estimate_text_tokens(
            json.dumps(self._normalize_for_fingerprint(tools), ensure_ascii=False, sort_keys=True, default=str)
        )

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

    def _fingerprint(self, value: Any) -> str:
        encoded = json.dumps(
            self._normalize_for_fingerprint(value),
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
                message for message in self._message_sequence(to_messages())
                if message_role(message) in {"system", "developer"}
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
        with self._lock:
            if component.token_estimate == 0:
                component.token_estimate = component.estimate_tokens(
                    self.config.chars_per_token
                )
            self._components.append(component)

    def clear_components(self) -> None:
        with self._lock:
            self._components.clear()

    def get_registered_components(self) -> List:
        with self._lock:
            return list(self._components)

    def replace_components(self, components: List) -> None:
        with self._lock:
            self._components.clear()
            for component in components:
                if component.token_estimate == 0:
                    component.token_estimate = component.estimate_tokens(
                        self.config.chars_per_token
                    )
                self._components.append(component)

    def _get_strategy(self):
        from ..agent_model import BufferedStrategy, FullStrategy, PriorityWeightedStrategy, TokenBudgetStrategy
        strategy_map = {
            "full": FullStrategy,
            "token_budget": TokenBudgetStrategy,
            "buffered": BufferedStrategy,
            "priority": PriorityWeightedStrategy,
        }
        strategy_class = strategy_map.get(self.config.strategy, FullStrategy)

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
        source_components = self._component_source(components)
        if not source_components:
            return []


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

    def project_context_items(
        self,
        components: Optional[Sequence[Any]] = None,
    ) -> List[Any]:
        """Project registered components into fine-grained ContextItem candidates."""
        monitoring_manager = get_monitoring_manager()
        _ensure_handlers_registered()
        from ..context.projector import ContextProjector

        source_components = self._component_source(components)

        with monitoring_manager.trace_operation(
            "context.project_items",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.component_count": len(source_components),
                OPENINFERENCE_INPUT_VALUE: [
                    getattr(c, "component_type", type(c).__name__) for c in source_components
                ],
            },
        ):
            projector = ContextProjector()
            items = projector.project(list(source_components))

            if monitoring_manager.is_enabled:
                monitoring_manager.set_openinference_output({
                    "item_count": len(items),
                    "item_types": [item.item_type.value for item in items],
                })

            return items


    def build_system_prompt(self, token_budget: Optional[int] = None) -> List:
        return self.build_context_messages(token_budget)

    def _calculate_component_budget(self) -> int:
        budgets = self.config.component_budgets
        excluded = ["conversation_history"]
        return sum(v for k, v in budgets.items() if k not in excluded)

    def _message_already_present(self, messages: List, new_msg: dict) -> bool:
        for existing in messages:
            if existing.get("role") == new_msg.get("role") and existing.get("content") == new_msg.get("content"):
                return True
        return False
