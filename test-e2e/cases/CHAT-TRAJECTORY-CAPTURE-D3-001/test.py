# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The actual smolagents worker emits facts consumed by the cold HTTP reader."""

import hashlib
import json
import threading
from typing import ClassVar

import pytest
from opentelemetry import trace
from smolagents import Tool

from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig


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


def test_capture_generated_code_result_and_logs_survive_cold_read(runtime):
    code = "print('执行日志😀')\n{'result': 42}"

    def reply(request, number, emit):
        emit(f'<code>\n{code}\n</code>' if number == 1 else '<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 2
    saved = runtime.spans()
    execution = next(s for s in saved if s['name'] == 'code.execute')
    python = next(s for s in saved if attrs(s).get('tool.name') == 'python_interpreter')
    result = json.loads(attrs(execution)['output.value'])
    assert result == json.loads(attrs(python)['output.value'])
    assert result == {'output': {'result': 42}, 'logs': '执行日志😀\n'}
    assert json.loads(attrs(execution)['input.value']) == {'code': code}
    with runtime.client() as client:
        view = snapshot(runtime, client)
        node = next(n for n in view['nodes'] if n['name'] == 'code.execute')
        assert node['source']['span_id'] == execution['spanId']
        assert node['duration_ms'] == pytest.approx(float(attrs(execution)['nexent.duration_ms']))
        assert not any(n['name'] == 'python_interpreter' for n in view['nodes'])
        assert json.loads(node['output']['text']) == result
        pieces, offset = [], 0
        while True:
            chunk = data(client.get(
                '/trajectory/conversations/123/contents/' + node['output']['content_id'],
                params={'offset': offset, 'limit': 16}, headers={'Authorization': 'admin'},
            ))
            pieces.append(chunk['text'])
            assert chunk['next_offset'] > offset
            offset = chunk['next_offset']
            if chunk['complete']:
                break
        assert json.loads(''.join(pieces)) == result


@pytest.mark.parametrize('creator', [False, True], ids=['clarification', 'creator-card'])
def test_capture_interactive_card_preserves_stop_status(runtime, monkeypatch, creator):
    from infrastructure.nl2agent_tool_config import NL2AGENT_RECEIPT_KEY, NL2A_WRAPPER_NAME
    from nexent.core.agents.cores.smolagents import agent as module
    from ops.services.trajectory.projection import execution_values
    from runtime.agentos.prepared_agent_creator import _Nl2AgentBoundaryObserver

    payload = {'agent_id': 7, 'subtype': 'requirement_clarification', 'questions': [{
        'question_id': 'scope', 'question_type': 'text', 'title': 'Which region?',
        'required': True, 'options': [], 'allow_other': False, 'other_input_expanded': False,
    }]}
    run_id = 'controlled-creator-card'
    conversation_id = '123'
    stop_event = None
    receipt = {NL2AGENT_RECEIPT_KEY: {
        'run_id': run_id, 'conversation_id': conversation_id, 'event_id': 'card', 'payload': payload,
    }}

    class CaptureCreatorCardTool(Tool):
        name = 'capture_creator_card'
        description = 'Deliver a controlled creator card receipt'
        inputs: ClassVar[dict] = {}
        output_type = 'string'
        observer = None

        def forward(self) -> str:
            self.observer.on_mcp_tool_result(NL2A_WRAPPER_NAME, receipt)
            assert self.observer.boundary_reached
            # A valid receipt completes the turn gracefully. Request an explicit stop after delivery.
            assert not stop_event.is_set()
            stop_event.set()
            return 'Card delivered'

    def make_observer(stop):
        nonlocal stop_event
        stop_event = stop
        return _Nl2AgentBoundaryObserver(
            lang='en', stop_event=stop, agent_id=7, run_id=run_id, conversation_id=conversation_id,
        )

    config = None
    if creator:
        monkeypatch.setattr(module, 'CaptureCreatorCardTool', CaptureCreatorCardTool, raising=False)
        config = AgentConfig(
            name='root', description='Controlled Agent', model_name='model', max_steps=2,
            tools=[ToolConfig(class_name='CaptureCreatorCardTool', name='capture_creator_card',
                              source='local', params={})],
        )
    code = ('capture_creator_card()' if creator else
            "ask_user(questions=[{'id': 'scope', 'type': 'text', 'title': 'Which region?'}])")
    factory = make_observer if creator else None

    def reply(request, number, emit):
        emit(f'<code>{code}</code>')
        emit(usage={'prompt_tokens': 9, 'completion_tokens': 4, 'total_tokens': 13})
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, config=config, observer_factory=factory)
        assert len(requests) == 1
    assert info.attempt_outcome == ('stopped' if creator else 'completed')
    events = [json.loads(item) for item in info.observer.get_cached_message()]
    cards = [event for event in events if event['type'] == ('nl2a' if creator else 'human_interaction')]
    assert len(cards) == 1
    assert not any(event['type'] == 'error' for event in events)
    if creator:
        assert info.observer.boundary_reached is True and info.stop_event.is_set()
        assert json.loads(cards[0]['content']) == payload
    root_span = next(span for span in runtime.spans() if span['name'] == 'agent.run')
    expected = 'cancelled' if creator else 'completed'
    assert attrs(root_span)['nexent.business_status'] == expected
    assert attrs(root_span)['nexent.cancelled'] is creator
    meta = json.loads(next(runtime.root.rglob('meta.json')).read_text())
    run = meta['runs'][-1]
    assert run['business_status'] == expected and run['capture_state'] == 'ready'
    with runtime.client() as client:
        result = snapshot(runtime, client)
        root = next(node for node in result['nodes'] if node['parent_id'] is None)
        assert root['status'] == expected
        assert execution_values(123, run, result['nodes'], root['id'])['status'] == (
            'cancelled' if creator else 'success'
        )


