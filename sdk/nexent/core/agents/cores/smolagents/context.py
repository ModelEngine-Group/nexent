# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Managed context path thin adapter.

All context policy and final payload assembly belongs to ContextManager.  This
runtime only adapts CoreAgent lifecycle calls to the ContextManager API.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from copy import deepcopy
from typing import Any, Mapping

from smolagents.memory import ActionStep, AgentMemory, TaskStep
from smolagents.models import ChatMessage, MessageRole, Model

from nexent.core.agents.context.budget import extract_message_text
from nexent.core.agents.context.evidence import ContextEvidenceCollector
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.models import ContextItem, ContextItemInput, ContextItemType
from nexent.core.agents.context.run_context import ManagedRunContext
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

    @property
    def context_manager(self) -> ContextManager:
        """Return the manager permanently bound to this runtime."""
        return self._context_manager

    def replace_items(self, items: Sequence[ContextItemCandidate] | None) -> None:
        """Replace this runtime's run-local fine-grained item snapshot."""
        self.items = list(items or ())
        self._run_context = None

    def prepare_run(self, *, memory: AgentMemory, fallback_system_prompt: str) -> None:
        self._evidence.reset()
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
        final_context = self.context_manager.assemble_context_items(
            model=adapt_context_model(model),
            current_items=self._memory_adapter._project_current_run(memory, current_run_start_idx),
            tools=context_tool_views(tools),
            purpose="step",
            run_context=self._ensure_run_context(memory),
            request_system_messages=context_messages(request_system_messages),
            request_tail_messages=context_messages(request_tail_messages),
        )
        self._evidence.record_call(final_context.evidence)
        return final_context

    def recover_step(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[ModelTool] | None = None,
        request_system_messages: Sequence[ChatMessage | dict[str, object]] = (),
        request_tail_messages: Sequence[ChatMessage | dict[str, object]] = (),
    ) -> FinalContext:
        """Force a source-backed rebuild after explicit Provider overflow."""
        final_context = self.context_manager.assemble_context_items(
            model=adapt_context_model(model),
            current_items=self._memory_adapter._project_current_run(memory, current_run_start_idx),
            tools=context_tool_views(tools),
            purpose="step",
            run_context=self._ensure_run_context(memory),
            force_compaction=True,
            request_system_messages=context_messages(request_system_messages),
            request_tail_messages=context_messages(request_tail_messages),
        )
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
        self._evidence.record_call(final_context.evidence)
        return final_context

    def recover_final_answer(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        task: str,
        final_answer_templates: Mapping[str, Mapping[str, str]],
        tools: Sequence[ModelTool] | None = None,
    ) -> FinalContext:
        """Force a final-answer rebuild after explicit Provider overflow."""
        final_context = self.context_manager.assemble_context_items(
            model=adapt_context_model(model),
            current_items=self._memory_adapter._project_current_run(memory, current_run_start_idx),
            tools=context_tool_views(tools),
            purpose="final_answer",
            task=task,
            final_answer_templates=final_answer_templates,
            run_context=self._ensure_run_context(memory),
            force_compaction=True,
        )
        self._evidence.record_call(final_context.evidence)
        return final_context

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
        self._current_item_cache = manager._current_item_cache
        self._to_json_value = manager._to_json_value
        self.build_context_messages = manager.build_context_messages

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
                        metadata={"layout_order": index, "run_order": index},
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
                        metadata={"layout_order": action_index, "run_order": index},
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
