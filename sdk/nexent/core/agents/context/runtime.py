# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Managed context path thin adapter.

ContextManager owns payload assembly and compression. This runtime binds
accepted-response usage and maintenance to safe CoreAgent step boundaries.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Mapping

from smolagents.memory import AgentMemory
from smolagents.models import ChatMessage, Model

from ...context_runtime.contracts import ContextEvidence, FinalContext, ModelTool
from .evidence import ContextEvidenceCollector
from .manager import ContextManager
from .models import ContextItem, ContextItemInput
from .run_context import ManagedRunContext
from .usage import ContextUsageBaseline

logger = logging.getLogger("agent_context.runtime")


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
        self.usage_baseline = ContextUsageBaseline()
        self.last_maintenance_evidence = None

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
        request_system_messages: Sequence[ChatMessage | dict[str, object]] = (),
        request_tail_messages: Sequence[ChatMessage | dict[str, object]] = (),
    ) -> FinalContext:
        final_context = self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="step",
            run_context=self._ensure_run_context(memory),
            request_system_messages=request_system_messages,
            request_tail_messages=request_tail_messages,
        )
        if not final_context.evidence.history_compression_triggered:
            self.check_input_capacity(final_context.messages, final_context.tools, model)
        self.capture_request(final_context.messages, final_context.tools, model)
        final_context = self._with_usage_evidence(final_context, model)
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
        final_context = self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="step",
            run_context=self._ensure_run_context(memory),
            force_compaction=True,
            request_system_messages=request_system_messages,
            request_tail_messages=request_tail_messages,
        )
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
        self.check_input_capacity(final_context.messages, final_context.tools, model)
        self.capture_request(final_context.messages, final_context.tools, model)
        final_context = self._with_usage_evidence(final_context, model)
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
        final_context = self.context_manager.assemble_final_context(
            model=model,
            memory=memory,
            current_run_start_idx=current_run_start_idx,
            tools=tools,
            purpose="final_answer",
            task=task,
            final_answer_templates=final_answer_templates,
            run_context=self._ensure_run_context(memory),
            force_compaction=True,
        )
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
            self.context_manager._canonical_tools(tools or ()),
        )

    def capture_request(self, messages, tools, model):
        """Capture the actual main invocation after overlays and guardrails."""
        self.usage_baseline.capture(self._estimate(messages, tools), self._model_key(model))

    def check_input_capacity(self, messages, tools, model):
        local = self._estimate(messages, tools)
        estimate = self.usage_baseline.estimate(local, self._model_key(model))
        limit = self.effective_input_limit_tokens or self.context_window_tokens
        if limit and estimate >= limit:
            raise ValueError("Context input exceeds the combined context window; reduce the new input")
        return estimate

    def complete_step(self, *, model, memory, current_run_start_idx, response, tools=None):
        """Maintain only accepted, completed steps with all tool results present."""
        stop_event = getattr(model, "stop_event", None)
        if response is None or (stop_event is not None and stop_event.is_set() is True):
            return None
        usage = getattr(response, "token_usage", None)
        provider_input = getattr(response, "provider_input_tokens", getattr(usage, "input_tokens", None))
        if not self.usage_baseline.accept(provider_input):
            return None
        before = self.context_manager.assemble_final_context(
            model=model, memory=memory, current_run_start_idx=current_run_start_idx,
            tools=tools, run_context=self._ensure_run_context(memory),
        )
        estimated = self.usage_baseline.estimate(
            self._estimate(before.messages, before.tools), self._model_key(model),
        )
        threshold = self.context_manager._compaction_trigger_threshold_tokens()
        if estimated < threshold or self.context_manager.processing_mode != "adaptive_compact":
            return before.evidence
        # Bound attempts per accepted response rather than per entire Agent run.
        self.context_manager._run_compaction_attempts = 0
        config = self.context_manager.config
        old_limit, old_target = config.effective_input_limit_tokens, config.compaction_target_tokens
        old_candidate = self.context_manager._history_candidate
        old_overrides = dict(self.context_manager._representation_overrides)
        old_event = self.context_manager._pending_history_summary_event
        old_sink = config.history_summary_sink
        config.history_summary_sink = None
        correction = estimated - self._estimate(before.messages, before.tools)
        config.effective_input_limit_tokens = max(1, old_limit - correction)
        config.compaction_target_tokens = max(1, self.context_manager._compaction_target_tokens() - correction)
        try:
            final = self.context_manager.assemble_final_context(
                model=model, memory=memory, current_run_start_idx=current_run_start_idx,
                tools=tools, run_context=self._ensure_run_context(memory), force_compaction=True,
                maintenance=True,
            )
        except Exception:
            self.context_manager._history_candidate = old_candidate
            self.context_manager._representation_overrides = old_overrides
            self.context_manager._pending_history_summary_event = old_event
            logger.warning("event=context_post_response_maintenance_failed", exc_info=True)
            return before.evidence
        finally:
            config.effective_input_limit_tokens, config.compaction_target_tokens = old_limit, old_target
            config.history_summary_sink = old_sink
        if stop_event is not None and stop_event.is_set() is True:
            self.context_manager._history_candidate = old_candidate
            self.context_manager._representation_overrides = old_overrides
            self.context_manager._pending_history_summary_event = old_event
            return before.evidence
        if self.context_manager._history_candidate is not old_candidate:
            status = self.context_manager._persist_candidate(self.context_manager._history_candidate)
            if self.context_manager._pending_history_summary_event is not None:
                self.context_manager._pending_history_summary_event["persist_status"] = status
        final = self._with_usage_evidence(final, model, "post_response")
        final = replace(final, evidence=replace(final.evidence,
            effective_input_limit_tokens=old_limit,
            compaction_target_tokens=old_target,
            exceeds_effective_input_limit=final.evidence.calibrated_input_estimate >= old_limit))
        self.last_maintenance_evidence = final.evidence
        self._evidence.record_call(final.evidence)
        logger.info("event=context_post_response_maintenance source=%s actual_input=%s estimated_before=%s "
                    "estimated_after=%s trigger=%s target=%s", self.usage_baseline.source,
                    self.usage_baseline.actual_input_tokens, estimated,
                    final.evidence.calibrated_input_estimate, threshold, old_target)
        if final.evidence.final_token_estimate < before.evidence.final_token_estimate:
            self.usage_baseline.invalidate()
        return final.evidence

    def render_summary_messages(self, *, memory: AgentMemory) -> list[ChatMessage | dict[str, object]]:
        """Return display-only memory messages without compression side effects."""
        return self.context_manager.render_memory_messages(memory)

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