def test_capture_actual_worker_retry_keeps_failed_partial_and_cold_reads(runtime):
    def reply(request, number, emit):
        emit(reasoning='Reasoning for ')
        emit(reasoning='the physical attempt')
        if number == 1:
            emit('failed-')
            emit('partial')
            emit(error=True)
        else:
            emit('<final_answer>completed-')
            emit('answer</final_answer>')
            emit(usage={'prompt_tokens': 9, 'completion_tokens': 4, 'total_tokens': 13})
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
    assert int(second['llm.token_count.prompt']) == 9
    assert int(second['llm.token_count.completion']) == 4
    assert int(second['llm.token_count.total']) == 13
    assert 'failed-partial' in first['output.value']
    for span, expected, completed in zip(models, ('failed-partial', '<final_answer>completed-answer</final_answer>'),
                                         (False, True)):
        values = attrs(span)
        output = json.loads(values['output.value'])
        assert output['content_parts'] == [{'type': 'text', 'text': expected}]
        assert output['reasoning_parts'] == [{'type': 'text', 'text': 'Reasoning for the physical attempt'}]
        assert output['complete'] is completed
        assert 'deltas' not in output and 'stream' not in json.loads(values['nexent.raw.value'])
        assert 'unmapped_delta_fields' not in output.get('provider_metadata', {})
        assert all(event['name'] != 'token_generated' for event in span.get('events', []))
        assert float(values['llm.ttft_ms']) >= 0
    for span in saved:
        if span['name'] == 'nexent.trajectory.fragment':
            for event in span.get('events', []):
                assert not {'output.value', 'nexent.reasoning.value', 'nexent.raw.value'} & attrs(event).keys()
    assert all(json.loads(attrs(span)['nexent.raw.value'])['request'] == request
               for span, request in zip(models, requests))
    with runtime.client() as client:
        result = snapshot(runtime, client)
        assert result['coverage']['complete']
        assert len([n for n in result['nodes'] if n['kind'] == 'model']) == 2
        root = next(n for n in result['nodes'] if n['parent_id'] is None)
        assert root['display_trace_id'] == '123' and root['model_call_count'] == 2
        indexed = {n['id']: n for n in result['nodes']}
        reason = 'The model service is temporarily unavailable. Please try again later.'
        assert json.loads(first['nexent.error'])['safe_message'] == reason
        assert indexed[first['nexent.record_id']]['failure_reason'] == reason
        assert 'failure_reason' not in indexed[second['nexent.record_id']]
        for physical, expected in zip(models, ('failed-partial', '<final_answer>completed-answer</final_answer>')):
            body = json.loads(indexed[attrs(physical)['nexent.record_id']]['output']['text'])
            assert body['choices'][0]['delta']['content'] == expected
            assert not {'content_parts', 'provider_metadata', 'complete', 'message_id'} & body.keys()
        assert client.get('/trajectory/conversations/123', headers={'Authorization': 'user'}).status_code == 403


