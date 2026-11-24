# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Managed context path thin adapter.

All context policy and final payload assembly belongs to ContextManager.  This
runtime only adapts CoreAgent lifecycle calls to the ContextManager API.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence
from copy import copy, deepcopy
from dataclasses import replace
from typing import Any, Mapping

from smolagents.memory import ActionStep, AgentMemory, TaskStep
from smolagents.models import ChatMessage, MessageRole, Model

from nexent.core.agents.context.budget import extract_message_text
from nexent.core.agents.context.evidence import ContextEvidenceCollector
from nexent.core.agents.context.maintenance import complete_agent_context as complete_context
from nexent.core.agents.context.maintenance import finish_agent_context
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.models import ContextItem, ContextItemInput, ContextItemType
from nexent.core.agents.context.run_context import ManagedRunContext
from nexent.core.agents.context.usage import ContextUsageBaseline
from nexent.core.agents.contracts.context import ContextEvidence, ContextMessage, ContextToolView, FinalContext
from nexent.core.agents.cores.smolagents.context_contracts import (
    ContextRuntime as ContextRuntime,
)
from nexent.core.agents.cores.smolagents.context_contracts import (
    ModelTool,
)
from nexent.core.agents.cores.smolagents.context_contracts import (
    UnconfiguredContextRuntime as UnconfiguredContextRuntime,
)


ModelMessage = ChatMessage | dict[str, object]
logger = logging.getLogger("agent_context.runtime")
_UNCONFIGURED_RUNTIME_ERROR = "CoreAgent requires a context runtime from the agent factory"


ContextItemCandidate = ContextItemInput | ContextItem


