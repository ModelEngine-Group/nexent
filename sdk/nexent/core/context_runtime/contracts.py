"""Contracts for the single ContextManager-backed runtime path."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from smolagents.memory import AgentMemory
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
    policy_fingerprint: str | None = None
    processing_mode: str = "passthrough"
    soft_budget: int = 0
    hard_budget: int = 0
    raw_token_estimate: int = 0
    final_token_estimate: int = 0
    loaded_summary_unit_id: int | None = None
    loaded_summary_coverage: int | None = None
    new_history_turn_count: int = 0
    history_compression_triggered: bool = False
    new_summary_coverage: int | None = None
    summary_persist_status: str = "not_attempted"
    item_representations: tuple[tuple[str, str], ...] = ()
    current_action_compact_count: int = 0
    representation_cache_hits: int = 0
    representation_cache_misses: int = 0
    compact_exhausted: bool = False
    over_hard_budget: bool = False
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

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        """Return display-only messages without triggering compression."""

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        """Finalize and emit the single evidence record for this agent loop."""

    def compression_stats(self) -> dict[str, object]:
        """Return this step's compression metrics in the common shape."""

    def consume_history_summary_event(self) -> dict[str, object] | None:
        """Return a newly-created history checkpoint once, if present."""

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

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ModelMessage]:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        raise RuntimeError(_UNCONFIGURED_RUNTIME_ERROR)

    def compression_stats(self) -> dict[str, object]:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}

    def consume_history_summary_event(self) -> dict[str, object] | None:
        return None

    @property
    def chars_per_token(self) -> float:
        return 1.5

    @property
    def token_threshold(self) -> int | None:
        return None
