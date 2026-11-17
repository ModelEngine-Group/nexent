# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""First output timing uses semantic deltas and keeps unknown distinct from zero."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sdk.nexent.monitor import monitoring as mod


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(mod.time, 'perf_counter', lambda: clock.value)
    return clock


def chunk(**delta):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(**delta))], usage=None)


def tracker():
    return mod.LLMTokenTracker(Mock(is_enabled=True), 'model', Mock())


def test_empty_token_does_not_start_clock_or_increment_count(clock):
    observed = tracker()
    observed.record_token('')
    assert observed.first_token_time is None
    assert observed.token_count == 0
    observed.manager.record_llm_metrics.assert_not_called()


@pytest.mark.parametrize('basis', ['content', 'reasoning', 'tool_delta'])
def test_first_output_sets_span_immediately_and_once(clock, basis):
    observed = tracker()
    clock.value += 0.25
    observed.record_first_token(basis=basis)
    clock.value += 0.5
    observed.record_first_token(basis='content')
    observed.manager.record_llm_metrics.assert_called_once_with('ttft', 0.25, {'llm.model_name': 'model'})
    attrs = observed.span.set_attributes.call_args.args[0]
    assert attrs['llm.time_to_first_token'] == 0.25
    assert attrs['llm.ttft_ms'] == 250
    assert attrs['llm.ttft_basis'] == basis
    observed.span.add_event.assert_called_once()
    assert observed.span.add_event.call_args.args[1]['llm.time_to_first_token'] == 0.25


@pytest.mark.parametrize('elapsed', [0.0, 0.125])
def test_zero_and_wall_clock_jumps_preserve_monotonic_value(clock, monkeypatch, elapsed):
    observed = tracker()
    monkeypatch.setattr(mod.time, 'time', lambda: -10000.0)
    clock.value += elapsed
    observed.record_first_token()
    assert observed.span.set_attributes.call_args.args[0]['llm.ttft_ms'] == elapsed * 1000
    assert mod._extract_tracker_metrics(observed)[1] == int(elapsed * 1000)


@pytest.mark.parametrize('elapsed', [-1.0, float('nan'), float('inf')])
def test_invalid_elapsed_is_unknown(clock, elapsed):
    observed = tracker()
    clock.value += elapsed
    observed.record_first_token()
    assert observed.first_token_time is None
    observed.manager.record_llm_metrics.assert_not_called()
    assert mod._extract_tracker_metrics(observed)[1] is None


def test_completion_without_output_keeps_ttft_unknown(clock):
    observed = tracker()
    clock.value += 1
    observed.record_completion(10, 5)
    assert 'llm.time_to_first_token' not in observed.span.set_attributes.call_args.args[0]
    assert mod._extract_tracker_metrics(observed)[1] is None


@pytest.mark.parametrize('delta,basis', [
    ({'content': 'answer'}, 'content'),
    ({'content': ' '}, 'content'),
    ({'reasoning_content': '思考'}, 'reasoning'),
    ({'reasoning': 'thought'}, 'reasoning'),
    ({'tool_calls': [SimpleNamespace(function=SimpleNamespace(arguments='{'))]}, 'tool_delta'),
])
def test_client_ignores_empty_chunks_and_times_first_semantic_delta(clock, monkeypatch, delta, basis):
    enqueue = Mock()
    monkeypatch.setattr(mod, '_enqueue_client_monitoring_record', enqueue)
    empty = [chunk(role='assistant'), chunk(content='', reasoning_content=''),
             SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3)),
             chunk(tool_calls=[SimpleNamespace(id='call', function=SimpleNamespace(name='f', arguments=''))])]

    def stream():
        for item in empty:
            clock.value += 0.125
            yield item
        clock.value += 0.25
        yield chunk(**delta)
        clock.value += 0.25
        yield chunk(content='later')

    original = Mock()
    original.create.return_value = stream()
    wrapper = mod._MonitoredChatCompletions(original, 'model', 'llm')
    assert len(list(wrapper.create(stream=True))) == 6
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs['ttft_ms'] == 750
    assert enqueue.call_args.kwargs['input_tokens'] == 2
    assert enqueue.call_args.kwargs['output_tokens'] == 3


