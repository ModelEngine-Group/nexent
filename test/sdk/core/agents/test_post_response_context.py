# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Usage calibration and response-boundary maintenance policy regressions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from smolagents.memory import TaskStep, ActionStep
from smolagents.monitoring import Timing
from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.context.usage import ContextUsageBaseline


def runtime(window=2000):
    config = ContextManagerConfig(context_window_tokens=window, effective_input_limit_tokens=window,
        compaction_trigger_threshold_tokens=int(window * .8), compaction_target_tokens=int(window * .6),
        chars_per_token=1, policy_layers={"platform": {"processing_mode": "adaptive_compact"}})
    return ManagedContextRuntime(ContextManager(config))


def test_ac009_usage_calibrates_delta_instead_of_summing_billing_totals():
    baseline = ContextUsageBaseline()
    baseline.capture(500, "model-a")
    baseline.accept(700)
    assert baseline.estimate(650, "model-a") == 850
    baseline.capture(650, "model-a")
    baseline.accept(850)
    assert baseline.estimate(700, "model-a") == 900
    assert baseline.estimate(700, "model-b") == 700


@pytest.mark.parametrize("usage", [None, -1, True, "100"])
def test_ac010_missing_or_invalid_usage_uses_local_estimate(usage):
    baseline = ContextUsageBaseline()
    baseline.capture(100, "model")
    baseline.accept(usage)
    assert baseline.estimate(200, "model") == 200


def test_ac010_maintenance_invalidates_previous_raw_history_anchor():
    baseline = ContextUsageBaseline()
    baseline.capture(100, "model")
    baseline.accept(200)
    baseline.invalidate()
    assert baseline.estimate(30, "model") == 30


def test_ac008_normal_preparation_never_calls_compaction_even_above_soft_threshold(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 1650)])
    model = SimpleNamespace(model_id="controlled")
    compact = Mock(side_effect=AssertionError("normal prepare must not compact"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    compact.assert_not_called()


def test_ac008_usage_drives_maintenance_only_after_completed_step(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 500)])
    model = SimpleNamespace(model_id="controlled")
    compact = Mock(side_effect=lambda items, *args, **kwargs: items)
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    compact.assert_not_called()
    memory.steps.append(ActionStep(step_number=1, model_output="answer", timing=Timing(start_time=0)))
    response = SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1800, output_tokens=3000))
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
    assert compact.call_count == 1
    assert managed.usage_baseline.actual_input_tokens == 1800
    assert managed.last_maintenance_evidence is not None
    assert managed.context_manager.config.effective_input_limit_tokens == 2000


def test_ac011_failed_maintenance_keeps_history_and_configuration(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 500)])
    model = SimpleNamespace(model_id="controlled")
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    original_steps = list(memory.steps)
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", Mock(side_effect=RuntimeError("summary failed")))
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1900)))
    assert memory.steps == original_steps
    assert managed.context_manager._history_candidate is None
    assert managed.context_manager._representation_overrides == {}
    assert managed.context_manager.config.effective_input_limit_tokens == 2000
    assert managed.context_manager.config.compaction_target_tokens == 1200


def test_ac012_oversized_new_input_is_rejected_without_compaction(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 2100)])
    compact = Mock(side_effect=AssertionError("hard check must not compact"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    with pytest.raises(ValueError, match="combined context window"):
        managed.prepare_step(model=SimpleNamespace(model_id="controlled"), memory=memory, current_run_start_idx=0)
    compact.assert_not_called()


def test_ac011_cancelled_response_cannot_start_maintenance(monkeypatch):
    from threading import Event
    managed = runtime()
    model = SimpleNamespace(model_id="controlled", stop_event=Event())
    memory = SimpleNamespace(steps=[TaskStep(task="task")])
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    model.stop_event.set()
    maintain = Mock(side_effect=AssertionError("cancelled run must not maintain"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", maintain)
    assert managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1900))) is None
    maintain.assert_not_called()
    assert managed.usage_baseline.actual_input_tokens is None


def test_ac009_duplicate_completion_cannot_replace_usage_or_repeat_maintenance(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 500)])
    model = SimpleNamespace(model_id="controlled")
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    compact = Mock(side_effect=lambda items, *args, **kwargs: items)
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    first = managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1800)))

    duplicate = managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=9999)))

    assert first.maintenance_phase == "post_response"
    assert duplicate is None
    assert compact.call_count == 1
    assert managed.usage_baseline.actual_input_tokens == 1800
    assert managed.last_maintenance_evidence is first


def test_ac011_post_response_assembly_failure_preserves_source_and_policy(monkeypatch, caplog):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 500)])
    model = SimpleNamespace(model_id="controlled")
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    original_steps = list(memory.steps)
    sink = Mock()
    managed.context_manager.config.history_summary_sink = sink
    monkeypatch.setattr(managed.context_manager, "assemble_context_items",
        Mock(side_effect=RuntimeError("assembly unavailable")))

    result = managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1900)))

    assert result is None
    assert memory.steps == original_steps
    assert managed.context_manager._history_candidate is None
    assert managed.context_manager._representation_overrides == {}
    assert managed.context_manager.config.effective_input_limit_tokens == 2000
    assert managed.context_manager.config.compaction_target_tokens == 1200
    assert managed.context_manager.config.history_summary_sink is sink
    assert "event=context_post_response_assembly_failed" in caplog.text
    sink.assert_not_called()


