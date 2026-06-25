"""Managed context path thin adapter.

All context policy and final payload assembly belongs to ContextManager.  This
runtime only adapts CoreAgent lifecycle calls to the ContextManager API.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..contracts import FinalContext


class ManagedContextRuntime:
    """Adapter for the ContextManager-owned managed path."""

    def __init__(self, context_manager: Any):
        self.context_manager = context_manager

    def prepare_run(self, *, memory: Any, fallback_system_prompt: str) -> None:
        self.context_manager.prepare_run_context(
            memory=memory,
            fallback_system_prompt=fallback_system_prompt,
        )

    def prepare_step(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        return self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="step",
        )

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
        return self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="final_answer",
            task=task,
            final_answer_templates=final_answer_templates,
        )

    def truncate_observation(self, memory_step: Any) -> None:
        max_observation_length = self.context_manager.config.max_observation_length
        observation = getattr(memory_step, "observations", None)
        if max_observation_length <= 0 or not observation or len(observation) <= max_observation_length:
            return
        half = max_observation_length // 2
        marker = (
            f"\n...[Output truncated to {max_observation_length} characters. "
            "Use search or read tools to find specific results.]\n"
        )
        memory_step.observations = observation[:half] + marker + observation[-half:]

    def compression_stats(self) -> dict:
        return self.context_manager.get_step_compression_stats()

    @property
    def chars_per_token(self) -> float:
        return self.context_manager.config.chars_per_token

    @property
    def token_threshold(self) -> int | None:
        return self.context_manager.config.token_threshold
