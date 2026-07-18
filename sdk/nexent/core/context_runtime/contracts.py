"""Contracts for the single ContextManager-backed runtime path."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from smolagents.memory import AgentMemory, MemoryStep
    from smolagents.models import ChatMessage, Model
    from smolagents.tools import Tool

    from ..agents.context.manager import ContextManager
    from ..agents.context.models import ContextItem, ContextItemInput

    ContextItemCandidate = ContextItemInput | ContextItem
    ModelMessage = ChatMessage | dict[str, object]
    ModelTool = Tool | dict[str, object]
else:
    AgentMemory = object
    ContextItemCandidate = object
    ContextManager = object
    MemoryStep = object
    Model = object
    ModelMessage = object
    ModelTool = object


_UNCONFIGURED_RUNTIME_ERROR = "CoreAgent requires a context runtime from the agent factory"

@dataclass(frozen=True)
class ContextEvidence:
    selected_item_ids: tuple[str, ...] = ()
    selected_item_types: tuple[str, ...] = ()
    stable_message_count: int = 0
    dynamic_message_count: int = 0
    compression_records: tuple[object, ...] = ()
    stable_prefix_fingerprint: str | None = None
    prefix_change_reasons: tuple[str, ...] = ()
    excluded_item_ids: tuple[str, ...] = ()
    selection_reason_codes: tuple[str, ...] = ()
    policy_fingerprint: str | None = None
    selection_decision_fingerprint: str | None = None
    embedding_mode: str = "none"
    embedding_provider_fingerprint: str | None = None
    embedding_failures: tuple[str, ...] = ()
    representation_cache_hits: int = 0
    representation_cache_misses: int = 0
    model_call_count: int = 0
    loop_status: str | None = None


@dataclass(frozen=True)
class FinalContext:
    """The only context payload permitted to enter a model call."""

    messages: list[ModelMessage]
    tools: list[dict[str, object]] = field(default_factory=list)
    evidence: ContextEvidence = field(default_factory=ContextEvidence)


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

    def truncate_observation(self, memory_step: MemoryStep) -> None:
        """Apply path-specific observation controls without exposing mode checks."""

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        """Return display-only messages without triggering compression."""

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        """Finalize and emit the single evidence record for this agent loop."""

    def compression_stats(self) -> dict[str, object]:
        """Return this step's compression metrics in the common shape."""

    @property
    def chars_per_token(self) -> float:
        """Token-estimation factor for the active context path."""

    @property
    def token_threshold(self) -> int | None:
        """Configured threshold, if the active path has one."""


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

    def truncate_observation(self, memory_step: MemoryStep) -> None:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def compression_stats(self) -> dict[str, object]:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}

    @property
    def chars_per_token(self) -> float:
        return 1.5

    @property
    def token_threshold(self) -> int | None:
        return None