def test_ac011_cancellation_after_staging_rolls_back_without_persistence(monkeypatch):
    from threading import Event

    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 500)])
    model = SimpleNamespace(model_id="controlled", stop_event=Event())
    before = managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    manager = managed.context_manager
    old_candidate, old_event = object(), {"previous": True}
    manager._history_candidate = old_candidate
    manager._representation_overrides = {"retained": "original"}
    manager._pending_history_summary_event = old_event
    original_steps = list(memory.steps)
    sink = Mock()
    manager.config.history_summary_sink = sink

    def assemble(**kwargs):
        if kwargs["maintenance"]:
            assert manager.config.history_summary_sink is None
            manager._history_candidate = object()
            manager._representation_overrides = {"candidate": "uncommitted"}
            manager._pending_history_summary_event = {"candidate": True}
            model.stop_event.set()
        return before

    monkeypatch.setattr(manager, "assemble_context_items", assemble)
    result = managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=1900)))

    assert result.maintenance_phase != "post_response"
    assert manager._history_candidate is old_candidate
    assert manager._representation_overrides == {"retained": "original"}
    assert manager._pending_history_summary_event is old_event
    assert manager.config.effective_input_limit_tokens == 2000
    assert manager.config.compaction_target_tokens == 1200
    assert manager.config.history_summary_sink is sink
    assert memory.steps == original_steps
    assert managed.last_maintenance_evidence is None
    sink.assert_not_called()


def test_ac009_one_request_usage_can_only_be_accepted_once():
    baseline = ContextUsageBaseline()
    baseline.capture(100, "model")
    assert baseline.accept(120) is True
    assert baseline.accept(9000) is False
    assert baseline.actual_input_tokens == 120


def test_ac010_estimated_legacy_token_usage_is_not_a_provider_anchor():
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="short")])
    model = SimpleNamespace(model_id="controlled")
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(provider_input_tokens=None,
            token_usage=SimpleNamespace(input_tokens=1900)))
    assert managed.usage_baseline.actual_input_tokens is None
    assert managed.usage_baseline.source == "estimated"
    assert managed.last_maintenance_evidence is None


@pytest.mark.parametrize('overlay_kind', ['request_system_messages', 'request_tail_messages'])
def test_ac008_post_response_uses_the_same_request_overlay_basis(monkeypatch, overlay_kind):
    managed = runtime(window=10000)
    memory = SimpleNamespace(steps=[TaskStep(task='x' * 500)])
    model = SimpleNamespace(model_id='controlled')
    compact = Mock(side_effect=lambda items, *args, **kwargs: items)
    monkeypatch.setattr(managed.context_manager, '_compact_to_compaction_target', compact)
    overlay = [{'role': 'system' if overlay_kind=='request_system_messages' else 'user',
                'content': [{'type': 'text', 'text': 'overlay ' * 375}]}]
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0,
                         **{overlay_kind: overlay})
    compact.assert_not_called()
    memory.steps.append(ActionStep(step_number=1, model_output='accepted', observations='R' * 2000,
                                   timing=Timing(start_time=0)))
    response = SimpleNamespace(token_usage=SimpleNamespace(input_tokens=7000, output_tokens=20))
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
    assert compact.call_count == 1


@pytest.mark.parametrize('overlay_kind', ['request_system_messages', 'request_tail_messages'])
def test_ac008_explicitly_cleared_overlays_are_removed_from_next_input(monkeypatch, overlay_kind):
    managed = runtime(window=10000)
    memory = SimpleNamespace(steps=[TaskStep(task='x' * 500)])
    model = SimpleNamespace(model_id='controlled')
    compact = Mock(side_effect=lambda items, *args, **kwargs: items)
    monkeypatch.setattr(managed.context_manager, '_compact_to_compaction_target', compact)
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0,
        **{overlay_kind: [{'role': 'user', 'content': [{'type': 'text', 'text': 'overlay ' * 375}]}]})
    memory.steps.append(ActionStep(step_number=1, model_output='accepted', observations='R' * 2000,
                                   timing=Timing(start_time=0)))
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=SimpleNamespace(input_tokens=7000)),
        request_system_messages=(), request_tail_messages=())
    compact.assert_not_called()


def test_ac008_core_passes_fresh_framing_after_clearing_protocol_repairs(monkeypatch):
    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
    from nexent.core.utils.observer import MessageObserver
    from smolagents.models import ChatMessage, Model, TokenUsage

    class FinalModel(Model):
        def generate(self, messages, **kwargs):
            return ChatMessage(role='assistant', content='<final_answer>done</final_answer>',
                token_usage=TokenUsage(input_tokens=1200, output_tokens=10))

    managed = runtime(window=100000)
    complete = Mock(wraps=managed.complete_step)
    monkeypatch.setattr(managed, 'complete_step', complete)
    agent = CoreAgent(observer=MessageObserver(lang='en'), model=FinalModel(model_id='controlled'),
        tools=[], context_runtime=managed, max_steps=1, enable_protocol_repair_retry=True)
    original = agent._context_request_overlays
    frames = []

    def framing():
        if not frames:
            agent._protocol_repair_messages = [ChatMessage(role='user', content='obsolete repair fixture')]
        result = original()
        frames.append(result)
        return result

    monkeypatch.setattr(agent, '_context_request_overlays', framing)
    assert str(agent.run('Return done.')) == 'done'
    complete.assert_called_once()
    assert 'obsolete repair fixture' in str(frames[0][1])
    assert complete.call_args.kwargs['request_system_messages']
    assert 'obsolete repair fixture' not in str(complete.call_args.kwargs['request_tail_messages'])