class ManagedContextRuntime:
    """Adapter for the ContextManager-owned managed path."""

    def __init__(
        self,
        context_manager: ContextManager,
        items: Sequence[ContextItemCandidate] | None = None,
    ) -> None:
        self._context_manager = context_manager
        self.items = list(items or ())
        self._run_context: ManagedRunContext | None = None
        self._evidence = ContextEvidenceCollector()
        self._memory_adapter = SmolagentsMemoryAdapter(context_manager)
        self.usage_baseline = ContextUsageBaseline()
        self.last_maintenance_evidence = None
        self._execution_completions = set()
        self._request_system_messages = ()
        self._request_tail_messages = ()

    @property
    def context_manager(self) -> ContextManager:
        """Return the manager permanently bound to this runtime."""
        return self._context_manager

    def replace_items(self, items: Sequence[ContextItemCandidate] | None) -> None:
        """Replace this runtime's run-local fine-grained item snapshot."""
        self.items = list(items or ())
        self._run_context = None
        self.usage_baseline.invalidate()

    def prepare_run(self, *, memory: AgentMemory, fallback_system_prompt: str) -> None:
        self._evidence.reset()
        self.usage_baseline = ContextUsageBaseline()
        self.last_maintenance_evidence = None
        self._execution_completions = set()
        self._request_system_messages = ()
        self._request_tail_messages = ()
        self._run_context = self.context_manager.prepare_items_context(
            fallback_system_prompt=fallback_system_prompt,
            items=self.items,
        )

    def _ensure_run_context(self, memory: AgentMemory) -> ManagedRunContext:
        if self._run_context is None:
            self._run_context = self.context_manager.prepare_items_context(
                fallback_system_prompt="",
                items=self.items,
            )
        return self._run_context

    def prepare_step(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[ModelTool] | None = None,
        request_system_messages: Sequence[ChatMessage | dict[str, object]] = (),
        request_tail_messages: Sequence[ChatMessage | dict[str, object]] = (),
    ) -> FinalContext:
        self._request_system_messages = tuple(context_messages(request_system_messages))
        self._request_tail_messages = tuple(context_messages(request_tail_messages))
        final_context = self.context_manager.assemble_context_items(
            model=adapt_context_model(model),
            current_items=self._memory_adapter._project_current_run(memory, current_run_start_idx),
            tools=context_tool_views(tools),
            purpose="step",
            run_context=self._ensure_run_context(memory),
            request_system_messages=self._request_system_messages,
            request_tail_messages=self._request_tail_messages,
        )
        if hasattr(model, "_agent_context"):
            model._agent_context = self.context_manager.agent_history_boundary()
        self.capture_request(final_context.messages, final_context.tools, model)
        final_context = self._with_usage_evidence(final_context, model)
        self._evidence.record_call(final_context.evidence)
        return final_context

    def prepare_final_answer(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        task: str,
        final_answer_templates: Mapping[str, Mapping[str, str]],
        tools: Sequence[ModelTool] | None = None,
    ) -> FinalContext:
        final_context = self.context_manager.assemble_context_items(
            model=adapt_context_model(model),
            current_items=self._memory_adapter._project_current_run(memory, current_run_start_idx),
            tools=context_tool_views(tools),
            purpose="final_answer",
            task=task,
            final_answer_templates=final_answer_templates,
            run_context=self._ensure_run_context(memory),
        )
        if hasattr(model, "_agent_context"):
            model._agent_context = self.context_manager.agent_history_boundary()
        self.capture_request(final_context.messages, final_context.tools, model)
        final_context = self._with_usage_evidence(final_context, model)
        self._evidence.record_call(final_context.evidence)
        return final_context

    def _with_usage_evidence(self, final, model, phase="prepare"):
        evidence = replace(final.evidence, maintenance_phase=phase,
            usage_source=self.usage_baseline.source,
            provider_input_tokens=self.usage_baseline.actual_input_tokens,
            calibrated_input_estimate=self.usage_baseline.estimate(
                self._estimate(final.messages, final.tools), self._model_key(model)))
        return replace(final, evidence=evidence)

    @staticmethod
    def _model_key(model):
        profile = getattr(model, "profile", None)
        if profile is not None:
            return (profile.identity.tenant_id, profile.outlet_id, profile.config_revision,
                    profile.identity.request_model_id)
        return (id(model), getattr(model, "model_id", None))

    def _estimate(self, messages, tools):
        return self.context_manager._message_tokens(messages) + self.context_manager._tools_tokens(
            self.context_manager._canonical_tools(context_tool_views(tools) or ()),
        )

    def capture_request(self, messages, tools, model):
        """Capture the actual main invocation after overlays and guardrails."""
        self.usage_baseline.capture(self._estimate(messages, tools), self._model_key(model))

    def complete_step(self, *, model, memory, current_run_start_idx, response, tools=None,
                      request_system_messages=None, request_tail_messages=None):
        """Maintain only accepted steps after all native tool results are present."""
        if response is None or getattr(response, "nexent_context_accepted", False) is not True:
            logger.info("event=context_run_local_skipped reason=not_context_accepted")
            return None
        from nexent.core.model_service.contracts import AssistantMessage

        canonical = response if isinstance(response, AssistantMessage) else getattr(response, "raw", None)
        stop_event = getattr(model, "stop_event", None)
        if not isinstance(canonical, AssistantMessage):
            logger.info("event=context_run_local_skipped reason=no_physical_response")
            return None
        self.usage_baseline.accept(canonical.usage.input_tokens if canonical.usage.origin == "provider" else None)
        def cancelled():
            return stop_event is not None and stop_event.is_set() is True
        manager = self.context_manager
        prior_view = (manager._agent_epoch, manager._agent_history, set(manager._agent_covered),
                      manager._selected_agent_history)
        try:
            self.last_run_local_summary = complete_context(manager=self.context_manager, response=canonical,
                model=adapt_context_model(model), cancelled=cancelled)
            try:
                self._complete_sent_execution_views(canonical, adapt_context_model(model), cancelled)
            except Exception:
                logger.warning("event=context_execution_view_failed", exc_info=True)
            if self.last_run_local_summary is not None:
                self.usage_baseline.invalidate()
        finally:
            if cancelled() and manager._agent_epoch == prior_view[0]:
                manager._agent_history, manager._agent_covered, manager._selected_agent_history = prior_view[1:]
            canonical._agent_input = None
        return None

    def _complete_sent_execution_views(self, response, model, cancelled):
        """Keep the existing result view mechanism, limited to this sent boundary."""
        from nexent.core.agents.context.maintenance import AgentHistoryBoundary
        from nexent.core.agents.context.models import CurrentActionContextItem
        from nexent.core.model_service.contracts import AgentCompletionInput

        snapshot = response._agent_input
        usage = response.usage
        counts = (usage.input_tokens, usage.output_tokens)
        manager, history = self.context_manager, self.context_manager.config.execution_history
        if (cancelled() or not isinstance(snapshot, AgentCompletionInput) or history is None
                or not isinstance(snapshot.binding, AgentHistoryBoundary)
                or snapshot.binding.epoch != manager._agent_epoch or usage.origin != "provider"
                or any(type(value) is not int or value < 0 for value in counts)
                or sum(counts) < manager._compaction_trigger_threshold_tokens()
                or manager.processing_mode != "adaptive_compact"):
            return
        identity = (snapshot.request_id, snapshot.attempt)
        if identity in self._execution_completions:
            return
        self._execution_completions.add(identity)
        staged = []
        for encoded in snapshot.binding.executions:
            if cancelled():
                return
            item = CurrentActionContextItem.model_validate_json(encoded)
            record = history.get(item.content["execution_key"])
            if record is None or (record.model_action or {}).get("dispatch_state") != "dispatched":
                continue
            pending_record = copy(record)
            try:
                compact = manager._compact_execution(item, model, record_override=pending_record)
            except Exception:
                continue
            finally:
                record.called |= pending_record.called
                record.attempted |= pending_record.attempted
            if compact is None or manager._estimate_items([compact], [], [], []) >= manager._estimate_items([item], [], [], []):
                continue
            view = {name: compact.content[name] for name in ("summary", "preview")
                    if isinstance(compact.content.get(name), str)}
            if view:
                staged.append((item, compact, record, pending_record, view))
        if cancelled():
            return
        for item, compact, record, pending_record, view in staged:
            manager._representation_overrides[item.id] = (manager._fingerprint(item.content), compact)
            record.summary = pending_record.summary
            record.model_view = view

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ChatMessage | dict[str, object]]:
        """Return display-only memory messages without compression side effects."""
        return self._memory_adapter.render_memory_messages(memory)

    def compression_stats(self) -> dict[str, object]:
        return self.context_manager.get_step_compression_stats()

    def global_compression_stats(self) -> dict[str, object]:
        return self.context_manager.get_all_compression_stats()

    def token_counts(self) -> dict[str, int | None]:
        return self.context_manager.get_token_counts()

    def consume_history_summary_event(self) -> dict[str, object] | None:
        return self.context_manager.consume_history_summary_event()

    def finish_run(self, *, model, memory, current_run_start_idx, final_output, cancelled=None):
        """Only the successful root loop may propose a completed-turn checkpoint."""
        stop = getattr(model, "stop_event", None)
        try:
            projection = SmolagentsMemoryAdapter(self.context_manager)
            # Final facts may have completed after the last request-time projection.
            projection._current_item_cache = {}
            return finish_agent_context(manager=self.context_manager, run_context=self._ensure_run_context(memory),
                current_items=projection._project_current_run(memory, current_run_start_idx), final_output=final_output, model=adapt_context_model(model),
                cancelled=cancelled or (lambda: stop is not None and stop.is_set() is True))
        except Exception:
            logger.warning("event=context_completed_turn_checkpoint_failed", exc_info=True)
            return None

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        return self._evidence.finalize(status=status)

    @property
    def chars_per_token(self) -> float:
        return self.context_manager.config.chars_per_token

    @property
    def token_threshold(self) -> int | None:
        return self.context_manager.config.token_threshold

    @property
    def context_window_tokens(self) -> int | None:
        return self.context_manager.config.context_window_tokens

    @property
    def effective_input_limit_tokens(self) -> int | None:
        return self.context_manager.effective_input_limit_tokens

    @property
    def processing_mode(self) -> str | None:
        return self.context_manager.processing_mode


