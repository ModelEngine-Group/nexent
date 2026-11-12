# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Low-dependency tests for the ContextManager runtime."""

from __future__ import annotations

import types

import pytest


def _bootstrap():
    from nexent.core.agents.cores.smolagents import context

    return context, {}


def _restore(snapshot):
    """No global module replacements are needed for the canonical bridge."""


class _Memory:
    def __init__(self):
        self.system_prompt = None
        self.steps = []


class _ContextManager:
    class _Config:
        chars_per_token = 1.5
        max_observation_length = 0
        token_threshold = 1024
        context_window_tokens = 4096

    config = _Config()
    effective_input_limit_tokens = 3584
    processing_mode = "adaptive_compact"

    def __init__(self):
        self.calls = []
        self.force_compactions = []
        self._current_item_cache = {}
        self._to_json_value = lambda value: value
        self.build_context_messages = lambda items: []

    def prepare_items_context(self, *, fallback_system_prompt, items=None):
        self.calls.append(("prepare_items_context", fallback_system_prompt, items))
        return types.SimpleNamespace(
            stable_messages=({"role": "system", "content": "managed stable"},),
            dynamic_messages=(),
            selected_item_types=tuple(
                str(getattr(item, "type", "unknown")) for item in items or ()
            ),
            items=tuple(items or ()),
        )

    def assemble_context_items(self, **kwargs):
        self.calls.append(
            ("assemble_context_items", kwargs["purpose"], kwargs.get("tools"))
        )
        self.force_compactions.append(kwargs.get("force_compaction", False))
        from nexent.core.agents.contracts import context as contracts

        return contracts.FinalContext(
            messages=[{"role": "system", "content": kwargs["purpose"]}],
            tools=list(kwargs.get("tools") or ()),
            evidence=contracts.ContextEvidence(stable_message_count=1),
        )

    def get_step_compression_stats(self):
        return {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_hits": 0,
            "cache_types": [],
        }

    def get_all_compression_stats(self):
        return {"calls": 1, "records": ["record"]}

    def get_token_counts(self):
        return {"uncompressed": 1200, "compressed": 900}

    def consume_history_summary_event(self):
        return None

    def render_memory_messages(self, memory):
        return []


def test_managed_runtime_is_thin_context_manager_adapter():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        item = types.SimpleNamespace(type="system_prompt")
        runtime = managed_module.ManagedContextRuntime(manager, items=[item])
        memory = _Memory()

        with pytest.raises(AttributeError):
            runtime.context_manager = _ContextManager()

        runtime.prepare_run(memory=memory, fallback_system_prompt="fallback")
        final = runtime.prepare_step(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[{"name": "z"}],
        )
        final_answer = runtime.prepare_final_answer(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            task="task",
            final_answer_templates={"final_answer": {}},
        )

        assert manager.calls == [
            ("prepare_items_context", "fallback", [item]),
            ("assemble_context_items", "step", [{"name": "z"}]),
            ("assemble_context_items", "final_answer", None),
        ]
        assert final.messages == [{"role": "system", "content": "step"}]
        assert final_answer.messages == [{"role": "system", "content": "final_answer"}]
        evidence = runtime.finalize_evidence(status="completed")
        assert evidence.model_call_count == 2
        assert evidence.loop_status == "completed"
        assert runtime.finalize_evidence(status="error") is evidence
        assert runtime.token_threshold == 1024
        assert runtime.context_window_tokens == 4096
        assert runtime.effective_input_limit_tokens == 3584
        assert runtime.processing_mode == "adaptive_compact"
        assert runtime.token_counts() == {"uncompressed": 1200, "compressed": 900}
        assert runtime.global_compression_stats() == {"calls": 1, "records": ["record"]}
    finally:
        _restore(snapshot)


def test_managed_runtime_replaces_items_without_mutating_context_manager():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        runtime = managed_module.ManagedContextRuntime(manager)
        item = types.SimpleNamespace(type="memory")

        runtime.replace_items([item])
        runtime.prepare_run(memory=_Memory(), fallback_system_prompt="fallback")

        assert manager.calls[0] == ("prepare_items_context", "fallback", [item])
    finally:
        _restore(snapshot)


def test_managed_runtime_uses_item_snapshot_without_explicit_prepare_run():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        item = types.SimpleNamespace(type="knowledge")
        runtime = managed_module.ManagedContextRuntime(manager, items=[item])

        runtime.prepare_step(model=None, memory=_Memory(), current_run_start_idx=0)

        assert manager.calls[0] == ("prepare_items_context", "", [item])
    finally:
        _restore(snapshot)


def test_managed_runtime_forces_compaction_for_both_overflow_recovery_paths():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        runtime = managed_module.ManagedContextRuntime(manager)
        memory = _Memory()

        step = runtime.recover_step(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[{"name": "search"}],
        )
        final_answer = runtime.recover_final_answer(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            task="task",
            final_answer_templates={"final_answer": {}},
        )

        assert manager.force_compactions == [True, True]
        assert step.messages == [{"role": "system", "content": "step"}]
        assert final_answer.messages == [{"role": "system", "content": "final_answer"}]
        assert runtime.finalize_evidence(status="completed").model_call_count == 2
    finally:
        _restore(snapshot)
