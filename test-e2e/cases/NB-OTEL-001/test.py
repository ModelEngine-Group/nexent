# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""NB-OTEL-001: real Northbound/Runtime/model/tool trace via Phoenix."""

import json
import os
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
import requests


class PrivateConfig(dict):
    """Keep test failure introspection from revealing credentials."""

    def __repr__(self):
        return '<private telemetry fixture>'


class SecretHeader(str):
    def __repr__(self):
        return '<redacted authorization>'


@pytest.fixture(scope='module')
def config():
    cfg = json.loads(Path(os.environ['NEXENT_TEST_CREDENTIALS']).read_text())
    required = ['northbound_url', 'northbound_api_key', 'agent_name', 'skill_name',
                'skill_marker', 'phoenix_url', 'phoenix_api_key', 'phoenix_project']
    assert all(cfg.get(key) for key in required), 'Incomplete private telemetry fixture'
    return PrivateConfig(cfg)


def read_trace(cfg, trace_id, expected_route, *, require_runtime=False):
    url = (cfg['phoenix_url'].rstrip('/') + '/v1/projects/'
           + quote(cfg['phoenix_project'], safe='') + '/spans')
    deadline = time.monotonic() + 45
    while True:
        response = requests.get(url, params={'trace_id': trace_id, 'limit': 1000},
                                headers={'Authorization': SecretHeader('Bearer ' + cfg['phoenix_api_key'])}, timeout=15)
        if response.status_code == 404 and time.monotonic() < deadline:
            time.sleep(1)
            continue
        assert response.status_code == 200, 'Authenticated Phoenix span query failed'
        spans = response.json()['data']
        root_ready = any(expected_route in str(s['attributes'].get('http.route', '')) for s in spans)
        runtime_ready = any('/agent/internal/northbound/run' in str(s['attributes'].get('http.route', '')) for s in spans)
        if root_ready and (not require_runtime or runtime_ready):
            break
        assert time.monotonic() < deadline, 'Completed HTTP trace was not exported'
        time.sleep(1)
    serialized = json.dumps(spans)
    assert cfg['northbound_api_key'] not in serialized and cfg['phoenix_api_key'] not in serialized
    assert all(s['context']['trace_id'] == trace_id for s in spans)
    assert all(s.get('end_time') for s in spans)
    artifact_dir = os.environ.get('NEXENT_TEST_ARTIFACT_DIR') or os.environ.get('RESULT_DIR')
    assert artifact_dir, 'Runner must provide a task-local artifact directory'
    evidence = Path(artifact_dir) / 'runtime/northbound-otel'
    evidence.mkdir(parents=True, exist_ok=True)
    safe = [{'name': s['name'], 'context': s['context'], 'parent_id': s.get('parent_id'),
             'start_time': s['start_time'], 'end_time': s['end_time'],
             'status_code': s.get('status_code'), 'route': s['attributes'].get('http.route')}
            for s in spans]
    (evidence/f'{trace_id}.json').write_text(json.dumps(safe, indent=2))
    return spans


def chat(cfg, *, authenticated):
    trace_id = uuid4().hex
    headers = {'traceparent': '00-' + trace_id + '-1111111111111111-01'}
    if authenticated:
        headers['Authorization'] = SecretHeader('Bearer ' + cfg['northbound_api_key'])
    body = {'agent_name': cfg['agent_name'], 'query': 'Read the bound skill ' + cfg['skill_name']
            + ' exactly once and report the actual guide marker. Do not invent tool results.'}
    response = requests.post(cfg['northbound_url'].rstrip('/') + '/nb/v1/chat/run',
                             headers=headers, json=body, stream=True, timeout=180)
    with response:
        content = b''.join(response.iter_content(chunk_size=None)).decode()
    return trace_id, response, content


