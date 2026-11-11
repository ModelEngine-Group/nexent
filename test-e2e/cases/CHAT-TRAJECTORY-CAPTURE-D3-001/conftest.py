# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private smolagents workers, protocol provider and cold HTTP trajectory reads."""

import asyncio
import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import TrajectoryFileStore
from management.api.observability import trajectory as api
from management.services.trajectory.primitives import ReferenceStore
from management.services.trajectory.service import TrajectoryService
from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ModelConfig
from nexent.core.agents.run_agent import agent_run_thread
from nexent.core.agents.sandbox import SandboxConfig, SandboxPoolManager
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    ManagedThreadSpec,
    RunCancellationScope,
    ThreadManager,
)
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)
from nexent.monitor.monitoring import MonitoringConfig, MonitoringManager
from opentelemetry import metrics, trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON


@contextmanager
def scripted_provider(reply):
    """The callback controls frames after observing the actual protocol request."""
    requests, failures = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()

            def emit(content=None, *, reasoning=None, error=False, done=False):
                if done:
                    body = '[DONE]'
                elif error:
                    body = json.dumps({'error': {'message': '500 server error in controlled fixture',
                                                 'type': 'server_error'}})
                else:
                    delta = {}
                    if content is not None:
                        delta['content'] = content
                    if reasoning is not None:
                        delta['reasoning_content'] = reasoning
                    body = json.dumps({
                        'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'model',
                        'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}],
                    })
                self.wfile.write(('data: ' + body + '\n\n').encode())
                self.wfile.flush()

            try:
                reply(request, len(requests), emit)
            except (BrokenPipeError, ConnectionResetError):
                # Closing a cancelled client is an expected protocol outcome.
                pass
            except Exception as error:  # noqa: BLE001 - Surface fixture callback errors on the test thread.
                failures.append(error)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.block_on_close = True
    thread = threading.Thread(target=server.serve_forever, name='capture-provider')
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not failures


@pytest.fixture
def telemetry_receiver():
    state = SimpleNamespace(status=200, requests=[])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            message = ExportTraceServiceRequest()
            message.ParseFromString(body)
            state.requests.append((self.path, message))
            self.send_response(state.status)
            self.send_header('Content-Length', '0')
            self.end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name='capture-telemetry')
    thread.start()
    state.endpoint = f'http://127.0.0.1:{server.server_port}'
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