class SmolagentsMemoryAdapter:
    """Project native memory while retaining the CM-owned representation cache."""

    def __init__(self, manager):
        self._manager = manager
        self._current_item_cache = manager._current_item_cache
        self._to_json_value = manager._to_json_value
        self.build_context_messages = manager.build_context_messages

    def _neutral_action_content(self, step: ActionStep, action_index: int) -> dict[str, Any]:
        """Preserve completed-action evidence without upstream protocol labels."""
        fields = getattr(step, "execution_fields", None)
        if not isinstance(fields, dict):
            fields = {}
            observation = getattr(step, "observations", None)
            output = getattr(step, "action_output", None)
            if observation is not None:
                fields["OUTPUT"] = str(observation)
            if output is not None and str(output) != str(observation or ""):
                fields["RETURN_VALUE"] = str(output)
            if getattr(step, "error", None):
                fields["ERROR"] = str(step.error)
            if not fields:
                fields["STDOUT"] = ""
        return {
            "step_number": getattr(step, "step_number", action_index + 1),
            "assistant_output": getattr(step, "model_output", None) or "",
            "tool_calls": self._to_json_value(getattr(step, "tool_calls", None)),
            "execution_fields": dict(fields),
            "execution_key": getattr(step, "execution_key", None),
            "loaded_result": getattr(step, "execution_loaded", False),
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
                        metadata={"layout_order": index, "run_order": index},
                    )
                )
                projected.append(item)
            elif isinstance(step, ActionStep):
                content = self._neutral_action_content(step, action_index)
                item = ContextItem.from_input(
                    ContextItemInput(
                        id=f"current_action:{action_index}",
                        type=ContextItemType.CURRENT_ACTION,
                        content=content,
                        metadata={
                            "layout_order": action_index,
                            "run_order": index,
                            "use_result_observations": self._manager.use_result_observations,
                        },
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
                        metadata={"layout_order": planning_index, "run_order": index},
                    )
                )
                projected.append(item)
                planning_index += 1
            else:
                continue
            self._current_item_cache[id(step)] = item
        return projected

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


