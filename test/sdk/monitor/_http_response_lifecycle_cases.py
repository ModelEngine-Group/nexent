# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""NB-AC01/03: real ASGI instrumentation covers the complete response send."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from nexent.monitor.monitoring import MonitoringConfig, get_monitoring_manager


@pytest.fixture
def instrument(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, 'get_tracer_provider', lambda: provider)
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, '_config', MonitoringConfig(enable_telemetry=True))
    yield manager, exporter
    provider.shutdown()


def scope(path='/nb/v1/chat/run', headers=None):
    return {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
            'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': path,
            'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
            'headers': headers or [], 'server': ('northbound', 5013), 'client': ('client', 1234)}


async def receive():
    await asyncio.Event().wait()


def server_spans(exporter):
    return [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['complete', 'send_error', 'cancel'])
async def test_nb_ac001_span_stays_open_until_last_send(instrument, outcome):
    manager, exporter = instrument
    app = FastAPI()
    last_send = asyncio.Event()
    release = asyncio.Event()
    chunks = []

    @app.post('/nb/v1/chat/run')
    async def run():
        async def body():
            yield b'data: first\n\n'
            yield b'data: last\n\n'
        return StreamingResponse(body(), media_type='text/event-stream')

    assert manager.setup_fastapi_app(app)

    async def send(message):
        chunks.append(message)
        if message['type'] == 'http.response.body' and not message.get('more_body', False):
            last_send.set()
            await release.wait()
            if outcome == 'send_error':
                raise RuntimeError('controlled transport failure')

    task = asyncio.create_task(app(scope(), receive, send))
    await asyncio.wait_for(last_send.wait(), 3)
    assert not server_spans(exporter), 'Server span ended before last send completed'
    assert b''.join(m.get('body', b'') for m in chunks) == b'data: first\n\ndata: last\n\n'
    if outcome == 'cancel':
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        if outcome == 'send_error':
            with pytest.raises(RuntimeError, match='controlled transport failure'):
                await task
        else:
            await task
    spans = server_spans(exporter)
    assert len(spans) == 1 and spans[0].end_time >= spans[0].start_time
    if outcome == 'send_error':
        assert spans[0].status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 503])
async def test_nb_ac003_nonstream_and_http_errors_end_span(instrument, status):
    manager, exporter = instrument
    app = FastAPI()

    @app.post('/nb/v1/chat/run')
    async def run():
        return JSONResponse({'result': 'unchanged'}, status_code=status)

    assert manager.setup_fastapi_app(app)
    messages = []

    async def send(message):
        messages.append(message)

    await app(scope(), receive, send)
    spans = server_spans(exporter)
    assert len(spans) == 1
    assert spans[0].attributes.get('http.status_code', spans[0].attributes.get('http.response.status_code')) == status
    assert messages[0]['status'] == status
    assert b'unchanged' in messages[-1]['body']


@pytest.mark.asyncio
async def test_nb_ac002_concurrent_requests_keep_separate_trace_context(instrument):
    manager, exporter = instrument
    app = FastAPI()
    entered = 0
    both = asyncio.Event()

    @app.post('/nb/v1/chat/run')
    async def run():
        nonlocal entered
        entered += 1
        if entered == 2:
            both.set()
        await both.wait()
        return JSONResponse({'ok': True})

    assert manager.setup_fastapi_app(app)

    async def send(_message):
        pass

    ids = ['1' * 32, '2' * 32]
    await asyncio.gather(*(app(scope(headers=[(b'traceparent', f'00-{tid}-1111111111111111-01'.encode())]),
                              receive, send) for tid in ids))
    spans = server_spans(exporter)
    assert {f'{span.context.trace_id:032x}' for span in spans} == set(ids)
    assert len({span.context.span_id for span in spans}) == 2


@pytest.mark.asyncio
async def test_nb_ac003_disabled_monitoring_keeps_response_without_spans(instrument, monkeypatch):
    manager, exporter = instrument
    monkeypatch.setattr(manager, '_config', MonitoringConfig(enable_telemetry=False))
    app = FastAPI()

    @app.post('/nb/v1/chat/run')
    async def run():
        return JSONResponse({'ok': True})

    assert manager.setup_fastapi_app(app) is False
    messages = []

    async def send(message):
        messages.append(message)

    await app(scope(), receive, send)
    assert messages[0]['status'] == 200 and not exporter.get_finished_spans()