class Catalog:
    """Only the PG identity boundary is controlled; capture and reads are real."""

    def __init__(self):
        self.agent_id = '7'

    def tenants(self, actor):
        return ['tenant']

    def actor_active(self, actor):
        return actor.user_id == 'admin' and actor.role == 'ADMIN'

    def user_active(self, tenant_id, user_id):
        return (tenant_id, user_id) == ('tenant', 'owner')

    def names(self, tenants):
        assert tenants == ['tenant']
        return {'tenant': 'Controlled tenant'}

    def candidates(self, tenants, *, target_user_id=None, conversation_id=None, limit):
        assert limit > 0 and conversation_id in (None, '123')
        return [self.resolve(tenants, '123', target_user_id=target_user_id)]

    def message_upper(self, conversation_id):
        return 0

    def resolve(self, tenants, conversation_id, *, target_user_id=None):
        assert tenants == ['tenant'] and str(conversation_id) == '123'
        assert target_user_id in (None, 'owner')
        return {'tenant_id': 'tenant', 'user_id': 'owner', 'user_name': 'Owner',
                'conversation_id': '123', 'agent_id': self.agent_id, 'category': 'workbench',
                'conversation_title': 'Controlled conversation'}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from nexent.core.agents import nexent_agent as agent_module

    monkeypatch.setattr(SandboxPoolManager, '_instance', None)
    clients = []
    create_model = agent_module.NexentAgent.create_model

    def observed_model(factory, *args, **kwargs):
        model = create_model(factory, *args, **kwargs)
        clients.append(model.client)
        return model

    monkeypatch.setattr(agent_module.NexentAgent, 'create_model', observed_model)
    directory = tmp_path.resolve()
    TrajectoryFileStore.provision(directory)
    store = TrajectoryFileStore(directory, authorize=lambda _: None)
    local = LocalTrajectoryProcessor(store, get_agent_monitoring_context)
    threads = ThreadManager('capture-fixture', {
        lane: LanePolicy(lane, 6, 8)
        for lane in ('agent-run', 'model-tool-io', 'sandbox', 'control-io', 'background-service', 'trajectory-read')
    })
    threads.start()
    remote = InMemorySpanExporter()
    provider = TracerProvider(sampler=local.wrap_sampler(ALWAYS_ON), shutdown_on_exit=False)
    provider.add_span_processor(local)
    manager = MonitoringManager()
    previous = dict(manager.__dict__)
    manager._config = MonitoringConfig(enable_telemetry=True, provider='local_file', local_span_processor=local,
                                       export_metrics=False, trace_max_chars=32)
    manager._tracer = provider.get_tracer('capture-fixture')
    local.start(threads, ManagedThreadSpec('trajectory-writer', 'capture-test', close_hook=local.request_stop))
    catalog = Catalog()
    observers = []
    active_provider, extra_providers = [provider], []

    def configure(sink, endpoint, *, enabled=True, content_mode='summary'):
        from nexent.monitor import monitoring as module

        actual_exporter = module.OTLPSpanExporterHTTP
        actual_tracer_provider = module.TracerProvider
        actual_meter_provider = module.MeterProvider

        def exporter(**kwargs):
            return actual_exporter(**kwargs, timeout=0.2)

        # The SDK permits one global registration per process. Keep this fixture's
        # repeated startup configurations isolated while executing real setup/export.
        with monkeypatch.context() as patch:
            patch.setattr(module, 'OTLPSpanExporterHTTP', exporter)
            patch.setattr(module, 'TracerProvider',
                          lambda **kwargs: actual_tracer_provider(**kwargs, shutdown_on_exit=False))
            patch.setattr(module, 'MeterProvider',
                          lambda **kwargs: actual_meter_provider(**kwargs, shutdown_on_exit=False))
            patch.setattr(trace, 'set_tracer_provider', lambda value: None)
            patch.setattr(trace, 'get_tracer', lambda *a, **kw: manager._tracer_provider.get_tracer(*a, **kw))
            patch.setattr(metrics, 'set_meter_provider', lambda value: None)
            patch.setattr(metrics, 'get_meter', lambda *a, **kw: manager._meter_provider.get_meter(*a, **kw))
            manager.configure(MonitoringConfig(
                enable_telemetry=enabled, provider=sink, local_span_processor=local,
                export_metrics=False, instrument_requests=False, otlp_endpoint=endpoint,
                trace_content_mode=content_mode, trace_max_chars=32,
            ))
        if enabled:
            active_provider[0] = manager._tracer_provider
            extra_providers.append((manager._tracer_provider, manager._meter_provider))

    def flush_remote():
        assert active_provider[0].force_flush(timeout_millis=3000)

    def run(base, *, config=None, query='Controlled question', agent_id=7, submit_only=False, sampled=True,
            models=None):
        current = active_provider[0]
        delegate = ALWAYS_ON if sampled else ALWAYS_OFF
        current.sampler = local.wrap_sampler(delegate) if manager._config.provider != 'otlp' else delegate
        manager._tracer = current.get_tracer('capture-fixture', str(uuid4()))
        observer = MessageObserver()
        observer.capture_first_output = threading.Event()
        original_add_token = observer.add_model_new_token

        def observed_token(token):
            original_add_token(token)
            if token:
                observer.capture_first_output.set()

        monkeypatch.setattr(observer, 'add_model_new_token', observed_token)
        observers.append(observer)
        config = config or AgentConfig(name='root', description='Controlled Agent', tools=[],
                                       model_name='model', max_steps=2)
        stop = threading.Event()
        info = AgentRunInfo(query=query, observer=observer, agent_config=config,
                            model_config_list=models or [ModelConfig(cite_name='model', model_name='model',
                                                                     url=base, api_key='synthetic')],
                            stop_event=stop, cancellation_scope=RunCancellationScope(stop),
                            history=[], conversation_id=123, user_id='owner',
                            sandbox_config=SandboxConfig(auto_sync_outputs=False), thread_manager=threads)
        metadata = AgentRunMetadata(agent_id=agent_id, agent_name=config.name, tenant_id='tenant',
                                    user_id='owner', conversation_id=123, query=query)
        with agent_monitoring_context(metadata):
            task = threads.submit('agent-run', ManagedTaskSpec('capture-agent', 'trajectory-test'),
                                  agent_run_thread, info)
        if not submit_only:
            task.future.result(timeout=20)
            assert local.force_flush(3000)
        return info, task

    def spans():
        assert local.force_flush(3000)
        return [span for path in directory.rglob('*.otlp.jsonl') for line in path.read_text().splitlines()
                for resource in json.loads(line)['resourceSpans'] for scope in resource['scopeSpans']
                for span in scope['spans'] if span['name'] != 'nexent.trajectory.fragment']

    @contextmanager
    def cold_client():
        # A new store/service/cache must derive everything from the published files.
        reader = TrajectoryFileStore(directory, authorize=lambda _: None)
        service = TrajectoryService(reader, catalog, ReferenceStore())
        monkeypatch.setattr(api, 'get_service', lambda: service)
        monkeypatch.setattr(api, 'get_current_user_context',
                            lambda header: ('admin', 'tenant', 'ADMIN') if header == 'admin'
                            else ('owner', 'tenant', 'USER'))
        app = FastAPI()
        app.state.thread_manager = threads
        app.include_router(api.router)
        with TestClient(app) as client:
            yield client

    @contextmanager
    def process_client():
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        repository = Path(__file__).resolve().parents[3]
        environment = dict(os.environ)
        environment['PYTHONPATH'] = os.pathsep.join(
            [str(repository / 'backend'), str(repository / 'sdk'), environment.get('PYTHONPATH', '')])
        errors = directory.parent / f'{directory.name}-cold-reader.stderr'
        with errors.open('w') as stderr:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name('reader.py')), '--root', str(directory),
                 '--fd', str(listener.fileno())],
                pass_fds=(listener.fileno(),), stdout=subprocess.PIPE, stderr=stderr,
                text=True, env=environment,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    assert selector.select(timeout=8), 'Cold reader did not start'
                    line = process.stdout.readline()
                assert line, errors.read_text()[-2000:]
                port = json.loads(line)['port']
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as client:
                    yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                    raise
                closed = process.stdout.read()
                process.stdout.close()
                listener.close()
                assert process.returncode in (0, -signal.SIGTERM), errors.read_text()[-2000:]
                assert json.loads(closed) == {'closed': True, 'active_workers': 0}

    try:
        yield SimpleNamespace(root=directory, store=store, local=local, remote=remote, provider=provider,
                              manager=manager, run=run, spans=spans, client=cold_client,
                              catalog=catalog, observers=observers, http=scripted_provider,
                              configure=configure, flush_remote=flush_remote, process_client=process_client)
    finally:
        for client in clients:
            client.close()
            assert client.is_closed
        pool = SandboxPoolManager._instance
        if pool is not None:
            task = threads.submit('control-io', ManagedTaskSpec('capture-pool-cleanup', 'trajectory-test'),
                                  pool.shutdown, logging.getLogger('capture-test'))
            task.future.result(timeout=5)
        for owned_provider, owned_metrics in extra_providers:
            owned_provider.shutdown()
            owned_metrics.shutdown()
        local.shutdown()
        provider.shutdown()
        asyncio.run(threads.shutdown(timeout=3))
        manager.__dict__.clear()
        manager.__dict__.update(previous)
        assert threads.snapshot().active_count == 0