@pytest.mark.parametrize('fail_after_output', [False, True])
def test_client_error_keeps_only_observed_ttft(clock, monkeypatch, fail_after_output):
    enqueue = Mock()
    monkeypatch.setattr(mod, '_enqueue_client_monitoring_record', enqueue)

    def stream():
        clock.value += 0.5
        yield chunk(content='partial' if fail_after_output else '')
        raise RuntimeError('controlled')

    original = Mock()
    original.create.return_value = stream()
    wrapped = mod._MonitoredChatCompletions(original, 'model', 'llm').create(stream=True)
    with pytest.raises(RuntimeError, match='controlled'):
        list(wrapped)
    wrapped.close()
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs['ttft_ms'] == (500 if fail_after_output else None)


def test_non_streaming_ttft_is_unknown(clock, monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(mod, '_enqueue_client_monitoring_record', enqueue)
    original = Mock()
    original.create.return_value = SimpleNamespace(usage=None)
    mod._MonitoredChatCompletions(original, 'model', 'llm').create(stream=False)
    assert enqueue.call_args.kwargs['ttft_ms'] is None


@pytest.mark.parametrize('raw,expected', [
    ({'choices': []}, None),
    ({'choices': [{'delta': {'role': 'assistant', 'content': ''}}]}, None),
    ({'choices': [{'delta': {'tool_calls': [{'id': 'a', 'function': {'name': 'f'}}]}}]}, None),
    ({'choices': [{'delta': {'function_call': {'arguments': '{'}}}]}, 'tool_delta'),
    ({'choices': [{'delta': {}}, {'delta': {'reasoning_content': '思考'}}]}, 'reasoning'),
    ({'choices': [{'delta': {'reasoning': '', 'reasoning_content': 'thought'}}]}, 'reasoning'),
    ({'choices': [{'delta': {'content': 3, 'reasoning_content': {}}}]}, None),
])
def test_semantic_chunk_variants(raw, expected):
    from sdk.nexent.monitor.first_token import stream_token_basis

    assert stream_token_basis(raw) == expected


def test_disabled_monitoring_does_not_publish(clock):
    observed = tracker()
    observed.manager.is_enabled = False
    observed.record_first_token()
    observed.record_token('hello')
    observed.record_completion(1, 1)
    assert observed.first_token_time is None
    observed.span.set_attributes.assert_not_called()
    observed.manager.record_llm_metrics.assert_not_called()


def test_client_timing_includes_create_wait(clock, monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(mod, '_enqueue_client_monitoring_record', enqueue)

    def create(**kwargs):
        clock.value += 0.5
        return iter([chunk(content='answer')])

    original = SimpleNamespace(create=create)
    list(mod._MonitoredChatCompletions(original, 'model', 'llm').create(stream=True))
    assert enqueue.call_args.kwargs['ttft_ms'] == 500


@pytest.mark.parametrize('value,duration,expected', [
    (0, 0, 0), (0.5, 1, 0.5), (1.1, 1, None), (True, 1, None),
    (float('nan'), 1, None), (0.5, float('inf'), None), (None, 1, None),
])
def test_ttft_validity_range(value, duration, expected):
    from sdk.nexent.monitor.first_token import valid_ttft

    assert valid_ttft(value, duration) == expected


def test_buffer_keeps_unknown_and_observed_values(clock, monkeypatch):
    buffer = Mock(is_enabled=True)
    monkeypatch.setattr(mod, 'get_monitoring_buffer', lambda: buffer)
    observed = tracker()
    observed._context_snapshot = {'tenant_id': 'tenant'}
    mod._enqueue_monitoring_record(observed, 'model', 'completion', {})
    assert buffer.add_record.call_args.args[0]['ttft_ms'] is None
    clock.value += 0.125
    observed.record_first_token(basis='reasoning')
    mod._enqueue_monitoring_record(observed, 'model', 'completion', {})
    assert buffer.add_record.call_args.args[0]['ttft_ms'] == 125