class SmolagentsContextModel:
    """Convert neutral auxiliary messages without changing the selected model state."""

    def __init__(self, model):
        object.__setattr__(self, "_model", model)

    def __getattr__(self, name):
        return getattr(self._model, name)

    def __setattr__(self, name, value):
        setattr(self._model, name, value)

    @property
    def model_id(self):
        """Keep CM audit/cache identity for custom models without an explicit ID."""
        return (
            getattr(self._model, "model_id", None)
            or getattr(self._model, "model_name", None)
            or self._model.__class__.__name__
        )

    @property
    def context_call_parameters(self):
        return inspect.signature(self._model.__call__).parameters

    def __call__(self, messages, **kwargs):
        converted = [
            message
            if isinstance(message, (ChatMessage, dict))
            else ChatMessage(role=MessageRole(message.role), content=deepcopy(message.content))
            for message in messages
        ]
        return self._model(converted, **kwargs)


def adapt_context_model(model):
    """Reuse a port when a legacy entry already adapted this model."""
    return model if isinstance(model, SmolagentsContextModel) else SmolagentsContextModel(model)


def context_messages(messages):
    """Detach native request-only messages while keeping the existing CM audit rule."""
    return [
        ContextMessage(
            role=str(getattr(message.role, "value", message.role)),
            content=deepcopy(message.content),
            fingerprint_payload=ContextManager._normalize(message),
        )
        if isinstance(message, ChatMessage)
        else deepcopy(message)
        for message in messages
    ]


def context_tool_views(tools):
    """Remove executable objects without changing legacy budget or fingerprint inputs."""
    if tools is None:
        return None
    return [
        deepcopy(tool)
        if isinstance(tool, dict)
        else ContextToolView(
            fingerprint_payload=ContextManager._normalize(tool),
            budget_text=str(tool),
        )
        for tool in tools
    ]
