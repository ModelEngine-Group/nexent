"""Managed context assembly for fine-grained items and adaptive compaction."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, Optional, Sequence

from smolagents.memory import ActionStep, AgentMemory, TaskStep

from ...context_runtime.contracts import ContextEvidence, FinalContext
from ..summary_cache import CompressionCallRecord
from .budget import extract_message_text, message_role
from .config import ContextManagerConfig
from .history_compression import HistoryCompressor, HistorySummaryCandidate
from .llm_summary import LLMSummary
from .models import ContextItem, ContextItemInput, ContextItemType, normalize_context_inputs
from .policy import ContextProcessingMode, resolve_policy
from .run_context import ManagedRunContext
from .selection import select_context_items
from .step_renderer import StepRenderer


logger = logging.getLogger("agent_context")


class ContextManager:
    """Owns ordering, budget checks, compaction and final rendering."""

    def __init__(self, config: Optional[ContextManagerConfig] = None, max_steps: int | None = None):
        self.config = config or ContextManagerConfig()
        if max_steps is not None:
            self.config.keep_recent_steps = min(self.config.keep_recent_steps, max_steps)
        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)
        self._lock = threading.Lock()
        self._items: list[ContextItem] = []
        self._renderer = StepRenderer(self.config)
        self._llm = LLMSummary(self.config, self._renderer)
        self._history_compressor = HistoryCompressor(self._llm)
        self._history_candidate: HistorySummaryCandidate | None = None
        self._current_item_cache: dict[int, ContextItem] = {}
        self._step_local_log: list[CompressionCallRecord] = []
        self.compression_calls_log: list[CompressionCallRecord] = []
        self._last_uncompressed_token_count: int | None = None
        self._last_compressed_token_count: int | None = None
        self._previous_stable_fingerprint: str | None = None
        self._previous_stable_items: dict[str, str] = {}
        self._pending_history_summary_event: dict[str, Any] | None = None

    def _soft_input_budget_tokens(self) -> int:
        return self.config.soft_input_budget_tokens or self.config.token_threshold

    def _hard_input_budget_tokens(self) -> int:
        return self.config.hard_input_budget_tokens or int(self.config.token_threshold * 1.1)

    @property
    def hard_input_budget_tokens(self) -> int:
        """Effective hard budget, including the legacy fallback calculation."""
        return self._hard_input_budget_tokens()

    @property
    def processing_mode(self) -> str:
        return resolve_policy(self.config.policy_layers).processing_mode.value

    def prepare_run_context(
        self, memory: AgentMemory, fallback_system_prompt: str,
        items: Optional[Sequence[Any]] = None,
    ) -> ManagedRunContext:
        self._history_candidate = None
        self._current_item_cache.clear()
        source = self._item_source(items)
        if fallback_system_prompt and not any(
            item.type == ContextItemType.SYSTEM for item in source
        ):
            source.append(ContextItem.from_input(ContextItemInput(
                id="system:fallback",
                type=ContextItemType.SYSTEM,
                content={"text": fallback_system_prompt},
                metadata={"layout_order": -1, "runtime_fallback": True},
            )))
        policy = resolve_policy(self.config.policy_layers)
        selected, decision = select_context_items(source, policy)
        messages = self.build_context_messages(selected)
        stable = [message for message in messages if message_role(message) in {"system", "developer"}]
        dynamic = [message for message in messages if message_role(message) not in {"system", "developer"}]
        return ManagedRunContext(
            item_messages=tuple(messages), stable_messages=tuple(stable),
            dynamic_messages=tuple(dynamic),
            selected_item_types=tuple(item.type.value for item in selected),
            items=tuple(selected), selection_decision=decision,
        )

    def assemble_final_context(
        self, *, model: Any, memory: AgentMemory, current_run_start_idx: int,
        tools: Sequence[Any] | None = None, purpose: str = "step",
        task: str | None = None, final_answer_templates: Optional[Dict[str, Any]] = None,
        run_context: ManagedRunContext | None = None,
    ) -> FinalContext:
        run_context = run_context or self.prepare_run_context(memory, "")
        policy = resolve_policy(self.config.policy_layers)
        persisted_items = list(run_context.items)
        if self._history_candidate is not None:
            persisted_items = [item for item in persisted_items if item.type not in {
                ContextItemType.HISTORY_SUMMARY, ContextItemType.CONVERSATION_TURN,
            }]
            persisted_items.append(self._history_candidate.as_item())
        current_items = self._project_current_run(memory, current_run_start_idx)
        items = sorted([*persisted_items, *current_items], key=lambda item: item.layout_key)
        purpose_stable, purpose_dynamic = self._purpose_messages(
            purpose=purpose, task=task, final_answer_templates=final_answer_templates,
        )
        canonical_tools = self._canonical_tools(tools or ())
        raw_tokens = self._estimate_items(items, purpose_stable, purpose_dynamic, canonical_tools)
        final_items = list(items)
        history_triggered = False
        new_coverage = None
        persist_status = "not_attempted"
        self._step_local_log = []

        if policy.processing_mode == ContextProcessingMode.ADAPTIVE_COMPACT and raw_tokens > self._soft_input_budget_tokens():
            summary = next((item for item in final_items if item.type == ContextItemType.HISTORY_SUMMARY), None)
            turns = [item for item in final_items if item.type == ContextItemType.CONVERSATION_TURN]
            if turns:
                history_triggered = True
                result = self._history_compressor.compress(summary, turns, model)
                self._record_compression(result.records)
                if result.candidate is not None:
                    self._history_candidate = result.candidate
                    new_coverage = result.candidate.covered_through_message_id
                    final_items = [item for item in final_items if item.type not in {
                        ContextItemType.HISTORY_SUMMARY, ContextItemType.CONVERSATION_TURN,
                    }]
                    final_items.append(result.candidate.as_item())
                    persist_status = self._persist_candidate(result.candidate)
                    self._pending_history_summary_event = {
                        **deepcopy(result.candidate.as_item().content),
                        "persist_status": persist_status,
                    }
                elif result.fallback_turns:
                    fallback_by_id = {item.id: item for item in result.fallback_turns}
                    final_items = [fallback_by_id.get(item.id, item) for item in final_items]

            final_items = self._compact_to_soft_budget(
                final_items, purpose_stable, purpose_dynamic, canonical_tools
            )

        final_items.sort(key=lambda item: item.layout_key)
        rendered = self.build_context_messages(final_items)
        messages = [*purpose_stable]
        # Stable item messages remain first for KV-cache reuse.
        stable = [message for message in rendered if message_role(message) in {"system", "developer"}]
        dynamic = [message for message in rendered if message_role(message) not in {"system", "developer"}]
        messages = [*stable, *purpose_stable, *dynamic, *purpose_dynamic]
        final_tokens = self._message_tokens(messages) + self._tools_tokens(canonical_tools)
        self._last_uncompressed_token_count = raw_tokens
        self._last_compressed_token_count = final_tokens
        hard = self._hard_input_budget_tokens()
        over_hard = final_tokens > hard
        compact_exhausted = over_hard
        if over_hard:
            logger.warning("Context remains over hard budget after safe compact: %s > %s", final_tokens, hard)

        representations = tuple((
            item.id, str(item.metadata.get("representation", "raw"))
        ) for item in final_items)
        hits = sum(item.representation_cache_stats[0] for item in items)
        misses = sum(item.representation_cache_stats[1] for item in items)
        loaded = next((item for item in run_context.items if item.type == ContextItemType.HISTORY_SUMMARY), None)
        stable_fp = self._fingerprint({"messages": [*stable, *purpose_stable], "tools": canonical_tools})
        reasons = self._change_reasons(stable_fp, self._stable_item_fingerprints(final_items, purpose_stable, canonical_tools))
        self._previous_stable_fingerprint = stable_fp
        selected_ids = tuple(item.id for item in final_items)
        return FinalContext(
            messages=messages, tools=canonical_tools,
            evidence=ContextEvidence(
                selected_item_ids=selected_ids,
                selected_item_types=tuple(item.type.value for item in final_items),
                stable_message_count=len(stable) + len(purpose_stable),
                dynamic_message_count=len(dynamic) + len(purpose_dynamic),
                compression_records=tuple(self._step_local_log),
                stable_prefix_fingerprint=stable_fp,
                prefix_change_reasons=tuple(reasons),
                policy_fingerprint=run_context.selection_decision.policy_fingerprint if run_context.selection_decision else None,
                processing_mode=policy.processing_mode.value,
                soft_budget=self._soft_input_budget_tokens(), hard_budget=hard,
                raw_token_estimate=raw_tokens, final_token_estimate=final_tokens,
                loaded_summary_unit_id=(loaded.content.get("unit_id") if loaded else None),
                loaded_summary_coverage=(loaded.content.get("covered_through_message_id") if loaded else None),
                new_history_turn_count=sum(item.type == ContextItemType.CONVERSATION_TURN for item in run_context.items),
                history_compression_triggered=history_triggered,
                new_summary_coverage=new_coverage, summary_persist_status=persist_status,
                item_representations=representations,
                current_action_compact_count=sum(
                    kind == "compact" and next(item for item in final_items if item.id == item_id).type == ContextItemType.CURRENT_ACTION
                    for item_id, kind in representations
                ),
                representation_cache_hits=hits, representation_cache_misses=misses,
                compact_exhausted=compact_exhausted, over_hard_budget=over_hard,
            ),
        )

    def consume_history_summary_event(self) -> dict[str, Any] | None:
        """Return a newly-created summary checkpoint once for stream display."""
        event = self._pending_history_summary_event
        self._pending_history_summary_event = None
        return deepcopy(event) if event is not None else None

    def _compact_to_soft_budget(self, items, purpose_stable, purpose_dynamic, tools):
        result = list(items)
        if self._estimate_items(result, purpose_stable, purpose_dynamic, tools) <= self._soft_input_budget_tokens():
            return result
        keep_recent = max(0, self.config.keep_recent_steps)
        actions = [item for item in result if item.type == ContextItemType.CURRENT_ACTION]
        old_actions = actions[:-keep_recent] if keep_recent else actions
        recent_actions = actions[-keep_recent:] if keep_recent else []
        other_items = [
            item for item in result
            if item.type != ContextItemType.CURRENT_ACTION and item.supports_compact
        ]
        # The stages are intentional: reclaim old current-run execution detail
        # before degrading stable resources or planning/evidence Items. Within a
        # stage, prefer the largest deterministic saving.
        # Recent actions are the last-resort stage. Keeping them raw is a
        # preference, not permission to exceed the model input budget.
        for candidates in (old_actions, other_items, recent_actions):
            savings = []
            for item in candidates:
                compact = item.compact()
                saving = max(0, item.token_estimate - compact.token_estimate)
                savings.append((saving, item.layout_key, item, compact))
            for _, _, original, compact in sorted(savings, key=lambda row: (-row[0], row[1])):
                index = result.index(original)
                result[index] = compact
                if self._estimate_items(result, purpose_stable, purpose_dynamic, tools) <= self._soft_input_budget_tokens():
                    return result
        return result

    def _project_current_run(self, memory: AgentMemory, start: int) -> list[ContextItem]:
        projected: list[ContextItem] = []
        action_index = planning_index = 0
        for index, step in enumerate(memory.steps[start:]):
            cached = self._current_item_cache.get(id(step))
            if cached is not None:
                projected.append(cached)
                if cached.type == ContextItemType.CURRENT_ACTION:
                    action_index += 1
                elif cached.type == ContextItemType.CURRENT_PLANNING:
                    planning_index += 1
                continue
            if isinstance(step, TaskStep):
                item = ContextItem.from_input(ContextItemInput(
                    id=f"current_task:{index}", type=ContextItemType.CURRENT_TASK,
                    content={"text": step.task or ""},
                    metadata={"layout_order": index},
                ))
                projected.append(item)
            elif isinstance(step, ActionStep):
                content = {
                    "step_number": getattr(step, "step_number", action_index + 1),
                    "tool_calls": self._to_json_value(getattr(step, "tool_calls", None)),
                    "observations": self._to_json_value(getattr(step, "observations", None)),
                    "error": str(getattr(step, "error", "")) if getattr(step, "error", None) else None,
                    "result": self._to_json_value(getattr(step, "action_output", None)),
                    "messages": [self._message_to_dict(message) for message in step.to_messages()],
                }
                item = ContextItem.from_input(ContextItemInput(
                    id=f"current_action:{action_index}", type=ContextItemType.CURRENT_ACTION,
                    content=content,
                    metadata={"layout_order": action_index},
                ))
                projected.append(item)
                action_index += 1
            elif step.__class__.__name__ == "PlanningStep":
                item = ContextItem.from_input(ContextItemInput(
                    id=f"current_planning:{planning_index}", type=ContextItemType.CURRENT_PLANNING,
                    content={"text": "\n".join(extract_message_text(m) for m in step.to_messages())},
                    metadata={"layout_order": planning_index},
                ))
                projected.append(item)
                planning_index += 1
            else:
                continue
            self._current_item_cache[id(step)] = item
        return projected

    def _persist_candidate(self, candidate: HistorySummaryCandidate) -> str:
        sink = self.config.history_summary_sink
        if sink is None:
            return "not_configured"
        try:
            sink(candidate)
            return "succeeded"
        except Exception:
            logger.exception("History summary persistence failed; using run-local candidate")
            return "failed"

    def _purpose_messages(self, *, purpose, task, final_answer_templates):
        if purpose != "final_answer":
            return [], []
        if not final_answer_templates:
            raise ValueError("final_answer purpose requires final_answer_templates")
        from jinja2 import StrictUndefined, Template
        template = final_answer_templates["final_answer"]
        return (
            [{"role": "system", "content": [{"type": "text", "text": template["pre_messages"]}]}],
            [{"role": "user", "content": [{"type": "text", "text": Template(template["post_messages"], undefined=StrictUndefined).render(task=task or "")}]}],
        )

    def _estimate_items(self, items, stable, dynamic, tools):
        return self._message_tokens([*self.build_context_messages(items), *stable, *dynamic]) + self._tools_tokens(tools)

    def _message_tokens(self, messages):
        return max(0, int(sum(len(extract_message_text(message)) for message in messages) / self.config.chars_per_token))

    def _tools_tokens(self, tools):
        return int(len(json.dumps(tools, ensure_ascii=False, default=str)) / self.config.chars_per_token) if tools else 0

    def _record_compression(self, records):
        self._step_local_log.extend(records)
        self.compression_calls_log.extend(records)

    def get_step_compression_stats(self):
        return {"calls": len(self._step_local_log), "records": list(self._step_local_log)}

    def get_all_compression_stats(self):
        return {"calls": len(self.compression_calls_log), "records": list(self.compression_calls_log)}

    def get_token_counts(self):
        return {"uncompressed": self._last_uncompressed_token_count, "compressed": self._last_compressed_token_count}

    def export_summary(self):
        return {"history_candidate": self._history_candidate}

    def build_compressed_snapshot(self, model, memory, current_run_start_idx):
        final = self.assemble_final_context(model=model, memory=memory, current_run_start_idx=current_run_start_idx)
        return final.messages, {"token_counts": self.get_token_counts(), "compression_stats": self.get_step_compression_stats()}

    def render_memory_messages(self, memory):
        messages = []
        if memory.system_prompt:
            messages.extend(memory.system_prompt.to_messages())
        for step in memory.steps:
            messages.extend(step.to_messages())
        return messages

    def register_item(self, item):
        normalized = self._item_source([item])[0]
        with self._lock:
            if any(existing.id == normalized.id for existing in self._items):
                raise ValueError(f"duplicate context item id: {normalized.id}")
            self._items.append(normalized)

    def clear_items(self):
        with self._lock:
            self._items.clear()

    def get_registered_items(self):
        with self._lock:
            return list(self._items)

    def replace_items(self, items):
        normalized = self._item_source(items)
        with self._lock:
            self._items = normalized

    def build_context_messages(self, items=None):
        from .rendering import ContextItemRenderer
        return ContextItemRenderer().render(sorted(self._item_source(items), key=lambda item: item.layout_key))

    def build_system_prompt(self):
        return self.build_context_messages()

    def _item_source(self, items):
        source = list(items) if items is not None else self.get_registered_items()
        if not source:
            return []
        if all(isinstance(item, ContextItem) for item in source):
            return source
        if any(isinstance(item, ContextItem) for item in source):
            raise TypeError("context items cannot mix public inputs and normalized items")
        return normalize_context_inputs(source)

    @staticmethod
    def _canonical_tools(tools):
        return sorted(list(tools), key=lambda tool: json.dumps(ContextManager._normalize(tool), sort_keys=True, default=str))

    @staticmethod
    def _normalize(value):
        if isinstance(value, dict):
            return {str(k): ContextManager._normalize(v) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
        if isinstance(value, (list, tuple)):
            return [ContextManager._normalize(v) for v in value]
        if hasattr(value, "model_dump"):
            return ContextManager._normalize(value.model_dump())
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return {"name": getattr(value, "name", value.__class__.__name__)}

    @staticmethod
    def _message_to_dict(message):
        if isinstance(message, dict):
            return ContextManager._to_json_value(message)
        role = getattr(message.role, "value", message.role)
        return {"role": str(role), "content": ContextManager._to_json_value(message.content)}

    @staticmethod
    def _to_json_value(value):
        """Convert runtime memory values into detached JSON-compatible payloads."""
        if isinstance(value, dict):
            return {str(key): ContextManager._to_json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ContextManager._to_json_value(item) for item in value]
        if isinstance(value, Enum):
            return ContextManager._to_json_value(value.value)
        if is_dataclass(value) and not isinstance(value, type):
            return ContextManager._to_json_value(asdict(value))
        if hasattr(value, "model_dump"):
            return ContextManager._to_json_value(value.model_dump(mode="json"))
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _fingerprint(self, value):
        encoded = json.dumps(self._normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _stable_item_fingerprints(self, items, purpose, tools):
        stable = {item.id: self._fingerprint(item.content) for item in items if item.type in {
            ContextItemType.SYSTEM, ContextItemType.TOOL, ContextItemType.SKILL,
            ContextItemType.MANAGED_AGENT, ContextItemType.EXTERNAL_AGENT,
        }}
        if purpose:
            stable["purpose"] = self._fingerprint(purpose)
        if tools:
            stable["tools"] = self._fingerprint(tools)
        return stable

    def _change_reasons(self, current, item_fingerprints):
        if self._previous_stable_fingerprint is None:
            self._previous_stable_items = item_fingerprints
            return ["initial_request"]
        if self._previous_stable_fingerprint == current:
            return []
        reasons = []
        if self._previous_stable_items.get("tools") != item_fingerprints.get("tools"):
            reasons.append("tool_schema_version")
        if self._previous_stable_items.get("purpose") != item_fingerprints.get("purpose"):
            reasons.append("context_purpose")
        if {k:v for k,v in self._previous_stable_items.items() if k not in {"tools","purpose"}} != {k:v for k,v in item_fingerprints.items() if k not in {"tools","purpose"}}:
            reasons.append("system_prompt_version")
        self._previous_stable_items = item_fingerprints
        return reasons or ["unexpected_nondeterminism"]
