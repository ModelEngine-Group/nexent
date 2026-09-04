"""Managed context assembly for fine-grained items and adaptive compaction."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, Optional, Sequence

from smolagents.memory import ActionStep, AgentMemory, TaskStep
from smolagents.models import ChatMessage, MessageRole

from ...context_runtime.contracts import ContextEvidence, FinalContext
from ...models.final_request_budget import build_final_request_shape
from ..summary_cache import CompressionCallRecord
from .budget import extract_message_text, message_role
from .archive import RunHistoryArchive, SearchArchivedHistoryTool
from .config import ContextManagerConfig
from .history_compression import HistoryCompressor, HistorySummaryCandidate
from .llm_summary import LLMSummary
from .long_term_memory_selector import select_long_term_memory
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
        self._memory_compact_cache: dict[tuple[Any, ...], list[ContextItem]] = {}
        self._archive: RunHistoryArchive | None = None
        self._archive_tool: SearchArchivedHistoryTool | None = None

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
        self,
        memory: AgentMemory,
        fallback_system_prompt: str,
        items: Optional[Sequence[Any]] = None,
    ) -> ManagedRunContext:
        self._history_candidate = None
        self._archive = None
        self._archive_tool = None
        self._current_item_cache.clear()
        source = self._item_source(items)
        if fallback_system_prompt and not any(item.type == ContextItemType.SYSTEM for item in source):
            source.append(
                ContextItem.from_input(
                    ContextItemInput(
                        id="system:fallback",
                        type=ContextItemType.SYSTEM,
                        content={"text": fallback_system_prompt},
                        metadata={"layout_order": -1, "runtime_fallback": True},
                    )
                )
            )
        policy = resolve_policy(self.config.policy_layers)
        selected, decision = select_context_items(source, policy)
        messages = self.build_context_messages(selected)
        stable = [message for message in messages if message_role(message) in {"system", "developer"}]
        dynamic = [message for message in messages if message_role(message) not in {"system", "developer"}]
        return ManagedRunContext(
            item_messages=tuple(messages),
            stable_messages=tuple(stable),
            dynamic_messages=tuple(dynamic),
            selected_item_types=tuple(item.type.value for item in selected),
            items=tuple(selected),
            selection_decision=decision,
        )

    def assemble_final_context(
        self,
        *,
        model: Any,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
        purpose: str = "step",
        task: str | None = None,
        final_answer_templates: Optional[Dict[str, Any]] = None,
        run_context: ManagedRunContext | None = None,
        target_input_budget_tokens: int | None = None,
        emergency_archive: bool = False,
    ) -> FinalContext:
        self._active_request_meter = getattr(model, "_final_request_meter", None)
        run_context = run_context or self.prepare_run_context(memory, "")
        policy = resolve_policy(self.config.policy_layers)
        persisted_items = list(run_context.items)
        if self._history_candidate is not None:
            persisted_items = [
                item
                for item in persisted_items
                if item.type
                not in {
                    ContextItemType.HISTORY_SUMMARY,
                    ContextItemType.CONVERSATION_TURN,
                }
            ]
            persisted_items.append(self._history_candidate.as_item())
        current_items = self._project_current_run(memory, current_run_start_idx)
        items = sorted([*persisted_items, *current_items], key=lambda item: item.layout_key)
        purpose_stable, purpose_dynamic = self._purpose_messages(
            purpose=purpose,
            task=task,
            final_answer_templates=final_answer_templates,
        )
        archived_item_count = 0
        if emergency_archive:
            self.activate_emergency_archive(hard_budget=target_input_budget_tokens or self._hard_input_budget_tokens())
        runtime_tools = list(tools or ())
        if emergency_archive and self._archive_tool is not None and all(
            getattr(tool, "name", None) != self._archive_tool.name for tool in runtime_tools
        ):
            runtime_tools.append(self._archive_tool)
        canonical_tools = self._canonical_tools(runtime_tools)
        if emergency_archive:
            items, archived_item_count = self._select_emergency_working_set(
                items, purpose_stable, purpose_dynamic, canonical_tools,
                target_tokens=target_input_budget_tokens or self._hard_input_budget_tokens(),
            )
        raw_tokens = self._estimate_items(items, purpose_stable, purpose_dynamic, canonical_tools)
        soft_budget = self._soft_input_budget_tokens()
        hard_budget = self._hard_input_budget_tokens()
        if target_input_budget_tokens is not None:
            if target_input_budget_tokens <= 0:
                raise ValueError("target_input_budget_tokens must be positive")
            soft_budget = min(soft_budget, target_input_budget_tokens)
            hard_budget = min(hard_budget, target_input_budget_tokens)
        final_items = list(items)
        history_triggered = False
        new_coverage = None
        persist_status = "not_attempted"
        self._step_local_log = []

        if (
            policy.processing_mode == ContextProcessingMode.ADAPTIVE_COMPACT
            and raw_tokens > soft_budget
        ):
            summary = next((item for item in final_items if item.type == ContextItemType.HISTORY_SUMMARY), None)
            turns = [item for item in final_items if item.type == ContextItemType.CONVERSATION_TURN]
            if turns:
                history_triggered = True
                result = self._history_compressor.compress(summary, turns, model)
                self._record_compression(result.records)
                if result.candidate is not None:
                    self._history_candidate = result.candidate
                    new_coverage = result.candidate.covered_through_message_id
                    final_items = [
                        item
                        for item in final_items
                        if item.type
                        not in {
                            ContextItemType.HISTORY_SUMMARY,
                            ContextItemType.CONVERSATION_TURN,
                        }
                    ]
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
                final_items,
                purpose_stable,
                purpose_dynamic,
                canonical_tools,
                model=model,
                target_tokens=soft_budget,
            )

        final_items.sort(key=lambda item: item.layout_key)
        rendered = self.build_context_messages(final_items)
        # Stable item messages remain first for KV-cache reuse.
        stable = [message for message in rendered if message_role(message) in {"system", "developer"}]
        dynamic = [message for message in rendered if message_role(message) not in {"system", "developer"}]
        messages = [*stable, *purpose_stable, *dynamic, *purpose_dynamic]
        final_tokens = self._request_tokens(messages, canonical_tools)
        self._last_uncompressed_token_count = raw_tokens
        self._last_compressed_token_count = final_tokens
        hard = hard_budget
        over_hard = final_tokens > hard
        compact_exhausted = over_hard
        budget_failure_reason = None
        if over_hard:
            budget_failure_reason = self._budget_failure_reason(
                final_items,
                purpose_stable,
                purpose_dynamic,
                canonical_tools,
                hard_budget=hard,
                compression_attempted=(
                    bool(self._step_local_log)
                    or any(
                        str(item.metadata.get("representation", "raw")) != "raw"
                        for item in final_items
                    )
                ),
            )
            logger.warning("Context remains over hard budget after safe compact: %s > %s", final_tokens, hard)

        representations = tuple((item.id, str(item.metadata.get("representation", "raw"))) for item in final_items)
        hits = sum(item.representation_cache_stats[0] for item in items)
        misses = sum(item.representation_cache_stats[1] for item in items)
        loaded = next((item for item in run_context.items if item.type == ContextItemType.HISTORY_SUMMARY), None)
        stable_fp = self._fingerprint({"messages": [*stable, *purpose_stable], "tools": canonical_tools})
        reasons = self._change_reasons(
            stable_fp, self._stable_item_fingerprints(final_items, purpose_stable, canonical_tools)
        )
        self._previous_stable_fingerprint = stable_fp
        selected_ids = tuple(item.id for item in final_items)
        from .composition import estimate_context_segments

        composition_estimate = estimate_context_segments(
            final_items,
            purpose_messages=[*purpose_stable, *purpose_dynamic],
            tools=canonical_tools,
        )
        message_roles = tuple(message_role(message) for message in messages)
        system_messages = [message for message in messages if message_role(message) in {"system", "developer"}]
        history_messages = [message for message in messages if message_role(message) not in {"system", "developer"}]
        return FinalContext(
            messages=messages,
            tools=canonical_tools,
            runtime_tools=tuple(runtime_tools),
            evidence=ContextEvidence(
                purpose=purpose,
                selected_item_ids=selected_ids,
                selected_item_types=tuple(item.type.value for item in final_items),
                context_composition_estimate=tuple(composition_estimate.items()),
                stable_message_count=len(stable) + len(purpose_stable),
                dynamic_message_count=len(dynamic) + len(purpose_dynamic),
                compression_records=tuple(self._step_local_log),
                stable_prefix_fingerprint=stable_fp,
                prefix_change_reasons=tuple(reasons),
                policy_fingerprint=run_context.selection_decision.policy_fingerprint
                if run_context.selection_decision
                else None,
                processing_mode=policy.processing_mode.value,
                soft_budget=soft_budget,
                hard_budget=hard,
                raw_token_estimate=raw_tokens,
                final_token_estimate=final_tokens,
                loaded_summary_unit_id=(loaded.content.get("unit_id") if loaded else None),
                loaded_summary_coverage=(loaded.content.get("covered_through_message_id") if loaded else None),
                new_history_turn_count=sum(
                    item.type == ContextItemType.CONVERSATION_TURN for item in run_context.items
                ),
                history_compression_triggered=history_triggered,
                new_summary_coverage=new_coverage,
                summary_persist_status=persist_status,
                item_representations=representations,
                current_action_compact_count=sum(
                    kind == "compact"
                    and next(item for item in final_items if item.id == item_id).type == ContextItemType.CURRENT_ACTION
                    for item_id, kind in representations
                ),
                representation_cache_hits=hits,
                representation_cache_misses=misses,
                compact_exhausted=compact_exhausted,
                over_hard_budget=over_hard,
                budget_failure_reason=budget_failure_reason,
                messages_fingerprint=self._fingerprint(messages),
                tools_fingerprint=self._fingerprint(canonical_tools),
                system_messages_fingerprint=self._fingerprint(system_messages),
                history_messages_fingerprint=self._fingerprint(history_messages),
                final_answer_prompt_fingerprint=(
                    self._fingerprint(purpose_dynamic)
                    if purpose == "final_answer" else None
                ),
                message_roles=message_roles,
                history_message_roles=tuple(message_role(message) for message in history_messages),
                compression_attempted=bool(self._step_local_log),
                fallback_compaction_used=any(representation != "raw" for _, representation in representations),
                archive_active=emergency_archive,
                archived_item_count=archived_item_count,
                retained_item_count=len(final_items),
                recall_invocation_count=self._archive.recall_invocations if self._archive else 0,
                recalled_tokens=self._archive.recalled_tokens if self._archive else 0,
            ),
        )

    @property
    def archive_tool(self) -> SearchArchivedHistoryTool | None:
        return self._archive_tool

    def activate_emergency_archive(self, *, hard_budget: int) -> SearchArchivedHistoryTool:
        if self._archive is None:
            self._archive = RunHistoryArchive(
                run_id=uuid.uuid4().hex,
                hard_input_budget=hard_budget,
                chars_per_token=self.config.chars_per_token,
            )
            self._archive_tool = SearchArchivedHistoryTool(self._archive)
        return self._archive_tool

    def _select_emergency_working_set(self, items, stable, dynamic, tools, *, target_tokens: int):
        turns = [item for item in items if item.type == ContextItemType.CONVERSATION_TURN]
        actions = [item for item in items if item.type == ContextItemType.CURRENT_ACTION]
        considered = set(item.id for item in [*turns[-3:], *actions[-4:]])
        protected = set(item.id for item in [*turns[-1:], *actions[-1:]])
        retained = [
            item for item in items
            if item.type not in {ContextItemType.CONVERSATION_TURN, ContextItemType.CURRENT_ACTION}
            or item.id in considered
        ]
        optional = [item for item in retained if item.id in considered and item.id not in protected]
        for item in optional:
            if self._estimate_items(retained, stable, dynamic, tools) <= target_tokens:
                break
            retained.remove(item)
        retained_ids = {item.id for item in retained}
        omitted = [item for item in items if item.id not in retained_ids]
        for item in omitted:
            self._archive_item(item)
        if omitted:
            manifest = ContextItem.from_input(ContextItemInput(
                id="system:archive_manifest",
                type=ContextItemType.SYSTEM,
                content={"text": (
                    f"Older history was archived ({len(omitted)} items). It may contain prior user turns, "
                    "final answers, tool calls, observations, errors, and results. Call search_archived_history "
                    "only when missing detail is relevant; do not guess archived content."
                )},
                metadata={"layout_order": 9_999, "run_local": True},
            ))
            retained.append(manifest)
        return sorted(retained, key=lambda item: item.layout_key), len(omitted)

    def _archive_item(self, item: ContextItem) -> None:
        if self._archive is None:
            return
        if item.type == ContextItemType.CONVERSATION_TURN:
            self._archive.add(kind="chat_turn", source_id=item.id, content=item.content)
            return
        content = item.content
        for field, kind in (
            ("tool_calls", "tool_call"), ("observations", "observation"),
            ("error", "error"), ("result", "result"),
        ):
            self._archive.add(kind=kind, source_id=item.id, content=content.get(field))

    def _budget_failure_reason(
        self,
        items,
        purpose_stable,
        purpose_dynamic,
        tools,
        *,
        hard_budget: int,
        compression_attempted: bool,
    ) -> str:
        if any(
            self._estimate_items([item], [], [], []) > hard_budget
            for item in items
        ):
            return "single_context_item_oversize"
        fixed_types = {
            ContextItemType.SYSTEM,
            ContextItemType.TOOL,
            ContextItemType.SKILL,
            ContextItemType.MANAGED_AGENT,
            ContextItemType.EXTERNAL_AGENT,
        }
        fixed_items = [item for item in items if item.type in fixed_types]
        if (
            self._estimate_items(
                fixed_items, purpose_stable, purpose_dynamic, tools
            )
            > hard_budget
        ):
            return "fixed_context_over_budget"
        if compression_attempted:
            return "compaction_no_reduction"
        return "final_request_over_hard_budget"

    def consume_history_summary_event(self) -> dict[str, Any] | None:
        """Return a newly-created summary checkpoint once for stream display."""
        event = self._pending_history_summary_event
        self._pending_history_summary_event = None
        return deepcopy(event) if event is not None else None

    def _compact_to_soft_budget(
        self,
        items,
        purpose_stable,
        purpose_dynamic,
        tools,
        *,
        model,
        target_tokens: Optional[int] = None,
    ):
        if target_tokens is None:
            target_tokens = self.config.token_threshold
        result = list(items)
        if self._estimate_items(result, purpose_stable, purpose_dynamic, tools) <= target_tokens:
            return result
        keep_recent = max(0, self.config.keep_recent_steps)
        actions = [item for item in result if item.type == ContextItemType.CURRENT_ACTION]
        old_actions = actions[:-keep_recent] if keep_recent else actions
        recent_actions = actions[-keep_recent:] if keep_recent else []
        long_term_items = [
            item for item in result
            if item.type == ContextItemType.MEMORY
            and (item.metadata.get("version_id") is not None or item.metadata.get("memory_type") == "long_term")
        ]
        other_items = [
            item for item in result
            if item.type != ContextItemType.CURRENT_ACTION and item.supports_compact and item not in long_term_items
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
                if (
                    self._estimate_items(result, purpose_stable, purpose_dynamic, tools)
                    <= target_tokens
                ):
                    return result
        if self.config.enable_long_term_memory_selection and long_term_items:
            return self._select_long_term_memories(
                result, long_term_items, model=model, target_tokens=target_tokens
            )
        return result

    def _select_long_term_memories(self, result, memory_items, *, model, target_tokens: int):
        task_item = next((item for item in result if item.type == ContextItemType.CURRENT_TASK), None)
        task = json.dumps(task_item.content, ensure_ascii=False, default=str) if task_item else ""
        model_id = str(getattr(model, "model_id", None) or getattr(model, "model_name", None)
                       or model.__class__.__name__)
        target_tokens = max(64, target_tokens // 4)
        versions = tuple(sorted(str(item.metadata.get("version_id") or item.id) for item in memory_items))
        cache_key = (*versions, task, target_tokens, model_id)
        cached = self._memory_compact_cache.get(cache_key)
        if cached is not None:
            replacements = {item.id: item for item in cached}
            self._record_compression([CompressionCallRecord(
                call_type="long_term_memory_block_selection", cache_hit=True,
                details={"version_ids": versions, "target_tokens": target_tokens,
                         "model_id": model_id, "outcome": "cache_hit"},
            )])
            return [replacements.get(item.id, item) for item in result]

        documents: dict[str, str] = {}
        by_scope: dict[str, ContextItem] = {}
        for item in memory_items:
            scope = str(item.metadata.get("scope") or item.content.get("memory_level") or "user")
            key = next((name for name in ("memory", "content", "text")
                        if isinstance(item.content.get(name), str)), None)
            if key and scope not in by_scope:
                documents[scope] = item.content[key]
                by_scope[scope] = item
        selected, audit = select_long_term_memory(
            documents, task=task, target_tokens=target_tokens, model=model,
            chars_per_token=self.config.chars_per_token,
        )
        replacements: list[ContextItem] = []
        for scope, item in by_scope.items():
            key = next(name for name in ("memory", "content", "text") if isinstance(item.content.get(name), str))
            content = deepcopy(item.content)
            content[key] = selected.get(scope, "")
            data = item.model_dump(exclude={"content", "token_estimate", "metadata"})
            replacements.append(item.__class__(
                **data, content=content,
                metadata={**deepcopy(item.metadata), "representation": "selected_blocks"},
                token_estimate=max(1, math.ceil(len(content[key]) / self.config.chars_per_token)),
            ))
        self._memory_compact_cache[cache_key] = replacements
        self._record_compression([CompressionCallRecord(
            call_type="long_term_memory_block_selection",
            input_chars=int(audit.get("input_chars", 0)), output_chars=sum(len(value) for value in selected.values()),
            details={**audit, "version_ids": versions, "target_tokens": target_tokens,
                     "model_id": model_id, "persisted": False},
        )])
        replacement_by_id = {item.id: item for item in replacements}
        return [replacement_by_id.get(item.id, item) for item in result]


    def _neutral_action_content(self, step: ActionStep, action_index: int) -> dict[str, Any]:
        """Preserve completed-action evidence without upstream protocol labels."""
        return {
            "step_number": getattr(step, "step_number", action_index + 1),
            "tool_calls": self._to_json_value(getattr(step, "tool_calls", None)),
            "observations": self._to_json_value(getattr(step, "observations", None)),
            "error": str(getattr(step, "error", "")) if getattr(step, "error", None) else None,
            "result": self._to_json_value(getattr(step, "action_output", None)),
        }

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
                item = ContextItem.from_input(
                    ContextItemInput(
                        id=f"current_task:{index}",
                        type=ContextItemType.CURRENT_TASK,
                        content={"text": step.task or ""},
                        metadata={"layout_order": index},
                    )
                )
                projected.append(item)
            elif isinstance(step, ActionStep):
                content = self._neutral_action_content(step, action_index)
                # Render completed actions from structured fields instead of
                # smolagents ActionStep.to_messages(). The upstream rendering
                # injects protocol labels such as "Calling tools:" and
                # "Observation:" into the next model request, which can prime
                # reasoning models to emit a configured stop sequence. The
                # neutral representation preserves the executable action,
                # outcome, error, result, and ordering without changing how
                # the live ReAct step is parsed or executed.
                item = ContextItem.from_input(
                    ContextItemInput(
                        id=f"current_action:{action_index}",
                        type=ContextItemType.CURRENT_ACTION,
                        content=content,
                        metadata={"layout_order": action_index},
                    )
                )
                projected.append(item)
                action_index += 1
            elif step.__class__.__name__ == "PlanningStep":
                item = ContextItem.from_input(
                    ContextItemInput(
                        id=f"current_planning:{planning_index}",
                        type=ContextItemType.CURRENT_PLANNING,
                        content={"text": "\n".join(extract_message_text(m) for m in step.to_messages())},
                        metadata={"layout_order": planning_index},
                    )
                )
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
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": Template(template["post_messages"], undefined=StrictUndefined).render(
                                task=task or ""
                            ),
                        }
                    ],
                }
            ],
        )

    def _estimate_items(self, items, stable, dynamic, tools):
        return self._request_tokens(
            [*self.build_context_messages(items), *stable, *dynamic], tools
        )

    def _request_tokens(self, messages, tools):
        meter = getattr(self, "_active_request_meter", None)
        if meter is not None:
            anchored = meter.estimate_context_candidate(messages, tools)
            if isinstance(anchored, int) and not isinstance(anchored, bool):
                return max(0, anchored)
        structural = build_final_request_shape(
            {"messages": list(messages), "tools": list(tools)}
        ).components.raw_total
        configured = self._message_tokens(messages) + self._tools_tokens(tools)
        return max(structural, configured)

    def _message_tokens(self, messages):
        return max(
            0, int(sum(len(extract_message_text(message)) for message in messages) / self.config.chars_per_token)
        )

    def _tools_tokens(self, tools):
        return (
            int(len(json.dumps(tools, ensure_ascii=False, default=str)) / self.config.chars_per_token) if tools else 0
        )

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
        return final.messages, {
            "token_counts": self.get_token_counts(),
            "compression_stats": self.get_step_compression_stats(),
        }

    def render_memory_messages(self, memory):
        messages = []
        if memory.system_prompt:
            messages.extend(memory.system_prompt.to_messages())
        action_index = 0
        for step in memory.steps:
            if isinstance(step, ActionStep):
                item = ContextItem.from_input(
                    ContextItemInput(
                        id=f"summary_action:{action_index}",
                        type=ContextItemType.CURRENT_ACTION,
                        content=self._neutral_action_content(step, action_index),
                        metadata={"layout_order": action_index},
                    )
                )
                messages.extend(self.build_context_messages([item]))
                action_index += 1
            else:
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
        return sorted(
            list(tools), key=lambda tool: json.dumps(ContextManager._normalize(tool), sort_keys=True, default=str)
        )

    @staticmethod
    def _normalize(value, _active_ids=None, _depth=0):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        class_name = f"{value.__class__.__module__}.{value.__class__.__qualname__}"
        if _depth >= 32:
            return {"__max_depth__": class_name}

        active_ids = _active_ids if _active_ids is not None else set()
        value_id = id(value)
        if value_id in active_ids:
            return {"__cycle__": class_name}
        active_ids.add(value_id)
        try:
            if isinstance(value, dict):
                return {
                    str(key): ContextManager._normalize(item, active_ids, _depth + 1)
                    for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                }
            if isinstance(value, (list, tuple)):
                return [
                    ContextManager._normalize(item, active_ids, _depth + 1)
                    for item in value
                ]
            model_dump = getattr(value, "model_dump", None)
            if callable(model_dump):
                return ContextManager._normalize(
                    model_dump(), active_ids, _depth + 1
                )
            return {"name": getattr(value, "name", value.__class__.__name__)}
        finally:
            active_ids.remove(value_id)

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
        try:
            normalized = self._normalize(value)
        except Exception as error:
            normalized = {
                "__normalization_error__": type(error).__name__,
                "__class__": (
                    f"{value.__class__.__module__}.{value.__class__.__qualname__}"
                ),
            }
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _stable_item_fingerprints(self, items, purpose, tools):
        stable = {
            item.id: self._fingerprint(item.content)
            for item in items
            if item.type
            in {
                ContextItemType.SYSTEM,
                ContextItemType.TOOL,
                ContextItemType.SKILL,
                ContextItemType.MANAGED_AGENT,
                ContextItemType.EXTERNAL_AGENT,
            }
        }
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
        if {k: v for k, v in self._previous_stable_items.items() if k not in {"tools", "purpose"}} != {
            k: v for k, v in item_fingerprints.items() if k not in {"tools", "purpose"}
        }:
            reasons.append("system_prompt_version")
        self._previous_stable_items = item_fingerprints
        return reasons or ["unexpected_nondeterminism"]