def test_capture_tool_failure_reason_survives_cold_read(runtime, monkeypatch):
    from nexent.core.agents.cores.smolagents import agent as module

    calls = []
    reason = 'The controlled tool rejected the request.'

    class CaptureFailureTool(Tool):
        name = 'capture_failure'
        description = 'A controlled tool failure'
        inputs: ClassVar[dict] = {}
        output_type = 'string'

        def forward(self) -> str:
            calls.append(True)
            raise ValueError(reason)

    monkeypatch.setattr(module, 'CaptureFailureTool', CaptureFailureTool, raising=False)
    config = AgentConfig(name='root', description='Controlled Agent', model_name='model', max_steps=2,
                         tools=[ToolConfig(class_name='CaptureFailureTool', name='capture_failure',
                                           source='local', params={})])

    def reply(request, number, emit):
        emit('<code>\ncapture_failure()\n</code>' if number == 1 else '<final_answer>recovered</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, config=config)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 2 and calls == [True]
    tool_span = next(s for s in runtime.spans() if attrs(s).get('tool.name') == 'capture_failure')
    assert attrs(tool_span)['error.message'] == reason
    with runtime.client() as client:
        view = snapshot(runtime, client)
        node = next(n for n in view['nodes'] if n['name'] == 'capture_failure')
        assert node['source']['span_id'] == tool_span['spanId']
        assert node['status'] == 'failed' and node['failure_reason'] == reason


def test_capture_parallel_tools_nested_output_and_full_local_body(runtime, monkeypatch):
    from nexent.core.agents.cores.smolagents import agent as module

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
        python = next(n for n in result['nodes'] if n['name'] == 'python_interpreter')
        execution = next(n for n in result['nodes'] if n['name'] == 'code.execute')
        assert execution['parent_id'] == python['id'] and execution['kind'] == 'phase'
        assert execution['duration_ms'] >= 0 and execution['duration_ms'] <= python['duration_ms']
        assert execution['usage'] is None and execution['tool_call_count'] is None


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
    provider_body = json.loads(attrs(models[0])['nexent.provider.response.value'])
    assert provider_body['choices'][0]['delta']['content'] == 'partial-before-cancellation'


def test_capture_parallel_subagents_keep_invocations_and_nested_tool_ancestry(runtime, monkeypatch):
    from nexent.core.agents.cores.smolagents import agent as module

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
    child = AgentConfig(name='child', display_name='通用子智能体', agent_id=9, version_no=2, description='Controlled child', model_name='child', max_steps=2,
                        tools=[ToolConfig(class_name='CaptureLeafTool', name='capture_leaf', source='local', params={})])
    root = AgentConfig(name='root', display_name='通用助手', agent_id=7, version_no=3, description='Controlled root', model_name='model', max_steps=2,
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
    children = [span for span in saved if attrs(span).get('subagent.invocation_id')]
    assert len(children) == 2
    assert {attrs(span)['input.value'] for span in children} == {'left', 'right'}
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
        assert agent['name'] == '通用子智能体'
        assert agent['agent_version_no'] == 2
        assert agent['attributes']['nexent.invocation_id'] == child_invocations[agent['id']]
        assert agent['attributes']['nexent.parent_invocation_id'] == root_invocation
        assert agent['model_call_count'] == 2 and agent['tool_call_count'] == 2
        tools = [n for n in nodes.values() if n['kind'] == 'tool' and n['parent_id'] == agent['id']]
        assert len(tools) == 1 and tools[0]['name'] == 'python_interpreter'
        executions = [n for n in nodes.values() if n['parent_id'] == tools[0]['id']]
        assert len(executions) == 1 and executions[0]['name'] == 'code.execute'
        leaves = [n for n in nodes.values() if n['parent_id'] == executions[0]['id']]
        assert len(leaves) == 1 and leaves[0]['name'] == 'capture_leaf'
    root = next(n for n in nodes.values() if n['parent_id'] is None)
    assert root['name'] == '通用助手'
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
    assert meta['agent_id'] == (str(first_agent) if first_agent is not None else None)
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


@pytest.mark.parametrize('sink, dual', [('otlp', False), ('local_file', False), ('otlp', True)])
@pytest.mark.parametrize('content_mode', ['summary', 'metrics', 'full'])
def test_capture_actual_configuration_sinks_and_full_safety(runtime, telemetry_receiver, sink, dual, content_mode):
    runtime.configure(sink, telemetry_receiver.endpoint, content_mode=content_mode, capture_local_traces=dual)
    large = '完整模型输入' * 16000

    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, query=large)
        assert info.attempt_outcome == 'completed' and len(requests) == 1
    runtime.flush_remote()
    files = list(runtime.root.rglob('*.otlp.jsonl'))
    assert bool(files) == (sink == 'local_file' or dual)
    assert bool(telemetry_receiver.requests) == (sink == 'otlp')
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
    remote_spans = [span for _, message in telemetry_receiver.requests for resource in message.resource_spans
                    for scope in resource.scope_spans for span in scope.spans]
    assert all(span.name != 'model.attempt' for span in remote_spans)
    assert all(not item.key.startswith('nexent.local.') for span in remote_spans for item in span.attributes)
    assert all(large not in item.value.string_value for span in remote_spans for item in span.attributes)
    if dual:
        local_root, = [s for s in runtime.spans() if attrs(s).get('nexent.trajectory.root')]
        remote_root, = [s for s in remote_spans if s.name == 'agent.run']
        assert (local_root['traceId'], local_root['spanId']) == (remote_root.trace_id.hex(), remote_root.span_id.hex())


@pytest.mark.parametrize('failed_sink', ['remote', 'local'])
@pytest.mark.parametrize('dual', [False, True])
def test_capture_selected_exporter_faults_do_not_retry_business(runtime, telemetry_receiver, failed_sink, dual,
                                                                 monkeypatch):
    from infrastructure.trace.trajectory_store import RunWriter

    sink = 'otlp' if dual or failed_sink == 'remote' else 'local_file'
    runtime.configure(sink, telemetry_receiver.endpoint, capture_local_traces=dual)
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
    assert bool(telemetry_receiver.requests) == (sink == 'otlp')
    manifests = list(runtime.root.rglob('meta.json'))
    assert bool(manifests) == (dual or failed_sink == 'local')
    if manifests:
        run = json.loads(manifests[0].read_text())['runs'][0]
        assert run['capture_state'] == ('ready' if failed_sink == 'remote' else 'incomplete')


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
    from nexent.core.agents.cores.smolagents import agent as module

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


@pytest.mark.parametrize('workbench', [False, True])
@pytest.mark.parametrize('kind', ['agent', 'skill'])
def test_capture_creator_entrypoints_bind_saved_identity_and_cold_read(runtime, monkeypatch, workbench, kind):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    import httpx
    from fastapi import FastAPI

    from contracts.agent import SystemAgentRef
    from contracts.constants import environment
    from management.api.agent import creator as agent_api
    from management.api.skill import creation as skill_api
    from management.services.agent import creator_run, runtime_client
    from management.services.conversation import creation_history, creator_checkpoints, creator_execution
    from management.services.skill import creation as skill_creation
    from nexent.core.concurrency.context import _reset_current_thread_manager, _set_current_thread_manager
    from nexent.monitor import AgentRunMetadata, agent_monitoring_context, get_agent_monitoring_context
    from runtime.agentos import (
        agent_creator_config, creator_definition, ephemeral, prepared_agent_creator, prepared_skill_creator,
    )
    from runtime.agentos.middleware import AgentOSMiddleware

    system_id = 77 if kind == 'agent' else 78
    system_key = f'nl2{kind}_main'
    target = {'type': 'agent', 'id': 201} if kind == 'agent' else None
    history = {'agent_id': system_id, 'target': target, 'message_records': []}
    saved, run_infos = [], []
    runtime.catalog.agent_id = str(system_id)
    monkeypatch.setattr(creator_execution.system_agent_provider, 'get_creator_ref',
                        lambda *_: SystemAgentRef('shared', system_key, system_id, 0))
    monkeypatch.setattr(creator_execution, 'authorize_target', lambda target, *_: target)
    monkeypatch.setattr(creator_execution, 'get_conversation_history', lambda *_: history)
    monkeypatch.setattr(creation_history, 'get_conversation_history', lambda *_: history)
    monkeypatch.setattr(creation_history, 'create_new_conversation', lambda **kw: (
        history.update(agent_id=kw['agent_id'], target=kw['target']) or {'conversation_id': 123}))
    monkeypatch.setattr(creation_history, 'save_message_unit', lambda **kw: None)
    monkeypatch.setattr('management.services.conversation.model_preferences.read_model_preferences',
                        lambda *_: {'model_parameter_preferences': {}, 'selected_model_id': None})
    monkeypatch.setattr(creator_checkpoints, 'checkpoint_creator_message', Mock())
    monkeypatch.setattr(ephemeral, 'runtime_thread_manager', runtime.threads)
    monkeypatch.setattr(environment, 'JWT_SECRET', 'controlled-creator-trajectory-agentos-key')
    monkeypatch.setattr(agent_creator_config, 'NEXENT_AGENT_CORE', 'smolagents')
    monkeypatch.setattr(prepared_skill_creator, 'NEXENT_AGENT_CORE', 'smolagents')
    creator_lookup = Mock(return_value={'agent_id': system_id, 'version_no': 0, 'max_steps': 2})
    monkeypatch.setattr(creator_definition, 'read_system_creator', creator_lookup)
    model_scope = {
        'model': {'model_id': 11, 'alias': 'model', 'revision': 'v1'},
        'input_budget': 8192, 'context_window_tokens': 8192,
    }
    monkeypatch.setattr(creator_run, 'prepare_creator_model', lambda *_: model_scope)
    monkeypatch.setattr(skill_creation, 'prepare_creator_model', lambda *_: model_scope)
    monkeypatch.setattr(creator_run, '_build_verified_bound_resources_context',
                        AsyncMock(return_value=SimpleNamespace(content={'text': 'Verified bindings'})))
    opened, closed = Mock(), Mock()
    monkeypatch.setattr(creator_run, 'open_nl2agent_tool_grant', opened)
    monkeypatch.setattr(creator_run, 'close_nl2agent_tool_grant', closed)

    def save(message, **kwargs):
        identity = len(saved) + 10
        saved.append((message.role, message.message_idx, identity))
        history['message_records'].append({
            'role': message.role, 'message_index': message.message_idx, 'message_id': identity,
            'message_content': message.message[0].content if message.message else '', 'minio_files': None,
        })
        return identity

    monkeypatch.setattr(creation_history, 'save_message', save)
    monkeypatch.setattr(creator_execution, 'save_message', save)

    management, worker = FastAPI(), FastAPI()
    management.include_router(agent_api.router if kind == 'agent' else skill_api.skill_creator_router)
    permission = (agent_api.require_agent_create_permission if kind == 'agent' else skill_api.require_skill_create_permission)
    management.dependency_overrides[permission] = lambda: None
    public_api = agent_api if kind == 'agent' else skill_api
    monkeypatch.setattr(public_api, 'ENABLE_AGENT_WORKBENCH', True)
    monkeypatch.setattr(public_api, 'get_current_user_info', lambda *_: ('owner', 'tenant', 'en'))
    worker.add_middleware(AgentOSMiddleware)
    worker.include_router(ephemeral.create_ephemeral_run_router())
    load = ephemeral.load_prepared_run

    async def observe_load(payload, actor, materialize):
        assert get_agent_monitoring_context().conversation_id is None
        info = await load(payload, actor, materialize)
        run_infos.append(info)
        return info

    async def runtime_app(scope, receive, send):
        with agent_monitoring_context(AgentRunMetadata()):
            await worker(scope, receive, send)

    async def assert_runtime_response(response):
        assert response.status_code == 200, (response.status_code, (await response.aread()).decode())

    monkeypatch.setattr(ephemeral, 'load_prepared_run', observe_load)
    monkeypatch.setattr(runtime_client, 'create_httpx_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app, root_path='/api'),
        event_hooks={'response': [assert_runtime_response]}, **kwargs,
    ))

    def reply(request, number, emit):
        answer = 'created' if kind == 'agent' else '<skill>\n# created\n</skill>'
        emit(f'<final_answer>{answer}</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        materialization = prepared_agent_creator if kind == 'agent' else prepared_skill_creator
        monkeypatch.setattr(materialization, '_materialize_model', lambda *_: ModelConfig(
            cite_name='model', model_name='model', url=base, api_key='synthetic',
        ))

        async def execute():
            config = {'schema_version': 4, 'mode': f'{kind}_create', 'agent_mounts': [], 'skill_mounts': []}
            path = '/agent/nl2agent/run' if kind == 'agent' else '/skills/nl2skill/run'
            fields = {'agent_id': 201} if kind == 'agent' else {}
            token = _set_current_thread_manager(runtime.threads)
            before = get_agent_monitoring_context()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=management),
                                             base_url='http://management') as client:
                    for turn in range(3):
                        response = await client.post(path, json={
                            **fields, 'query': 'build' if turn != 1 else 'edit',
                            'conversation_id': None if turn == 0 else 123,
                            'retry_user_message_id': 10 if turn == 2 else None,
                            'workbench_config': config if workbench else None,
                        })
                        assert response.status_code == 200 and response.headers['conversation_id'] == '123'
                        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                        assert 'created' in response.text and all(event['type'] != 'error' for event in events), events
                        assert get_agent_monitoring_context() is before
                    response = await client.post(path, json={
                        **fields, 'query': 'unsaved', 'conversation_id': 123, 'persist_history': False,
                        'trajectory': {'conversation_id': 123, 'source_message_id': 10},
                    })
                    assert response.status_code == 200 and 'conversation_id' not in response.headers
                    assert 'created' in response.text
                    assert get_agent_monitoring_context() is before
            finally:
                _reset_current_thread_manager(token)

        asyncio.run(execute())
        assert len(requests) == 4
    assert [role for role, _, _ in saved] == ['user', 'assistant', 'user', 'assistant', 'assistant']
    assert history['agent_id'] == system_id and history['target'] == target
    assert [call.args for call in creator_lookup.call_args_list] == [(system_id, 0, system_key)] * 3
    if kind == 'agent':
        assert opened.call_count == closed.call_count == 4
        assert all(call.args[1] == 201 for call in opened.call_args_list)
    assert all(info.thread_future.done() and info.attempt_outcome == 'completed' for info in run_infos)
    roots = [span for span in runtime.spans() if span['name'] == 'agent.run']
    assert len(roots) == 3
    values = sorted((attrs(span) for span in roots), key=lambda item: int(item['nexent.source_message_id']))
    assert [item['nexent.source_message_id'] for item in values] == ['10', '10', '12']
    assert all(str(item['agent.id']) == str(system_id) for item in values)
    assert all(str(item['nexent.trace_id']) == '123' for item in values)
    assert all(str(item['agent.version_no']) == '0' for item in values)
    assert [item['input.value'] for item in values] == ['build', 'build', 'edit']
    meta_path = next(runtime.root.rglob('meta.json'))
    assert meta_path.parent.parts[-4:] == ('tenant', 'owner', str(system_id), '123')
    meta = json.loads(meta_path.read_text())
    assert len(meta['runs']) == 3
    with runtime.client() as client:
        for run in meta['runs']:
            result = data(client.get('/trajectory/conversations/123/snapshot',
                                     params={'trajectory_id': run['trajectory_id']},
                                     headers={'Authorization': 'admin'}))
            root = next(node for node in result['nodes'] if node['parent_id'] is None)
            assert root['agent_version_no'] == 0
            assert run['root_agent_id'] == str(system_id)
            assert len([node for node in result['nodes'] if node['kind'] == 'model']) == 1


