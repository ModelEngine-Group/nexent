"""Managed context path thin adapter.

All context policy and final payload assembly belongs to ContextManager.  This
runtime only adapts CoreAgent lifecycle calls to the ContextManager API.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..contracts import FinalContext
from nexent.monitor import get_monitoring_manager, OPENINFERENCE_SPAN_KIND_CHAIN


class ManagedContextRuntime:
    """Adapter for the ContextManager-owned managed path."""

    def __init__(self, context_manager: Any, components: Sequence[Any] | None = None, conversation_id: int | None = None):
        self.context_manager = context_manager
        self.components = list(components or ())
        self.conversation_id = conversation_id
        self._run_context = None

    def replace_components(self, components: Sequence[Any] | None) -> None:
        """Replace this runtime's run-local component snapshot."""
        self.components = list(components or ())
        self._run_context = None

    def prepare_run(self, *, memory: Any, fallback_system_prompt: str) -> None:
        self._run_context = self.context_manager.prepare_run_context(
            memory=memory,
            fallback_system_prompt=fallback_system_prompt,
            components=self.components,
        )

    def _ensure_run_context(self, memory: Any) -> Any:
        if self._run_context is None:
            self._run_context = self.context_manager.prepare_run_context(
                memory=memory,
                fallback_system_prompt="",
                components=self.components,
            )
        return self._run_context

    def prepare_step(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.prepare_step",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.current_run_start_idx": current_run_start_idx,
                "context.conversation_id": self.conversation_id,
            },
        ):
            return self.context_manager.assemble_final_context(
                model=model,
                memory=memory,
                current_run_start_idx=current_run_start_idx,
                tools=tools,
                purpose="step",
                run_context=self._ensure_run_context(memory),
                conversation_id=self.conversation_id,
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
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.prepare_final_answer",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.current_run_start_idx": current_run_start_idx,
                "context.conversation_id": self.conversation_id,
                "context.task": task,
            },
        ):
            return self.context_manager.assemble_final_context(
                model=model,
                memory=memory,
                current_run_start_idx=current_run_start_idx,
                tools=tools,
                purpose="final_answer",
                task=task,
                final_answer_templates=final_answer_templates,
                run_context=self._ensure_run_context(memory),
                conversation_id=self.conversation_id,
            )

    def render_summary_messages(self, *, memory: Any) -> list[Any]:
        """Return display-only memory messages without compression side effects."""
        return self.context_manager._messages_from_memory(memory)

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
