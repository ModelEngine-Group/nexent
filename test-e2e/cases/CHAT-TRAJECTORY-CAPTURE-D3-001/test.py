# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The actual smolagents worker emits facts consumed by the cold HTTP reader."""

import hashlib
import json
import threading
from typing import ClassVar

import pytest
from nexent.core.agents.agent_model import AgentConfig, ModelConfig, ToolConfig
from opentelemetry import trace
from smolagents import Tool

pytestmark = [pytest.mark.case_id('CHAT-TRAJECTORY-CAPTURE-D3-001'), pytest.mark.stage('D3')]


def attrs(span):
    return {item['key']: next(iter(item['value'].values())) for item in span.get('attributes', [])}


def data(response):
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private,no-store'
    return response.json()['data']


def snapshot(runtime, client):
    meta = json.loads(next(runtime.root.rglob('meta.json')).read_text())
    run = meta['runs'][-1]
    return data(client.get('/trajectory/conversations/123/snapshot',
                           params={'trajectory_id': run['trajectory_id']}, headers={'Authorization': 'admin'}))


def test_capture_actual_worker_retry_keeps_failed_partial_and_cold_reads(runtime):
    def reply(request, number, emit):
        emit(reasoning='Reasoning for the physical attempt')
        if number == 1:
            emit('failed-partial')
            emit(error=True)
        else:
            emit('<final_answer>completed-answer</final_answer>')
            emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 2
    saved = runtime.spans()
    models = [span for span in saved if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 2
    models.sort(key=lambda span: int(attrs(span)['nexent.attempt_no']))
    first, second = [attrs(span) for span in models]
    assert first['nexent.business_status'] == 'failed'
    assert second['nexent.business_status'] == 'completed'
    assert first['nexent.attempt_id'] == second['nexent.previous_attempt_id']
    assert first['nexent.record_id'] != second['nexent.record_id']
    assert 'failed-partial' in first['output.value']
    assert all(json.loads(attrs(span)['nexent.raw.value'])['request'] == request
               for span, request in zip(models, requests))
    with runtime.client() as client:
        result = snapshot(runtime, client)
        assert result['coverage']['complete']
        assert len([n for n in result['nodes'] if n['kind'] == 'model']) == 2
        root = next(n for n in result['nodes'] if n['parent_id'] is None)
        assert root['display_trace_id'] == '123' and root['model_call_count'] == 2
        assert client.get('/trajectory/conversations/123', headers={'Authorization': 'user'}).status_code == 403


def test_capture_parallel_tools_nested_output_and_full_local_body(runtime, monkeypatch):
    from nexent.core.agents import nexent_agent as module

    calls, barrier = [], threading.Barrier(2)
    large = '完整工具结果' * 55000

    class CaptureEchoTool(Tool):
        name = 'capture_echo'
        description = 'Controlled parallel operation'
        inputs: ClassVar[dict] = {'value': {'type': 'string', 'description': 'The requested controlled value'}}
        output_type = 'string'
        observer = None

        def forward(self, value: str) -> str:
            span = trace.get_current_span()
            calls.append((value, span.get_span_context().span_id, dict(span.attributes)))
            barrier.wait(timeout=3)
            return large + value

    monkeypatch.setattr(module, 'CaptureEchoTool', CaptureEchoTool, raising=False)
    config = AgentConfig(name='root', description='Controlled Agent', model_name='model', max_steps=2,
                         tools=[ToolConfig(class_name='CaptureEchoTool', name='capture_echo',
                                           source='local', params={}),
                                ToolConfig(class_name='ParallelExecutorTool', name='parallel_executor',
                                           source='local', params={})])

    def reply(request, number, emit):
        emit('<code>\nparallel_executor(tasks=[(capture_echo, {"value": "left"}), '
             '(capture_echo, {"value": "right"})])\n</code>' if number == 1
             else '<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, config=config)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 2
    assert sorted(value for value, _, _ in calls) == ['left', 'right']
    saved = runtime.spans()
    tools = [span for span in saved if attrs(span).get('tool.name') == 'capture_echo']
    assert len(tools) == 2
    for span in tools:
        values = attrs(span)
        assert large in values['output.value']
        assert values['nexent.call_id']
        assert json.loads(values['tool.definition'])['name'] == 'capture_echo'
        assert int(span['spanId'], 16) in {identity for _, identity, _ in calls}
    assert len({attrs(span)['nexent.record_id'] for span in tools}) == 2
    with runtime.client() as client:
        result = snapshot(runtime, client)
        assert result['coverage']['complete']
        root = next(n for n in result['nodes'] if n['parent_id'] is None)
        assert root['tool_call_count'] == 4
        assert len([n for n in result['nodes'] if n['name'] == 'python_interpreter']) == 1
        assert len([n for n in result['nodes'] if n['name'] == 'capture_echo']) == 2


def test_capture_actual_worker_cancel_preserves_partial_output(runtime):
    received, release = threading.Event(), threading.Event()

    def reply(request, number, emit):
        emit('partial-before-cancellation')
        received.set()
        assert release.wait(timeout=5)
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, task = runtime.run(base, submit_only=True)
        try:
            assert received.wait(timeout=5)
            assert info.observer.capture_first_output.wait(timeout=5)
            info.cancellation_scope.cancel()
            release.set()
            task.future.result(timeout=5)
        finally:
            release.set()
        assert info.attempt_outcome == 'stopped'
        assert len(requests) == 1
    saved = runtime.spans()
    root = next(span for span in saved if span['name'] == 'agent.run')
    assert attrs(root)['nexent.business_status'] == 'cancelled'
    models = [span for span in saved if attrs(span).get('openinference.span.kind') == 'LLM']
    assert len(models) == 1
    assert attrs(models[0])['nexent.business_status'] == 'cancelled'
    assert 'partial-before-cancellation' in attrs(models[0])['output.value']


def test_capture_parallel_subagents_keep_invocations_and_nested_tool_ancestry(runtime, monkeypatch):
    from nexent.core.agents import nexent_agent as module

    barrier, calls = threading.Barrier(2), []

    class CaptureLeafTool(Tool):
        name = 'capture_leaf'
        description = 'Controlled nested operation'
        inputs: ClassVar[dict] = {'value': {'type': 'string', 'description': 'The leaf value'}}
        output_type = 'string'
        observer = None

        def forward(self, value: str) -> str:
            calls.append(dict(trace.get_current_span().attributes))
            barrier.wait(timeout=3)
            return 'leaf-result-' + value

    monkeypatch.setattr(module, 'CaptureLeafTool', CaptureLeafTool, raising=False)
    child = AgentConfig(name='child', agent_id=9, version_no=2, description='Controlled child', model_name='child', max_steps=2,
                        tools=[ToolConfig(class_name='CaptureLeafTool', name='capture_leaf', source='local', params={})])
    root = AgentConfig(name='root', agent_id=7, version_no=3, description='Controlled root', model_name='model', max_steps=2,
                       tools=[ToolConfig(class_name='ParallelExecutorTool', name='parallel_executor',
                                         source='local', params={})],
                       worker_agents=[child])

    def reply(request, number, emit):
        if request['model'] == 'model':
            answer = ('<code>\nparallel_executor(tasks=[(child, {"task": "left"}), '
                      '(child, {"task": "right"})])\n</code>') if number == 1 else '<final_answer>root-done</final_answer>'
        else:
            answer = ('<final_answer>child-done</final_answer>' if 'leaf-result-' in json.dumps(request['messages'])
                      else '<code>\ncapture_leaf(value="executed")\n</code>')
        emit(answer)
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        models = [ModelConfig(cite_name=alias, model_name=model, url=base, api_key='synthetic')
                  for alias, model in [('model', 'model'), ('child', 'child-model')]]
        info, _ = runtime.run(base, config=root, models=models)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 6
    assert len(calls) == 2
    saved = runtime.spans()
    children = [span for span in saved if span['name'] == 'agent.subagent.child']
    assert len(children) == 2
    assert len({attrs(span)['subagent.invocation_id'] for span in children}) == 2
    root_invocation = attrs(next(span for span in saved if span['name'] == 'agent.run'))['nexent.invocation_id']
    child_invocations = {attrs(span)['nexent.record_id']: attrs(span)['subagent.invocation_id'] for span in children}
    for span in children:
        assert attrs(span)['agent.version_no'] == '2'
        assert attrs(span)['nexent.invocation_id'] == attrs(span)['subagent.invocation_id']
        assert attrs(span)['nexent.parent_invocation_id'] == root_invocation
    assert {call['nexent.local.nexent.invocation_id'] for call in calls} == set(child_invocations.values())
    with runtime.client() as client:
        result = snapshot(runtime, client)
    assert result['coverage']['complete']
    nodes = {n['id']: n for n in result['nodes']}
    agents = [n for n in nodes.values() if n['kind'] == 'agent' and n['parent_id'] is not None]
    assert len(agents) == 2
    for agent in agents:
        assert agent['agent_version_no'] == 2
        assert agent['attributes']['nexent.invocation_id'] == child_invocations[agent['id']]
        assert agent['attributes']['nexent.parent_invocation_id'] == root_invocation
        assert agent['model_call_count'] == 2 and agent['tool_call_count'] == 2
        tools = [n for n in nodes.values() if n['kind'] == 'tool' and n['parent_id'] == agent['id']]
        assert len(tools) == 1 and tools[0]['name'] == 'python_interpreter'
        leaves = [n for n in nodes.values() if n['parent_id'] == tools[0]['id']]
        assert len(leaves) == 1 and leaves[0]['name'] == 'capture_leaf'
    root = next(n for n in nodes.values() if n['parent_id'] is None)
    assert root['agent_version_no'] == 3
    assert all(n['agent_version_no'] is None for n in nodes.values() if n['kind'] != 'agent')
    assert root['model_call_count'] == 6 and root['tool_call_count'] == 6


def test_capture_versions_are_frozen_per_execution_and_cold_read(runtime):
    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        for version, name in [(3, 'Historical'), (0, None), (None, None)]:
            config = AgentConfig(name='root', agent_id=7, version_no=version, version_name=name,
                                 description='Versioned Agent', model_name='model', tools=[], max_steps=2)
            info, _ = runtime.run(base, config=config)
            assert info.attempt_outcome == 'completed'
            config.version_no = 99
            config.version_name = 'Current'
        assert len(requests) == 3
    with runtime.client() as client:
        rows = data(client.get('/trajectory/records', headers={'Authorization': 'admin'}))['items']
        assert {row['root_agent_version_no'] for row in rows} == {3, 0, None}
        for row in rows:
            result = data(client.get('/trajectory/conversations/123/snapshot', headers={'Authorization': 'admin'},
                                     params={'trajectory_id': row['trajectory_id']}))
            root = next(n for n in result['nodes'] if n['parent_id'] is None)
            assert root['agent_version_no'] == row['root_agent_version_no']
            assert root['agent_version_name'] == ('Historical' if root['agent_version_no'] == 3 else None)
    agents = [attrs(span) for span in runtime.spans() if span['name'] == 'agent.run']
    assert {item.get('agent.version_no') for item in agents} == {'3', '0', None}


@pytest.mark.parametrize('first_agent', [7, None])
def test_capture_root_switch_keeps_directory_and_native_context(runtime, first_agent):
    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        runtime.run(base, agent_id=first_agent, sampled=False)
        runtime.catalog.agent_id = '8'
        runtime.run(base, agent_id=8, sampled=False)
        assert len(requests) == 2
    manifests = list(runtime.root.rglob('meta.json'))
    assert len(manifests) == 1
    meta = json.loads(manifests[0].read_text())
    assert meta['storage_agent_id'] == (str(first_agent) if first_agent is not None else None)
    assert len(meta['runs']) == 2
    assert len(list(runtime.root.rglob('*.otlp.jsonl'))) == 2
    roots = [span for span in runtime.spans() if attrs(span).get('nexent.trajectory.root')]
    assert len(roots) == 2
    assert all(attrs(span)['nexent.trace_id'] == attrs(span)['session.id'] == '123' for span in roots)
    assert all(len(span['traceId']) == 32 and int(span['spanId'], 16) > 0 for span in roots)
    assert all(int(span['flags']) & 1 == 0 for span in roots)
    assert not runtime.remote.get_finished_spans()
    with runtime.client() as client:
        result = data(client.get('/trajectory/conversations/123', headers={'Authorization': 'admin'}))
        assert len(result['executions']) == 2


@pytest.mark.parametrize('sink', ['otlp', 'local_file'])
@pytest.mark.parametrize('content_mode', ['summary', 'metrics', 'full'])
def test_capture_actual_configuration_sinks_and_full_safety(runtime, telemetry_receiver, sink, content_mode):
    runtime.configure(sink, telemetry_receiver.endpoint, content_mode=content_mode)
    large = '完整模型输入' * 16000

    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, query=large)
        assert info.attempt_outcome == 'completed' and len(requests) == 1
    runtime.flush_remote()
    files = list(runtime.root.rglob('*.otlp.jsonl'))
    assert bool(files) == (sink != 'otlp')
    assert bool(telemetry_receiver.requests) == (sink != 'local_file')
    assert all(path == '/v1/traces' for path, _ in telemetry_receiver.requests)
    if files:
        assert files[0].stat().st_size > 256 * 1024
        models = [s for s in runtime.spans() if attrs(s).get('openinference.span.kind') == 'LLM']
        assert len(models) == 1
        assert json.loads(attrs(models[0])['nexent.raw.value'])['request'] == requests[0]
        assert large in attrs(models[0])['input.value']
        meta = json.loads(next(runtime.root.rglob('meta.json')).read_text())['runs'][0]
        assert meta['capture_state'] == 'ready'
        assert meta['confirmed_bytes'] == files[0].stat().st_size
        assert meta['confirmed_sha256'] == hashlib.sha256(files[0].read_bytes()).hexdigest()
    for _, message in telemetry_receiver.requests:
        spans = [s for resource in message.resource_spans for scope in resource.scope_spans for s in scope.spans]
        assert all(s.name != 'model.attempt' for s in spans)
        assert all(not item.key.startswith('nexent.local.') for s in spans for item in s.attributes)
        assert all(large not in item.value.string_value for s in spans for item in s.attributes)


@pytest.mark.parametrize('failed_sink', ['remote', 'local'])
def test_capture_selected_exporter_faults_do_not_retry_business(runtime, telemetry_receiver, failed_sink, monkeypatch):
    from infrastructure.observability.trajectory_store import RunWriter

    runtime.configure('otlp' if failed_sink == 'remote' else 'local_file', telemetry_receiver.endpoint)
    if failed_sink == 'remote':
        telemetry_receiver.status = 503
    else:
        def fail_append(*args, **kwargs):
            raise OSError('Controlled local I/O failure')

        monkeypatch.setattr(RunWriter, 'append', fail_append)

    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base)
        assert info.attempt_outcome == 'completed' and len(requests) == 1
    runtime.flush_remote()
    if failed_sink == 'remote':
        assert telemetry_receiver.requests
        assert not list(runtime.root.rglob('meta.json'))
    else:
        assert not telemetry_receiver.requests
        run = json.loads(next(runtime.root.rglob('meta.json')).read_text())['runs'][0]
        assert run['capture_state'] == 'incomplete'