@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled"])
def test_capture_preparation_phases_survive_authorized_worker_and_cold_read(runtime, outcome):
    import asyncio
    from types import SimpleNamespace

    from nexent.monitor.phase_capture import capture_preparation, trace_phase

    calls = []

    @capture_preparation
    async def prepare():
        for agent_id, agent_name in [(2, "子智能体"), (1, "主智能体")]:
            attributes = {"agent.id": str(agent_id), "agent.name": f"agent_{agent_id}", "agent.display_name": agent_name}
            for name, inputs in [
                ("memory.initialize", {"service": "memory"}),
                ("memory.initialize", {"service": "context"}),
                ("memory.external_search", {"query": "controlled", "api_key": "private"}),
                ("memory.load_context", {"layers": ["tenant", "user"]}),
                ("memory.presearch", {"query": "controlled", "top_k": 5}),
            ]:
                try:
                    with trace_phase(name, input_value=inputs, attributes=attributes) as phase:
                        calls.append((agent_id, name))
                        if name == "memory.external_search" and agent_id == 2:
                            if outcome == "failed":
                                raise RuntimeError("private error")
                            if outcome == "cancelled":
                                raise asyncio.CancelledError("private cancellation")
                        if name == "memory.presearch":
                            with trace_phase("memory.retrieve", attributes=attributes) as nested:
                                nested.set_output({"matches": [agent_name]})
                        phase.set_output({"memories": ["controlled preference", agent_name]})
                except (RuntimeError, asyncio.CancelledError):
                    pass
        with trace_phase("agent.sandbox.initialize") as phase:
            with trace_phase("agent.sandbox.warmup"):
                pass
            with trace_phase("agent.sandbox.workspace"):
                pass
            phase.set_output({"ready": True})
        return SimpleNamespace()

    preparation = asyncio.run(prepare())
    original = list(preparation.preparation_trace)

    def reply(request, number, emit):
        emit('<final_answer>completed</final_answer>')
        emit(usage={"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13})
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, preparation=preparation)
        assert info.attempt_outcome == "completed" and len(requests) == 1
    assert len(calls) == 10 and info.preparation_trace == []
    saved = runtime.spans()
    assert {"agent.sandbox.warmup", "agent.sandbox.workspace"} <= {s["name"] for s in saved}
    memories = [s for s in saved if s["name"] == "memory.prepare"]
    assert len(memories) == 2
    assert not any(s["name"] in {"memory.initialize", "memory.presearch", "memory.retrieve"} for s in saved)
    for memory in memories:
        values = attrs(memory)
        facts = [r for r in original if r["attributes"].get("agent.id") == values["agent.id"]]
        assert int(memory["startTimeUnixNano"]) == min(r["started_at_ns"] for r in facts)
        assert int(memory["endTimeUnixNano"]) == max(r["finished_at_ns"] for r in facts)
        assert len(json.loads(values["output.value"])["steps"]) == 6
        assert "private" not in str(values)
    with runtime.client() as client:
        result = snapshot(runtime, client)
        phases = [n for n in result["nodes"] if n["kind"] == "phase"]
        assert not {"agent.sandbox.warmup", "agent.sandbox.workspace"} & {n["name"] for n in phases}
        prepare_node = next(n for n in phases if n["name"] == "agent.prepare")
        grouped = [n for n in phases if n["name"] == "memory.prepare"]
        root = next(n for n in result["nodes"] if n["parent_id"] is None)
        assert len(grouped) == 2 and prepare_node["parent_id"] == root["id"]
        assert {n["attributes"]["agent.display_name"] for n in grouped} == {"子智能体", "主智能体"}
        assert {n["attributes"]["agent.name"] for n in grouped} == {"agent_1", "agent_2"}
        for node in grouped:
            assert node["parent_id"] == prepare_node["id"]
            assert root["started_at"] <= node["started_at"]
            assert node["status"] == (outcome if node["attributes"]["agent.display_name"] == "子智能体" else "success")
            body, offset, chunks = node["output"], 0, []
            for _ in range(100):
                chunk = data(client.get('/trajectory/conversations/123/contents/' + body['content_id'],
                                        params={'offset': offset, 'limit': 8192}, headers={'Authorization': 'admin'}))
                chunks.append(chunk["text"])
                offset = chunk["next_offset"]
                if chunk["complete"]:
                    break
            else:
                pytest.fail("Grouped memory output did not complete")
            text = "".join(chunks)
            assert "controlled preference" in text and "private" not in text
            steps = json.loads(text)["steps"]
            assert len(steps) == 6 and steps[-1]["parent_step"] == 4
            if node["status"] != "success":
                assert steps[2]["error_type"] == ("RuntimeError" if outcome == "failed" else "CancelledError")
        assert root["duration_ms"] >= prepare_node["duration_ms"]
        assert root["model_call_count"] == 1 and root["tool_call_count"] == 0
        assert root["usage"]["total"] == 13 and result["coverage"]["complete"]
        assert any(node["name"] == "agent.sandbox.initialize" for node in phases)


@pytest.mark.parametrize('query', ['用户问题', '用户问题🙂\n' * 5000], ids=['short', 'chunked-unicode'])
def test_capture_agent_query_matches_preview_and_cold_content(runtime, query):
    def reply(request, number, emit):
        emit('<final_answer>done</final_answer>')
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base, query=query)
        assert info.attempt_outcome == 'completed'
        assert len(requests) == 1
    saved = runtime.spans()
    root = next(span for span in saved if span['name'] == 'agent.run')
    assert attrs(root)['input.value'] == query
    execution = json.loads(attrs(root)['nexent.run.snapshot'])
    assert execution['effective_config']['agent_config']['name'] == 'root'
    assert 'query' not in execution
    model = next(span for span in saved if attrs(span).get('openinference.span.kind') == 'LLM')
    assert json.loads(attrs(model)['nexent.raw.value'])['request'] == requests[0]
    assert json.loads(attrs(model)['input.value']) == requests[0]
    with runtime.client() as client:
        result = snapshot(runtime, client)
        node = next(n for n in result['nodes'] if n['parent_id'] is None)
        body = node['input']
        assert query.startswith(body['text'])
        assert body['byte_count'] == len(query.encode())
        assert body['char_count'] == len(query)
        assert body['complete'] == (body['text'] == query)
        chunks, offset = [], 0
        for _ in range(100):
            chunk = data(client.get('/trajectory/conversations/123/contents/' + body['content_id'],
                                    params={'offset': offset, 'limit': 8192}, headers={'Authorization': 'admin'}))
            chunks.append(chunk['text'])
            assert chunk['next_offset'] == offset + len(chunk['text'].encode())
            offset = chunk['next_offset']
            if chunk['complete']:
                break
        else:
            pytest.fail('Input did not finish within the bounded chunk count')
        assert ''.join(chunks) == query
        assert node['model_call_count'] == 1


