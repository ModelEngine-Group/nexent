"""Neutral contracts shared by independent legacy and managed context paths."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class ContextEvidence:
    selected_component_types: tuple[str, ...] = ()
    stable_message_count: int = 0
    dynamic_message_count: int = 0
    compression_records: tuple[Any, ...] = ()
    stable_prefix_fingerprint: str | None = None
    prefix_change_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FinalContext:
    """The only context payload permitted to enter a model call."""

    messages: list[Any]
    tools: list[Any] = field(default_factory=list)
    evidence: ContextEvidence = field(default_factory=ContextEvidence)


class ContextRuntime(Protocol):
    """Runtime protocol; implementations must not depend on one another."""

    context_manager: Any

    def prepare_run(self, *, memory: Any, fallback_system_prompt: str) -> None:
        """Initialize the run's system state before a TaskStep is appended."""

    def prepare_step(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        """Return all model messages for the current step."""

    def prepare_final_answer(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        task: str,
        final_answer_templates: dict,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        """Return all model messages for final-answer generation."""

    def truncate_observation(self, memory_step: Any) -> None:
        """Apply path-specific observation controls without exposing mode checks."""

    def compression_stats(self) -> dict:
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

    def prepare_run(self, *, memory: Any, fallback_system_prompt: str) -> None:
        raise RuntimeError("CoreAgent requires a context runtime from the agent factory")

    def prepare_step(self, **kwargs: Any) -> FinalContext:
        raise RuntimeError("CoreAgent requires a context runtime from the agent factory")

    def prepare_final_answer(self, **kwargs: Any) -> FinalContext:
        raise RuntimeError("CoreAgent requires a context runtime from the agent factory")

    def truncate_observation(self, memory_step: Any) -> None:
        raise RuntimeError("CoreAgent requires a context runtime from the agent factory")

    def compression_stats(self) -> dict:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}

    @property
    def chars_per_token(self) -> float:
        return 1.5

    @property
    def token_threshold(self) -> int | None:
        return None