def test_nb_otel_001_real_stream_and_trace_ancestry(config):
    trace_id, response, content = chat(config, authenticated=True)
    assert response.status_code == 200
    events = [json.loads(line[5:].strip()) for line in content.splitlines()
              if line.startswith('data:') and line[5:].strip() != '[DONE]']
    assert not any(event.get('type') == 'error' for event in events)
    finals = ''.join(str(e.get('content', '')) for e in events if e.get('type') == 'final_answer')
    assert config['skill_marker'] in finals
    spans = read_trace(config, trace_id, '/nb/v1/chat/run', require_runtime=True)
    north = [s for s in spans if s['attributes'].get('http.route', '').endswith('/nb/v1/chat/run')]
    runtime = [s for s in spans if '/agent/internal/northbound/run' in s['attributes'].get('http.route', '')]
    assert len(north) == 1 and len(runtime) == 1
    root = north[0]
    assert root['parent_id'] == '1111111111111111'
    assert runtime[0]['parent_id'] == root['context']['span_id']
    # The peer can consume the final body before upstream ASGI cleanup returns.
    assert root['start_time'] <= runtime[0]['start_time'] <= root['end_time']
    # Sandbox warmup also carries model metadata but is not an LLM request.
    models = [s for s in spans if s['attributes'].get('llm.operation.name')]
    tools = [s for s in spans if s['name'] == 'agent.tool.read_skill_md']
    agents = [s for s in spans if s['name'] == 'agent.run']
    assert models and tools and agents
    by_id = {s['context']['span_id']: s for s in spans}
    for span in models + tools + agents:
        assert root['start_time'] <= span['start_time'] <= span['end_time'] <= root['end_time']
        assert runtime[0]['start_time'] <= span['start_time'] <= span['end_time'] <= runtime[0]['end_time']
        cursor = span
        for _ in range(len(spans)):
            if cursor['context']['span_id'] == root['context']['span_id']:
                break
            assert cursor.get('parent_id') in by_id, 'Broken trace ancestry'
            cursor = by_id[cursor['parent_id']]
        else:
            pytest.fail('Trace parent cycle')
    assert all(s['attributes'].get('input.truncated') is False for s in models)
    assert all(s['attributes'].get('llm.token_count.total', 0) > 0 for s in models)
    assert any(config['skill_marker'] in str(s['attributes'].get('input.value', '')) for s in models)


def test_nb_otel_001_unauthorized_trace_without_runtime(config):
    trace_id, response, _content = chat(config, authenticated=False)
    assert response.status_code == 401
    spans = read_trace(config, trace_id, '/nb/v1/chat/run')
    north = [s for s in spans if s['attributes'].get('http.route', '').endswith('/nb/v1/chat/run')]
    assert len(north) == 1
    attrs = north[0]['attributes']
    assert attrs.get('http.status_code', attrs.get('http.response.status_code')) == 401
    assert not any(s['name'].startswith('agent.') or s['attributes'].get('llm.model_name')
                   or '/agent/internal/' in s['attributes'].get('http.route', '') for s in spans)


pytestmark = [pytest.mark.case_id('NB-OTEL-001'), pytest.mark.stage('D3')]


def test_nb_otel_001_disconnect_ends_http_but_keeps_persisted_run(config):
    trace_id = uuid4().hex
    headers = {'Authorization': SecretHeader('Bearer ' + config['northbound_api_key']),
               'traceparent': '00-' + trace_id + '-1111111111111111-01'}
    url = config['northbound_url'].rstrip('/')
    with requests.post(url + '/nb/v1/chat/run', headers=headers, json={
        'agent_name': config['agent_name'], 'query': 'Read the bound skill ' + config['skill_name']
        + ' exactly once and report its actual guide marker.'}, stream=True, timeout=180) as response:
        assert response.status_code == 200
        conversation_id = int(response.headers['conversation_id'])
        # Close after headers without consuming body or stopping the persisted producer.
    spans = read_trace(config, trace_id, '/nb/v1/chat/run')
    assert len([s for s in spans if s['attributes'].get('http.route', '').endswith('/nb/v1/chat/run')]) == 1
    deadline = time.monotonic() + 180
    while True:
        history = requests.get(url + f'/nb/v1/conversations/{conversation_id}', headers={'Authorization': headers['Authorization']}, timeout=15)
        assert history.status_code == 200
        messages = history.json()['data']['history']
        answers = [m['content'] for m in messages if m['role'] == 'assistant']
        if any(config['skill_marker'] in str(answer) for answer in answers):
            break
        assert time.monotonic() < deadline, 'Detached persisted run did not complete'
        time.sleep(2)
    assert len(answers) == 1 and sum(m['role'] == 'user' for m in messages) == 1
