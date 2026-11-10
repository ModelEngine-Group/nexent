# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real HTTP/SSE model calls preserve first-output timing through local OTLP."""

import asyncio
import json
import math
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import TrajectoryFileStore
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.http_sender import HttpRequestSender
from nexent.core.model_service.service import (
    ModelService,
    ModelServiceError,
)
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.models.retry import ModelRetryConfig
from nexent.core.utils.observer import MessageObserver
from nexent.monitor.monitoring import MonitoringConfig, MonitoringManager
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id('CHAT-TRAJECTORY-TTFT-D3-001'), pytest.mark.stage('D3')]


@pytest.fixture
def capture(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    store = TrajectoryFileStore(tmp_path, root_id, authorize=lambda _: None)
    identity = SimpleNamespace(tenant_id='tenant', user_id='owner', agent_id=7, conversation_id=123, extra_metadata={})
    processor = LocalTrajectoryProcessor(store, lambda: identity)
    threads = ThreadManager('ttft-fixture', {'background-service': LanePolicy('background-service', 1, 0)})
    threads.start()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    reader = InMemoryMetricReader()
    metrics = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    manager = MonitoringManager()
    previous = dict(manager.__dict__)
    manager._config = MonitoringConfig(
        enable_telemetry=True, trace_sink='local_file', local_span_processor=processor, export_metrics=False,
    )
    manager._tracer = provider.get_tracer('ttft-fixture')
    manager._llm_ttft_duration = metrics.get_meter('ttft-fixture').create_histogram('llm.time_to_first_token')
    processor.start(threads, ManagedThreadSpec('trajectory-writer', 'ttft-test', close_hook=processor.request_stop))
    try:
        yield SimpleNamespace(manager=manager, tracer=manager._tracer, processor=processor, root=tmp_path, reader=reader)
    finally:
        processor.shutdown()
        provider.shutdown()
        metrics.shutdown()
        asyncio.run(threads.shutdown(timeout=3))
        manager.__dict__.clear()
        manager.__dict__.update(previous)
        assert threads.snapshot().active_count == 0


def attrs(span):
    return {item['key']: next(iter(item['value'].values())) for item in span.get('attributes', [])}


def spans(capture):
    assert capture.processor.force_flush(3000)
    return [span for path in capture.root.rglob('*.otlp.jsonl') for line in path.read_text().splitlines()
            for resource in json.loads(line)['resourceSpans'] for scope in resource['scopeSpans']
            for span in scope['spans'] if span['name'] != 'nexent.trajectory.fragment']


@contextmanager
def provider(mode):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            if mode == 'before_error' or (mode == 'sampling_fallback' and len(requests) == 1):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                detail = {'message': 'controlled', 'type': 'invalid_request_error'}
                if mode == 'sampling_fallback':
                    detail.update(message='temperature unsupported', param='temperature')
                self.wfile.write(json.dumps({'error': detail}).encode())
                return
            if not request.get('stream'):
                body = json.dumps({'id': 'complete', 'object': 'chat.completion', 'created': 1, 'model': 'model',
                                   'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'answer'},
                                                'finish_reason': 'stop'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()

            def emit(delta=None, finish=None, usage=None):
                value = {'id': 'stream', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'model',
                         'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
                if usage is not None:
                    value['choices'] = []
                    value['usage'] = usage
                self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                self.wfile.flush()

            emit({'role': 'assistant', 'content': ''})
            emit(usage={'prompt_tokens': 2, 'completion_tokens': 0, 'total_tokens': 2})
            if mode != 'retry_empty':
                emit({'tool_calls': [{'index': 0, 'id': 'call', 'type': 'function',
                                       'function': {'name': 'unused', 'arguments': ''}}]})
            time.sleep(0.025)
            if mode != 'empty':
                first_empty = mode == 'retry_empty' and len(requests) == 1
                delta = {'reasoning_content': '思考'} if mode == 'reasoning' or first_empty else (
                    {'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]} if mode == 'tool_delta'
                    else {'content': 'answer'}
                )
                emit(delta)
                if mode == 'after_error':
                    self.wfile.write(b'data: {"error":{"message":"controlled","type":"server_error"}}\n\n')
                    self.wfile.flush()
                    return
                if not first_empty:
                    emit({'content': 'final'})
            emit(finish='stop' if mode == 'retry_empty' else 'tool_calls')
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name='ttft-provider')
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


async def invoke(capture, base, entry, *, streaming=True, attempts=1, empty_policy='accept'):
    if entry == 'legacy':
        model = OpenAIModel(observer=MessageObserver(), model_id='model', api_key='synthetic', api_base=base,
                            retry_config=ModelRetryConfig(max_attempts=attempts, backoff_base_seconds=0, jitter=False))
        model._monitoring = capture.manager
        try:
            result = model([{'role': 'user', 'content': 'hello'}])
            return result.content
        finally:
            model.client.close()
    service = ModelService(lambda _: HttpRequestSender(lambda _: {}), monitoring=capture.manager,
                           retry_policy=SimpleNamespace(max_attempts=attempts, calculate_backoff=lambda _: 0))
    profile = resolved_profile_for_test(base)
    request = ModelRequest(request_id='ttft-test', outlet_id=None, config_revision=1, stream=streaming,
                           messages=[ModelMessage(semantic_role='user', content_parts=[{'type': 'text', 'text': 'hello'}])])
    if not streaming:
        result = await service.ainvoke(request, profile) if entry == 'async' else service.invoke(request, profile)
    elif entry == 'async':
        async with service.astream(request, profile, empty_response_policy=empty_policy) as events:
            collected = [event async for event in events]
            if collected[-1].type == 'error':
                raise ModelServiceError(collected[-1].error)
            result = collected[-1].message
    else:
        with service.stream(request, profile, empty_response_policy=empty_policy) as events:
            collected = list(events)
            if collected[-1].type == 'error':
                raise ModelServiceError(collected[-1].error)
            result = collected[-1].message
    return ''.join(part.get('text', '') for part in result.content_parts)


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['sync', 'async', 'legacy'])
@pytest.mark.parametrize('mode,basis', [('content', 'content'), ('reasoning', 'reasoning'), ('tool_delta', 'tool_delta')])
async def test_ttft_semantic_output_reaches_file(capture, entry, mode, basis):
    with provider(mode) as (base, requests):
        with capture.tracer.start_as_current_span('agent.run'):
            answer = await invoke(capture, base, entry)
            with capture.tracer.start_as_current_span('unused-tool', attributes={'openinference.span.kind': 'TOOL'}):
                pass
        assert answer.endswith('final') and len(requests) == 1
    saved = spans(capture)
    models = [span for span in saved if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 1
    model = models[0]
    values = attrs(model)
    seconds = values['llm.time_to_first_token']
    assert math.isfinite(seconds) and seconds >= 0.025
    duration_ms = float(values['nexent.duration_ms'])
    assert math.isfinite(duration_ms) and duration_ms >= 0
    assert seconds <= duration_ms / 1000
    assert values['llm.ttft_ms'] == pytest.approx(seconds * 1000)
    assert values['llm.ttft_basis'] == basis
    first = [event for event in model['events'] if event['name'] == 'first_token_received']
    assert len(first) == 1 and attrs(first[0])['llm.time_to_first_token'] == seconds
    assert all('llm.ttft_ms' not in attrs(span) for span in saved if span not in models)
    histogram = capture.reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
    assert histogram.count == 1 and histogram.sum == seconds
    assert model.get('parentSpanId')


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['sync', 'async'])
@pytest.mark.parametrize('mode', ['empty', 'nonstream', 'before_error', 'after_error'])
async def test_ttft_unknown_and_partial_failure(capture, entry, mode):
    with provider(mode) as (base, requests):
        with capture.tracer.start_as_current_span('agent.run'):
            if mode in {'before_error', 'after_error'}:
                with pytest.raises(ModelServiceError):
                    await invoke(capture, base, entry)
            else:
                await invoke(capture, base, entry, streaming=mode != 'nonstream')
        assert len(requests) == 1
    models = [span for span in spans(capture) if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 1
    assert ('llm.ttft_ms' in attrs(models[0])) == (mode == 'after_error')
    if mode == 'after_error':
        assert attrs(models[0])['llm.ttft_ms'] >= 25
    else:
        assert 'llm.time_to_first_token' not in attrs(models[0])
        assert not [event for event in models[0].get('events', []) if event['name'] == 'first_token_received']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['empty', 'before_error', 'after_error'])
async def test_ttft_legacy_unknown_and_partial_failure(capture, mode):
    from nexent.core.model_errors import ModelInvocationTerminalError

    with provider(mode) as (base, requests):
        with capture.tracer.start_as_current_span('agent.run'), pytest.raises(ModelInvocationTerminalError):
            await invoke(capture, base, 'legacy')
        assert len(requests) == 1
    models = [span for span in spans(capture) if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 1
    assert ('llm.ttft_ms' in attrs(models[0])) == (mode == 'after_error')
    if mode == 'after_error':
        first = [event for event in models[0]['events'] if event['name'] == 'first_token_received']
        assert len(first) == 1 and attrs(models[0])['llm.ttft_ms'] >= 25


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['sync', 'async', 'legacy'])
async def test_ttft_each_physical_retry_preserves_safe_facts(capture, entry):
    with provider('retry_empty') as (base, requests):
        with capture.tracer.start_as_current_span('agent.run'):
            answer = await invoke(capture, base, entry, attempts=2, empty_policy='retry_uncommitted')
        assert answer.endswith('final') and len(requests) == 2
    saved = spans(capture)
    models = [span for span in saved if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 2
    models.sort(key=lambda span: int(span['startTimeUnixNano']))
    first, second = [attrs(span) for span in models]
    assert second['nexent.previous_attempt_id'] == first['nexent.attempt_id']
    assert first['nexent.attempt_id'] != second['nexent.attempt_id']
    assert first['nexent.business_status'] == 'failed' and second['nexent.business_status'] == 'completed'
    for model, request in zip(models, requests):
        values = attrs(model)
        assert json.loads(values['nexent.raw.value'])['request'] == request
        assert 'synthetic' not in values['nexent.raw.value']
        assert len([event for event in model['events'] if event['name'] == 'first_token_received']) == 1
        assert values['llm.time_to_first_token'] >= 0.025
    assert '思考' in first['nexent.reasoning.value']
    assert 'final' in second['output.value']
    assert all('llm.ttft_ms' not in attrs(span) for span in saved if span not in models)
    histogram = capture.reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
    assert histogram.count == 2
    assert histogram.sum == pytest.approx(sum(attrs(span)['llm.time_to_first_token'] for span in models))


@pytest.mark.asyncio
async def test_ttft_sampling_fallback_is_a_separate_physical_attempt(capture):
    with provider('sampling_fallback') as (base, requests):
        with capture.tracer.start_as_current_span('agent.run'):
            answer = await invoke(capture, base, 'legacy')
        assert answer.endswith('final') and len(requests) == 2
    models = [span for span in spans(capture) if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 2
    models.sort(key=lambda span: int(span['startTimeUnixNano']))
    first, second = [attrs(span) for span in models]
    assert 'llm.ttft_ms' not in first and second['llm.ttft_ms'] >= 25
    assert second['nexent.previous_attempt_id'] == first['nexent.attempt_id']
    assert second['nexent.retry_reason'] == 'MODEL_SAMPLING_FALLBACK'
    assert 'temperature' in requests[0] and 'temperature' not in requests[1]
    for model, request in zip(models, requests):
        assert json.loads(attrs(model)['nexent.raw.value'])['request'] == request
    histogram = capture.reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
    assert histogram.count == 1 and histogram.sum == second['llm.time_to_first_token']
