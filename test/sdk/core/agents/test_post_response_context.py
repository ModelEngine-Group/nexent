# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Usage calibration and response-boundary maintenance policy regressions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.memory import TaskStep

from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.context.usage import ContextUsageBaseline
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime


def runtime(window=2000, *, message_format="codeagent"):
    config = ContextManagerConfig(context_window_tokens=window, effective_input_limit_tokens=window,
        compaction_trigger_threshold_tokens=int(window * .8), compaction_target_tokens=int(window * .6),
        chars_per_token=1, policy_layers={"platform": {"processing_mode": "adaptive_compact"}})
    return ManagedContextRuntime(ContextManager(config, message_format=message_format))


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


def test_ac012_oversized_new_input_is_prepared_without_compaction(monkeypatch):
    managed = runtime()
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 2100)])
    compact = Mock(side_effect=AssertionError("hard check must not compact"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    context = managed.prepare_step(model=SimpleNamespace(model_id="controlled"), memory=memory, current_run_start_idx=0)
    assert "x" * 2100 in str(context.messages)
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
        response=SimpleNamespace(token_usage=SimpleNamespace(origin="provider", input_tokens=1900))) is None
    maintain.assert_not_called()
    assert managed.usage_baseline.actual_input_tokens is None


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
            token_usage=SimpleNamespace(origin="provider", input_tokens=1900)))
    assert managed.usage_baseline.actual_input_tokens is None
    assert managed.usage_baseline.source == "estimated"
    assert managed.last_maintenance_evidence is None


def test_ac008_core_passes_fresh_framing_after_clearing_protocol_repairs(monkeypatch):
    from smolagents.models import ChatMessage, Model, TokenUsage

    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
    from nexent.core.utils.observer import MessageObserver

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


@pytest.mark.parametrize("max_steps", [0, 1], ids=["final-answer", "action"])
def test_codeagent_over_window_input_reaches_model_without_context_rebuild(monkeypatch, max_steps):
    from smolagents.models import ChatMessage, Model, TokenUsage

    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
    from nexent.core.utils.observer import MessageObserver

    sent = []
    class ControlledModel(Model):
        def generate(self, messages, **kwargs):
            assert "context_rebuild" not in kwargs
            sent.append(messages)
            response = ChatMessage(role="assistant", content="<final_answer>done</final_answer>",
                                   token_usage=TokenUsage(input_tokens=128, output_tokens=3))
            response.provider_input_tokens = 128
            return response
    managed = runtime(window=1000)
    compact = Mock(side_effect=AssertionError("low provider usage must not compact"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    agent = CoreAgent(observer=MessageObserver(lang="en"), model=ControlledModel(model_id="controlled"),
                      tools=[], context_runtime=managed, max_steps=1)
    query = "OVER_WINDOW " + "x" * 3000
    agent.memory.steps.append(TaskStep(task=query))
    assert list(agent._run_stream(query, max_steps=max_steps))[-1].output == "done"
    assert len(sent) == 1 and query in str(sent[0])
    assert managed.usage_baseline.pending_estimate > 1000
    assert managed.usage_baseline.actual_input_tokens is None
    compact.assert_not_called()


@pytest.mark.parametrize("origin", [None, "unknown"])
def test_custom_model_unproven_usage_cannot_trigger_maintenance(monkeypatch, origin):
    managed = runtime()
    model = SimpleNamespace(model_id="controlled")
    memory = SimpleNamespace(steps=[TaskStep(task="x" * 10000)])
    compact = Mock(side_effect=AssertionError("unknown usage must not compact"))
    monkeypatch.setattr(managed.context_manager, "_compact_to_compaction_target", compact)
    managed.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    usage = SimpleNamespace(input_tokens=10000)
    if origin is not None:
        usage.origin = origin
    managed.complete_step(model=model, memory=memory, current_run_start_idx=0,
        response=SimpleNamespace(token_usage=usage))
    compact.assert_not_called()
