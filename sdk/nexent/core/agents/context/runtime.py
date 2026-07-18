"""Managed context path thin adapter.

All context policy and final payload assembly belongs to ContextManager.  This
runtime only adapts CoreAgent lifecycle calls to the ContextManager API.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Mapping

from smolagents.memory import AgentMemory
from smolagents.models import ChatMessage, Model

from ...context_runtime.contracts import ContextEvidence, FinalContext, ModelTool
from .evidence import ContextEvidenceCollector
from .manager import ContextManager
from .models import ContextItem, ContextItemInput
from .run_context import ManagedRunContext


ContextItemCandidate = ContextItemInput | ContextItem


class ManagedContextRuntime:
    """Adapter for the ContextManager-owned managed path."""

    def __init__(
        self,
        context_manager: ContextManager,
        items: Sequence[ContextItemCandidate] | None = None,
    ) -> None:
        self.context_manager = context_manager
        self.items = list(items or ())
        self._run_context: ManagedRunContext | None = None
        self._evidence = ContextEvidenceCollector()

    def replace_items(self, items: Sequence[ContextItemCandidate] | None) -> None:
        """Replace this runtime's run-local fine-grained item snapshot."""
        self.items = list(items or ())
        self._run_context = None

    def prepare_run(self, *, memory: AgentMemory, fallback_system_prompt: str) -> None:
        self._evidence.reset()
        self._run_context = self.context_manager.prepare_run_context(
            memory=memory,
            fallback_system_prompt=fallback_system_prompt,
            items=self.items,
        )

    def _ensure_run_context(self, memory: AgentMemory) -> ManagedRunContext:
        if self._run_context is None:
            self._run_context = self.context_manager.prepare_run_context(
                memory=memory,
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
    ) -> FinalContext:
        final_context = self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="step",
            run_context=self._ensure_run_context(memory),
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
        final_context = self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="final_answer",
            task=task,
            final_answer_templates=final_answer_templates,
            run_context=self._ensure_run_context(memory),
        )
        self._evidence.record_call(final_context.evidence)
        return final_context

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ChatMessage | dict[str, object]]:
        """Return display-only memory messages without compression side effects."""
        return self.context_manager.render_memory_messages(memory)

    def compression_stats(self) -> dict[str, object]:
        return self.context_manager.get_step_compression_stats()

    def finalize_evidence(self, *, status: str) -> ContextEvidence:
        return self._evidence.finalize(status=status)

    @property
    def chars_per_token(self) -> float:
        return self.context_manager.config.chars_per_token

    @property
    def token_threshold(self) -> int | None:
        return self.context_manager.config.token_threshold
