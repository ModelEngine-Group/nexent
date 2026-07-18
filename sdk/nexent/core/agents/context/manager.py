"""ContextManager: the main orchestrator for agent context compression and managed context assembly.

Owns compression collaborators and delegates history compression/rendering to
them. Fine-grained item assembly remains directly on ContextManager.
"""

import hashlib
import json
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union


if TYPE_CHECKING:
    from ...context_runtime.contracts import FinalContext

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage

from ...utils.token_estimation import (
    estimate_tokens,
    estimate_tokens_for_steps,
    estimate_tokens_for_system_prompt,
    msg_char_count,
    msg_token_count,
)
from ..summary_cache import CompressionCallRecord, CurrentSummaryCache, PreviousSummaryCache
from .budget import (
    extract_message_text,
    extract_pairs,
    is_curr_cache_valid,
    is_prev_cache_valid,
    message_role,
)
from .config import ContextManagerConfig
from .current_compression import CurrentCompressor
from .llm_summary import LLMSummary
from .policy import resolve_policy
from .previous_compression import PreviousCompressor
from .selection import select_context_items
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
        self._previous_stable_items: Dict[str, str] = {}

        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)

        self._items: List = []

        # Compose compression collaborators.
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

    def _effective_prev_tokens(self, prev_steps: List[MemoryStep]) -> int:
        if not prev_steps:
            return 0
        prev_pairs = extract_pairs(prev_steps)
        is_valid, covered_idx = is_prev_cache_valid(prev_pairs, self._previous_summary_cache)
        if not is_valid:
            return estimate_tokens_for_steps(prev_steps, self.config.chars_per_token)
        uncovered = prev_pairs[covered_idx:]
        uncovered_tokens = (
            self._renderer.estimate_text_tokens(self._renderer.pairs_to_text(uncovered))
            if uncovered else 0
        )
        return (self._renderer.estimate_text_tokens(self._previous_summary_cache.summary_text)
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
            self._renderer.estimate_text_tokens(curr_task.task or "") if curr_task else 0
        )
        uncovered = action_steps[covered_idx:]
        uncovered_tokens = (
            self._renderer.estimate_text_tokens(self._renderer.actions_to_text(uncovered))
            if uncovered else 0
        )
        return (task_tokens
                + self._renderer.estimate_text_tokens(self._current_summary_cache.summary_text)
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
        if not self.config.enabled:
            return original_messages

        soft_input_budget_tokens = self._soft_input_budget_tokens()
        hard_input_budget_tokens = self._hard_input_budget_tokens()
        soft_history_budget_tokens = max(0, soft_input_budget_tokens - context_overhead_tokens)
        hard_history_budget_tokens = max(0, hard_input_budget_tokens - context_overhead_tokens)

        if estimate_tokens(memory, self.config.chars_per_token) <= soft_history_budget_tokens:
            self._last_uncompressed_token_count = self._msg_token_count(original_messages)
            self._last_compressed_token_count = self._last_uncompressed_token_count
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
                    if is_valid:
                        prev_summary_step = SummaryTaskStep(
                            task=self._previous_summary_cache.summary_text
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
                                + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
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
                if is_valid:
                    prev_summary_step = SummaryTaskStep(
                        task=self._previous_summary_cache.summary_text
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
                    if is_valid:
                        uncovered = curr_action_steps[covered_idx:]
                        curr_kept_steps = (
                            ([curr_task] if curr_task else [])
                            + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
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
        items: Optional[Sequence[Any]] = None,
    ) -> ManagedRunContext:
        from smolagents.memory import SystemPromptStep

        source_items = self._item_source(items)
        policy = resolve_policy(self.config.policy_layers)
        query = self.config.selection_query or self._latest_user_text(source_items)
        normalized_items, selection_decision = select_context_items(
            source_items,
            policy,
            query=query,
        )
        logger.info(
            "Context policy decision: enabled=%s version=%s selected=%s excluded=%s "
            "policy_fingerprint=%s decision_fingerprint=%s",
            policy.enabled,
            selection_decision.policy_version,
            list(selection_decision.selected_item_ids),
            list(selection_decision.excluded_item_ids),
            selection_decision.policy_fingerprint,
            selection_decision.decision_fingerprint,
        )
        item_messages = self.build_context_messages(items=normalized_items)
        stable_messages = [
            message for message in item_messages
            if message_role(message) in {"system", "developer"}
        ]
        dynamic_messages = [
            message for message in item_messages
            if message_role(message) not in {"system", "developer"}
        ]

        stable_text = "\n\n".join(
            extract_message_text(message) for message in stable_messages
        )
        memory.system_prompt = SystemPromptStep(
            system_prompt=stable_text or fallback_system_prompt
        )
        selected_item_types = tuple(
            item.type.value for item in normalized_items
        )
        return ManagedRunContext(
            item_messages=tuple(item_messages),
            stable_messages=tuple(stable_messages),
            dynamic_messages=tuple(dynamic_messages),
            selected_item_types=selected_item_types,
            items=tuple(normalized_items),
            selection_decision=selection_decision,
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
    ) -> "FinalContext":
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
        item_fingerprints = self._stable_item_fingerprints(
            purpose_stable,
            items=run_context.items,
        )
        if tools:
            item_fingerprints["tools"] = self._fingerprint(tools)
        reasons = self._change_reasons(fingerprint, item_fingerprints)
        self._previous_stable_fingerprint = fingerprint
        self._previous_stable_items = item_fingerprints

        from ...context_runtime.contracts import ContextEvidence, FinalContext

        selection_decision = run_context.selection_decision
        return FinalContext(
            messages=messages,
            tools=tools,
            evidence=ContextEvidence(
                selected_item_ids=tuple(item.id for item in run_context.items),
                selected_item_types=run_context.selected_item_types,
                stable_message_count=len(stable_messages),
                dynamic_message_count=len(messages) - len(stable_messages),
                compression_records=tuple(self._step_local_log or ()),
                stable_prefix_fingerprint=fingerprint,
                prefix_change_reasons=tuple(reasons),
                excluded_item_ids=(
                    selection_decision.excluded_item_ids if selection_decision else ()
                ),
                selection_reason_codes=(
                    tuple(decision.reason_code for decision in selection_decision.item_decisions)
                    if selection_decision else ()
                ),
                policy_version=(selection_decision.policy_version if selection_decision else None),
                policy_fingerprint=(selection_decision.policy_fingerprint if selection_decision else None),
                selection_decision_fingerprint=(
                    selection_decision.decision_fingerprint if selection_decision else None
                ),
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
            [{"role": "system", "content": [{"type": "text", "text": pre_messages}]}],
            [{"role": "user", "content": [{"type": "text", "text": post_messages}]}],
        )

    @staticmethod
    def _messages_from_memory(memory: AgentMemory) -> List[Any]:
        messages: List[Any] = []
        if memory.system_prompt:
            messages.extend(memory.system_prompt.to_messages())
        for step in memory.steps:
            messages.extend(step.to_messages())
        return messages

    def render_memory_messages(self, memory: AgentMemory) -> List[Any]:
        """Render memory for display without triggering selection or compression."""
        return self._messages_from_memory(memory)

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

    def _fingerprint(self, messages: Sequence[Any]) -> str:
        encoded = json.dumps(
            self._normalize_for_fingerprint(messages),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _stable_item_fingerprints(
        self,
        purpose_stable: Sequence[Any] = (),
        items: Optional[Sequence[Any]] = None,
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        from ..context import ContextItemRenderer
        for item in self._item_source(items):
            stable = [message for message in ContextItemRenderer().render([item])
                      if message_role(message) in {"system", "developer"}]
            if stable:
                result[item.id] = self._fingerprint(stable)
        if purpose_stable:
            result["purpose"] = self._fingerprint(purpose_stable)
        return result

    def _change_reasons(
        self, current: str, item_fingerprints: Dict[str, str]
    ) -> List[str]:
        if self._previous_stable_fingerprint is None:
            return ["initial_request"]
        if self._previous_stable_fingerprint == current:
            return []
        reasons: List[str] = []
        if self._previous_stable_items.get("tools") != item_fingerprints.get("tools"):
            reasons.append("tool_schema_version")
        if self._previous_stable_items.get("purpose") != item_fingerprints.get("purpose"):
            reasons.append("context_purpose")
        previous_items = {
            key: value for key, value in self._previous_stable_items.items()
            if key not in {"tools", "purpose"}
        }
        current_items = {
            key: value for key, value in item_fingerprints.items()
            if key not in {"tools", "purpose"}
        }
        if previous_items != current_items:
            reasons.append("system_prompt_version")
        return reasons or ["unexpected_nondeterminism"]

    def _item_source(self, items: Optional[Sequence[Any]]) -> List[Any]:
        from ..context.models import ContextItem, normalize_context_inputs
        source = list(items) if items is not None else self.get_registered_items()
        if not source:
            return source
        if all(isinstance(item, ContextItem) for item in source):
            return source
        if any(isinstance(item, ContextItem) for item in source):
            raise TypeError("context items cannot mix public inputs and normalized items")
        return normalize_context_inputs(source)

    @staticmethod
    def _ordered_items(items: Sequence[Any]) -> List[Any]:
        """Preserve the Phase 2 full-strategy priority order without pruning."""
        return sorted(items, key=lambda item: item.priority, reverse=True)

    @staticmethod
    def _latest_user_text(items: Sequence[Any]) -> str:
        """Return the latest authorized user history text for relevance scoring."""
        for item in reversed(items):
            if item.type.value == "history" and item.content.get("role") == "user":
                return item.content.get("text", "")
        return ""

    # ============================================================
    #  Context Item Management
    # ============================================================

    def register_item(self, item) -> None:
        with self._lock:
            current = self._item_source([item])[0]
            if any(existing.id == current.id for existing in self._items):
                raise ValueError(f"duplicate context item id: {current.id}")
            self._items.append(current)

    def clear_items(self) -> None:
        with self._lock:
            self._items.clear()

    def get_registered_items(self) -> List:
        with self._lock:
            return list(self._items)

    def replace_items(self, items: List) -> None:
        normalized = self._item_source(items)
        with self._lock:
            self._items = normalized

    def build_context_messages(
        self,
        items: Optional[Sequence[Any]] = None,
    ) -> List:
        source_items = self._ordered_items(self._item_source(items))
        if not source_items:
            return []
        from ..context import ContextItemRenderer
        return ContextItemRenderer().render(source_items)

    def build_system_prompt(self) -> List:
        return self.build_context_messages()