@pytest.mark.parametrize('answer', ['最终回答', '最终回答🙂' * 3000], ids=['short', 'chunked-unicode'])
def test_capture_model_display_uses_provider_bodies_and_cold_content(runtime, answer):
    def reply(request, number, emit):
        emit(reasoning='分析')
        emit(reasoning='完成')
        emit('<final_answer>')
        emit(answer)
        emit('</final_answer>')
        emit(usage={'prompt_tokens': 9, 'completion_tokens': 4, 'total_tokens': 13})
        emit(done=True)

    with runtime.http(reply) as (base, requests):
        info, _ = runtime.run(base)
        assert info.attempt_outcome == 'completed' and len(requests) == 1
    with runtime.client() as client:
        result = snapshot(runtime, client)
        model = next(n for n in result['nodes'] if n['kind'] == 'model')

        def body(reference):
            parts, offset = [], 0
            for _ in range(100):
                chunk = data(client.get('/trajectory/conversations/123/contents/' + reference['content_id'],
                                        params={'offset': offset, 'limit': 8192},
                                        headers={'Authorization': 'admin'}))
                parts.append(chunk['text'])
                offset = chunk['next_offset']
                if chunk['complete']:
                    break
            else:
                pytest.fail('Model body did not finish within the bounded chunk count')
            text = ''.join(parts)
            assert text.startswith(reference['text'])
            assert len(text.encode()) == reference['byte_count']
            return json.loads(text)

        assert body(model['input']) == requests[0]
        assert body(model['output']) == {
            'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'model',
            'choices': [{'index': 0, 'delta': {'reasoning_content': '分析完成',
                                             'content': '<final_answer>' + answer + '</final_answer>'},
                         'finish_reason': None}],
            'usage': {'prompt_tokens': 9, 'completion_tokens': 4, 'total_tokens': 13},
        }
        assert model['usage']['total'] == 13 and model['ttft_ms'] >= 0
