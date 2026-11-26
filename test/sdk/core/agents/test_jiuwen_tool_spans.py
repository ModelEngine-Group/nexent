# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""RSR-003: actual calls are safely observed without redefining success."""

import asyncio
import json
from types import MethodType, SimpleNamespace

import pytest
from nexent.monitor.monitoring import MonitoringManager
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_jiuwen_errors import adapter as _adapter

adapter = _adapter


@pytest.fixture
def spans(mocker):
    provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    manager = SimpleNamespace(is_enabled=True, _tracer=provider.get_tracer('jiuwen-test'),
                              _agent_error_count=None, _agent_step_count=None,
                              build_agent_run_attributes=lambda *args, **kwargs: {})
    manager.trace_tool_call = MethodType(MonitoringManager.trace_tool_call, manager)
    mocker.patch('nexent.core.agents.cores.jiuwen.adapter.get_monitoring_manager', return_value=manager, create=True)
    try:
        yield manager, exporter
    finally:
        provider.shutdown()


@pytest.mark.parametrize('result,is_error', [('Order not found', False), ({'success': False, 'error': 'private-result'}, True)])
def test_normal_return_and_structured_error_keep_call_success(adapter, spans, result, is_error):
    manager, exporter = spans
    with manager._tracer.start_as_current_span('agent') as parent:
        parent_id = parent.get_span_context().span_id
        with adapter._observe_tool('local', {'private_key': 'secret-input'}):
            adapter._resource_result(result)
    tools = [span for span in exporter.get_finished_spans() if span.attributes.get('openinference.span.kind') == 'TOOL']
    assert len(tools) == 1
    span = tools[0]
    assert span.parent.span_id == parent_id
    assert span.attributes['agent.tool.success'] is True
    assert span.attributes['nexent.tool.result.is_error'] is is_error
    assert span.attributes['nexent.tool.local_call_id']
    assert not {'input.value', 'output.value', 'tool.parameters'}.intersection(span.attributes)
    assert not {'nexent.local.input.value', 'nexent.local.output.value'}.intersection(span.attributes)
    assert 'secret-input' not in str(span.attributes) and 'private-result' not in str(span.attributes)


@pytest.mark.parametrize('error', [ValueError('secret-error-message'), asyncio.CancelledError()])
def test_actual_exception_is_preserved_and_safely_recorded(adapter, spans, error):
    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True)
    with pytest.raises(type(error)) as caught:
        with adapter._observe_tool('local', {}):
            raise error
    assert caught.value is error
    tools = [s for s in exporter.get_finished_spans() if s.attributes.get('openinference.span.kind') == 'TOOL']
    assert len(tools) == 1
    assert tools[0].attributes['agent.tool.success'] is False
    assert tools[0].attributes['error.type'] == type(error).__name__
    assert tools[0].status.status_code.name == 'ERROR'
    assert json.loads(tools[0].attributes['nexent.local.input.value']) == {}
    assert 'nexent.local.output.value' not in tools[0].attributes
    assert 'secret-error-message' not in str(tools[0].attributes) + str(tools[0].events) + str(tools[0].status.description)
    assert adapter._active_resource.get() is None


@pytest.mark.asyncio
async def test_parallel_async_calls_have_distinct_scope_and_original_parent(adapter, spans):
    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True)
    async def work(query):
        with adapter._observe_tool('local', {'query': query}):
            await asyncio.sleep(0)
            adapter._resource_result(query)
    with manager._tracer.start_as_current_span('parent') as parent:
        await asyncio.gather(work('first'), work('second'))
        parent_id = parent.get_span_context().span_id
    tools = [s for s in exporter.get_finished_spans() if s.attributes.get('openinference.span.kind') == 'TOOL']
    assert len(tools) == 2
    assert len({s.attributes['nexent.tool.local_call_id'] for s in tools}) == 2
    assert all(s.parent.span_id == parent_id and not s.attributes.get('nexent.tool.parent_call_id') for s in tools)
    assert {json.loads(s.attributes['nexent.local.input.value'])['query']: s.attributes['nexent.local.output.value']
            for s in tools} == {'first': 'first', 'second': 'second'}
    assert adapter._active_resource.get() is None


def test_telemetry_failure_does_not_change_tool_result(adapter, mocker):
    mocker.patch('nexent.core.agents.cores.jiuwen.adapter.get_monitoring_manager',
                 side_effect=RuntimeError('telemetry only'), create=True)
    with adapter._observe_tool('local', {}):
        adapter._resource_result('unchanged result')
    assert adapter._active_resource.get() is None


