# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""smolagents lifecycle interfaces without importing ContextManager implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from smolagents.memory import AgentMemory
from smolagents.models import ChatMessage, MessageRole, Model
from smolagents.tools import Tool

from nexent.core.agents.context.models import ContextItem
from nexent.core.agents.contracts.context import ContextEvidence, ContextItemInput, ContextMessage, FinalContext


if TYPE_CHECKING:
    from nexent.core.agents.context.manager import ContextManager

ContextItemCandidate = ContextItemInput | ContextItem
ModelMessage = ChatMessage | dict[str, object]
ModelTool = Tool | dict[str, object]
_UNCONFIGURED_RUNTIME_ERROR = "CoreAgent requires a context runtime from the agent factory"


def native_context_messages(messages):
    """Restore the native model input shape only at the Core's send boundary."""
    return [
        ChatMessage(role=MessageRole(message.role), content=message.content)
        if isinstance(message, ContextMessage)
        else message
        for message in messages
    ]


def native_context_rebuild(context):
    """Keep legacy callback identity unless neutral messages need native conversion."""
    if not any(isinstance(message, ContextMessage) for message in context.messages):
        return context
    return replace(context, messages=native_context_messages(context.messages))


class ContextRuntime(Protocol):
    """Runtime protocol implemented by the ContextManager adapter."""

    context_manager: "ContextManager | None"

    def replace_items(self, items: Sequence[ContextItemCandidate] | None) -> None:
        """Replace the run-local authorized item snapshot."""

    def prepare_run(self, *, memory: AgentMemory, fallback_system_prompt: str) -> None:
        """Initialize the run's system state before a TaskStep is appended."""

    def prepare_step(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[ModelTool] | None = None,
        request_system_messages: Sequence[ModelMessage] = (),
        request_tail_messages: Sequence[ModelMessage] = (),
    ) -> FinalContext:
        """Return all model messages for the current step."""

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
        """Return all model messages for final-answer generation."""

    def recover_step(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[ModelTool] | None = None,
        request_system_messages: Sequence[ModelMessage] = (),
        request_tail_messages: Sequence[ModelMessage] = (),
    ) -> FinalContext:
        """Force a source-backed step rebuild after Provider overflow."""

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
        """Force a source-backed final-answer rebuild after Provider overflow."""

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        """Return display-only messages without triggering compression."""

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        """Finalize and emit the single evidence record for this agent loop."""

    def compression_stats(self) -> dict[str, object]:
        """Return this step's compression metrics in the common shape."""

    def global_compression_stats(self) -> dict[str, object]:
        """Return compression metrics accumulated by this runtime."""

    def token_counts(self) -> dict[str, int | None]:
        """Return the latest raw and rendered context token counts."""

    def consume_history_summary_event(self) -> dict[str, object] | None:
        """Return a newly-created history checkpoint once, if present."""

    @property
    def chars_per_token(self) -> float:
        """Token-estimation factor for the active context path."""

    @property
    def token_threshold(self) -> int | None:
        """Configured threshold, if the active path has one."""

    @property
    def context_window_tokens(self) -> int | None:
        """Stable model context-window capacity for this runtime."""

    @property
    def effective_input_limit_tokens(self) -> int | None:
        """Effective Provider input limit for this runtime."""

    @property
    def processing_mode(self) -> str | None:
        """Resolved context-processing policy mode."""


class UnconfiguredContextRuntime:
    """Neutral guard used only when a caller bypasses the agent factory."""

    context_manager = None

    def replace_items(self, items: Sequence[ContextItemCandidate] | None) -> None:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def prepare_run(self, *, memory: AgentMemory, fallback_system_prompt: str) -> None:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def prepare_step(
        self,
        *,
        model: Model,
        memory: AgentMemory,
        current_run_start_idx: int,
        tools: Sequence[ModelTool] | None = None,
    ) -> FinalContext:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

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
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def recover_step(self, **kwargs) -> FinalContext:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def recover_final_answer(self, **kwargs) -> FinalContext:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def compression_stats(self) -> dict[str, object]:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}

    def global_compression_stats(self) -> dict[str, object]:
        return {"calls": 0, "records": []}

    def token_counts(self) -> dict[str, int | None]:
        return {"uncompressed": None, "compressed": None}

    def consume_history_summary_event(self) -> dict[str, object] | None:
        return None

    @property
    def chars_per_token(self) -> float:
        return 1.5

    @property
    def token_threshold(self) -> int | None:
        return None

    @property
    def context_window_tokens(self) -> int | None:
        return None

    @property
    def effective_input_limit_tokens(self) -> int | None:
        return None

    @property
    def processing_mode(self) -> str | None:
        return None