def test_capture_disabled_and_remote_mode_preserve_historical_files_and_cold_read(runtime, telemetry_receiver):
    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        runtime.run(base)
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.root.rglob('*') if p.is_file()}
        runtime.configure('otlp', telemetry_receiver.endpoint)
        runtime.run(base)
        runtime.flush_remote()
        assert telemetry_receiver.requests
        exported = len(telemetry_receiver.requests)
        runtime.configure('local_file', telemetry_receiver.endpoint, enabled=False)
        runtime.run(base)
        runtime.flush_remote()
        assert len(requests) == 3 and len(telemetry_receiver.requests) == exported
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.root.rglob('*') if p.is_file()}
    assert before == after
    with runtime.client() as client:
        result = snapshot(runtime, client)
        assert result['coverage']['complete']


def test_capture_rejected_protocol_retains_output_without_executing_code(runtime, monkeypatch):
    from nexent.core.agents import nexent_agent as module

    executed = []

    class CaptureCanaryTool(Tool):
        name = 'capture_canary'
        description = 'A canary that must not execute'
        inputs: ClassVar[dict] = {}
        output_type = 'string'

        def forward(self) -> str:
            executed.append(True)
            return 'unexpected'

    monkeypatch.setattr(module, 'CaptureCanaryTool', CaptureCanaryTool, raising=False)
    config = AgentConfig(name='root', description='Controlled Agent', model_name='model', max_steps=2,
                         output_protocol='final_envelope', enable_protocol_repair_retry=True,
                         tools=[ToolConfig(class_name='CaptureCanaryTool', name='capture_canary',
                                           source='local', params={})])

    def reply(request, number, emit):
        emit('<code>capture_canary()</code>' if number == 1 else '<final_answer>safe-answer</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, config=config)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 2
    assert not executed
    models = [s for s in runtime.spans() if attrs(s).get('openinference.span.kind') == 'LLM']
    assert len(models) == 2
    assert any('capture_canary()' in attrs(s)['output.value'] for s in models)
    assert any('safe-answer' in attrs(s)['output.value'] for s in models)
    assert not [s for s in runtime.spans() if attrs(s).get('tool.name') == 'capture_canary']


def test_capture_independent_process_reads_published_facts_without_runtime_caches(runtime):
    def reply(request, number, emit):
        emit(reasoning='persisted-thinking')
        emit('<final_answer>persisted-answer</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        runtime.run(base)
        assert len(requests) == 1
    with runtime.process_client() as client:
        result = snapshot(runtime, client)
        assert result['coverage']['complete']
        models = [n for n in result['nodes'] if n['kind'] == 'model']
        assert len(models) == 1
        assert 'persisted-thinking' in models[0]['reasoning']['text']
        assert 'persisted-answer' in models[0]['output']['text']
        root = next(n for n in result['nodes'] if n['parent_id'] is None)
        assert root['display_trace_id'] == '123' and root['model_call_count'] == 1
        assert client.get('/trajectory/conversations/123', headers={'Authorization': 'user'}).status_code == 403