@pytest.mark.asyncio
async def test_managed_worker_inherits_actual_tool_span_and_cleanup(adapter, spans):
    from nexent.core.concurrency import LanePolicy, ThreadManager

    manager, exporter = spans
    threads = ThreadManager('tool-span-test', {
        'model-tool-io': LanePolicy(name='model-tool-io', max_workers=1, max_queue_size=0)})
    threads.start()
    adapter.manager = threads
    observed = []
    def forward():
        observed.append(trace.get_current_span().get_span_context().span_id)
        return 'worker result'
    try:
        with manager._tracer.start_as_current_span('agent') as parent:
            parent_id = parent.get_span_context().span_id
            assert await adapter._business_handler('local', forward)() == 'worker result'
    finally:
        assert not (await threads.shutdown(timeout=3)).stuck_execution_ids
    tools = [s for s in exporter.get_finished_spans() if s.attributes.get('openinference.span.kind') == 'TOOL']
    assert len(tools) == 1 and observed == [tools[0].context.span_id]
    assert tools[0].parent.span_id == parent_id
    assert adapter._active_resource.get() is None


def test_nested_actual_calls_have_unique_ids_and_scoped_results(adapter, spans):
    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True)
    with adapter._observe_tool('local', {}):
        outer_id = adapter._active_resource.get()[0]
        with adapter._observe_tool('local', {}):
            adapter._resource_result({'success': False})
        adapter._resource_result('normal outer result')
    tools = [s for s in exporter.get_finished_spans() if s.attributes.get('openinference.span.kind') == 'TOOL']
    assert len(tools) == 2
    inner, outer = tools
    assert inner.attributes['nexent.tool.parent_call_id'] == outer_id
    assert inner.parent.span_id == outer.context.span_id
    assert inner.attributes['nexent.tool.result.is_error'] is True
    assert outer.attributes['nexent.tool.result.is_error'] is False
    assert json.loads(inner.attributes['nexent.local.output.value']) == {'success': False}
    assert outer.attributes['nexent.local.output.value'] == 'normal outer result'
    assert all(s.attributes['agent.tool.success'] is True for s in tools)


def test_disabled_monitoring_keeps_execution_and_emits_no_span(adapter, spans):
    manager, exporter = spans
    manager.is_enabled = False
    with adapter._observe_tool('local', {}):
        adapter._resource_result('result')
    assert not exporter.get_finished_spans()


def test_close_failure_does_not_fail_business_or_leak_scope(adapter, spans):
    from contextlib import contextmanager
    from unittest.mock import Mock

    manager, _ = spans
    @contextmanager
    def broken(*args, **kwargs):
        yield Mock()
        raise RuntimeError('export failure')
    manager.trace_tool_call = broken
    with adapter._observe_tool('local', {}):
        adapter._resource_result('returned')
    assert adapter._active_resource.get() is None


def test_platform_run_model_request_and_provider_identity_remain_distinct(adapter, spans, mocker):
    from nexent.core.model_service.contracts import ToolCall

    mocker.patch('nexent.core.agents.cores.jiuwen.tool_tracing.get_agent_monitoring_context',
                 return_value=SimpleNamespace(extra_metadata={'agentos_run_id': 'platform-run'}))
    adapter.events.begin_step(SimpleNamespace(request_id='model-request'))
    adapter.events.calls.append(ToolCall(provider_call_id='provider-call', name='local', index=0,
                                        raw_arguments='{}', parsed_arguments={}))
    with adapter._observe_tool('local', {}):
        adapter._resource_result('ok')
    _, exporter = spans
    span = exporter.get_finished_spans()[0]
    assert span.attributes['nexent.agentos.run_id'] == 'platform-run'
    assert span.attributes['nexent.runtime.turn_id'] == adapter.events.turn_id
    assert span.attributes['nexent.model.request_id'] == 'model-request'
    assert span.attributes['nexent.tool.provider_call_id'] == 'provider-call'
    assert span.attributes['nexent.tool.local_call_id'] != 'provider-call'


def test_fingerprints_use_existing_redaction_and_match_actual_observation(adapter, spans):
    import hashlib
    import json

    from nexent.monitor.local_content import local_content_value

    _, exporter = spans
    data = {'query': 'public', 'api_key': 'never-export', 'url': 'https://example.test/file?X-Amz-Signature=private'}
    with adapter._observe_tool('local', data):
        adapter._resource_result('result without another model call')
    span = exporter.get_finished_spans()[0]
    encoded = json.dumps(local_content_value(data), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    assert span.attributes['nexent.tool.input.sha256'] == hashlib.sha256(encoded).hexdigest()
    assert span.attributes['nexent.tool.input.size_bytes'] == len(encoded)
    assert span.attributes['nexent.tool.output.available'] is True
    assert len(span.attributes['nexent.tool.output.sha256']) == 64
    assert 'never-export' not in str(span.attributes) and 'X-Amz-Signature' not in str(span.attributes)
    assert not {'input.value', 'output.value'}.intersection(span.attributes)


def test_result_credentials_are_removed_before_fingerprinting(adapter, spans):
    _, exporter = spans
    for secret in ['first-secret', 'second-secret']:
        with adapter._observe_tool('local', {}):
            adapter._resource_result({'api_key': secret, 'value': 7})
    tools = exporter.get_finished_spans()
    assert len(tools) == 2
    assert tools[0].attributes['nexent.tool.output.sha256'] == tools[1].attributes['nexent.tool.output.sha256']
    assert 'first-secret' not in str([s.attributes for s in tools])


def test_opaque_non_json_payload_has_no_repr_capture(adapter, spans):
    from nexent.core.agents.cores.jiuwen.tool_tracing import tool_execution_trace

    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True)
    class Private:
        def __repr__(self):
            raise AssertionError('Do not inspect arbitrary objects')
    with tool_execution_trace(lambda: manager, 'local', 'agent', {}, tool_input={'value': Private()}):
        pass
    span = exporter.get_finished_spans()[0]
    assert span.attributes['nexent.tool.input.available'] is False
    assert span.attributes['nexent.local.nexent.availability.input'] == 'serialization_failed'
    assert span.attributes['nexent.local.nexent.trajectory.gap'] is True
    assert 'nexent.local.input.value' not in span.attributes
    assert span.attributes['agent.tool.success'] is True


def test_existing_local_capture_identity_and_definition_are_preserved(adapter, spans):
    manager, exporter = spans
    manager._config = SimpleNamespace(provider='local_file', export_traces=True)
    tool = SimpleNamespace(name='local', description='Lookup', inputs={'query': {'type': 'string'}},
                           output_type='string')
    adapter.business_tools['local'] = tool
    with adapter._observe_tool('local', {'query': 'safe'}):
        local_id = adapter._active_resource.get()[0]
        adapter._resource_result('result')
    span = exporter.get_finished_spans()[0]
    assert span.attributes['nexent.local.nexent.call_id'] == local_id
    assert 'Lookup' in span.attributes['nexent.local.tool.definition']
    assert span.attributes['nexent.local.tool.implementation']


@pytest.mark.parametrize('result,expected', [
    (None, 'null'), (False, 'false'), ('', ''), (' 42 ', ' 42 '), ('"text"', '"text"'),
    (' { "v": 5 } ', ' { "v": 5 } '),
])
def test_local_tool_output_preserves_actual_return(adapter, spans, result, expected):
    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True)
    with adapter._observe_tool('local', {}):
        adapter._resource_result(result)
    assert exporter.get_finished_spans()[0].attributes['nexent.local.output.value'] == expected


def test_local_tool_bodies_are_redacted_and_excluded_from_remote_export(adapter, spans):
    from nexent.monitor.span_processor import MonitoringSpanProcessor

    manager, exporter = spans
    manager._config = SimpleNamespace(capture_local_traces=True, provider='otlp')
    arguments = {'count': 0, 'empty': [], 'nested': {'api_key': 'input-secret', 'value': None}}
    result = {'result': '{"success":false,"api_key":"output-secret","message":"business error"}'}
    with adapter._observe_tool('remote', arguments):
        adapter._resource_result(result)
    span = exporter.get_finished_spans()[0]
    assert json.loads(span.attributes['nexent.local.input.value']) == {
        'count': 0, 'empty': [], 'nested': {'value': None},
    }
    captured = json.loads(span.attributes['nexent.local.output.value'])
    assert json.loads(captured['result']) == {'success': False, 'message': 'business error'}
    assert span.attributes['agent.tool.success'] is True
    assert span.attributes['nexent.tool.result.is_error'] is True
    remote = InMemorySpanExporter()
    MonitoringSpanProcessor(SimpleSpanProcessor(remote)).on_end(span)
    public = remote.get_finished_spans()[0]
    assert not any(key.startswith('nexent.local.') for key in public.attributes)
    assert 'nexent.tool.output.sha256' in public.attributes
    assert 'business error' not in str(public.attributes)
    assert all(secret not in str(span.attributes) for secret in ('input-secret', 'output-secret'))
