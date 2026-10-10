"""CMSR-D3-001: deployed Agent attempts stream, commit and persist atomically."""

import json
import os
import threading
import time
from pathlib import Path

import pytest
import requests


def _request(config, method, path, body=None, *, provider=False):
    base = config['provider'] if provider else config['runtime']
    headers = {} if provider else {'Authorization': 'Bearer ' + config['token']}
    response = requests.request(method, base + path, json=body, headers=headers, timeout=30)
    assert response.status_code < 400, f'{method} {path}: HTTP {response.status_code}'
    return response.json()


def _config():
    path = Path(os.environ['NEXENT_TEST_CREDENTIALS'])
    return json.loads(path.read_text())


def _units(history):
    return [unit for conversation in history['data'] for message in conversation['message']
            if isinstance(message.get('message'), list) for unit in message['message']]


@pytest.mark.parametrize('scenario', ['partial_then_success', 'invalid_then_success'])
def test_cmsr_d3_001_deployed_retry_streams_and_persists(scenario, tmp_path):
    config = _config()
    marker = 'CMSR_DEPLOYED_REPAIR_OK'
    _request(config, 'POST', '/__control', {
        'scenario': scenario, 'response_protocol': 'code_then_final',
        'response_text': marker, 'pause_after_success_chunks': 4,
    }, provider=True)
    conversation = _request(config, 'PUT', '/conversation/create', {'title': 'CMSR deployment regression'})
    conversation_id = conversation['data']['conversation_id']
    events = []
    outcome = {}

    def run():
        try:
            response = requests.post(config['runtime'] + '/agent/run', json={
                'query': 'Reply with exactly ' + marker, 'conversation_id': conversation_id,
                'history': [], 'agent_id': config['agent_id'], 'is_debug': False,
            }, headers={'Authorization': 'Bearer ' + config['token'], 'Accept-Language': 'en'},
                stream=True, timeout=(30, 120))
            assert response.status_code == 200, f'Agent HTTP {response.status_code}'
            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                if line and line.startswith('data:'):
                    payload = line[5:].strip()
                    if payload != '[DONE]':
                        events.append(json.loads(payload))
            outcome['completed'] = True
        except BaseException as error:
            outcome['error'] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 45
        paused = None
        while time.monotonic() < deadline:
            if 'error' in outcome:
                raise outcome['error']
            stats = _request(config, 'GET', '/__stats', provider=True)
            model_text = ''.join(str(e.get('content', '')) for e in events
                                 if str(e.get('type', '')).startswith('model_output_'))
            if stats['success_stream_paused'] and '<code>print(' in model_text:
                paused = list(events)
                break
            time.sleep(0.1)
        assert paused, f'No successful safe delta before completion; event types: {[e.get("type") for e in events]}'
        controls = [e for e in paused if e.get('type') == 'model_attempt_control']
        assert [e['phase'] for e in controls] == ['begin', 'rollback', 'begin']
        assert paused[0]['type'] == 'step_count' or next(
            i for i, e in enumerate(paused) if e.get('type') == 'step_count'
        ) < next(i for i, e in enumerate(paused) if e.get('phase') == 'begin')
        assert sum(e.get('type') == 'step_count' for e in paused) == 1
        assert not outcome.get('completed')
        _request(config, 'POST', '/__release', {}, provider=True)
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert 'error' not in outcome, str(outcome.get('error'))
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / (scenario + '-observed.json')).write_text(json.dumps(events, ensure_ascii=False, indent=2))
        controls = [e for e in events if e.get('type') == 'model_attempt_control']
        assert [e['phase'] for e in controls] == ['begin', 'rollback', 'begin', 'commit', 'begin', 'rollback']
        assert sum(e.get('type') == 'parse' for e in events) == 1
        answers = [e for e in events if e.get('type') == 'final_answer']
        assert len(answers) == 1 and answers[0]['content'] == marker
        assert sum(e.get('type') == 'step_count' for e in events) == 2
        stats = _request(config, 'GET', '/__stats', provider=True)
        # Third request is the normal final envelope after one executable action.
        assert stats['request_count'] == 3
        history = _request(config, 'GET', f'/conversation/{conversation_id}')
        units = _units(history)
        raw = ''.join(str(u.get('content', '')) for u in units)
        assert '<code>print(' in raw and marker in raw
        assert 'CMSR_LEAK_' not in raw and 'INVALID_SEMANTIC_FIRST' not in raw
        assert sum(u.get('type') == 'parse' for u in units) == 1
        assert sum(u.get('type') == 'final_answer' for u in units) == 1
        assert sum(u.get('type') == 'step_count' for u in units) == 2
        assert not any(u.get('type') == 'model_attempt_control' for u in units)
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / (scenario + '.json')).write_text(json.dumps({
            'case_id': 'CMSR-D3-001', 'scenario': scenario, 'conversation_id': conversation_id,
            'paused_events': paused, 'events': events, 'history': history, 'provider': stats,
        }, ensure_ascii=False, indent=2))
    finally:
        _request(config, 'POST', '/__release', {}, provider=True)
        thread.join(timeout=10)
        _request(config, 'DELETE', f'/conversation/{conversation_id}')


def test_cmsr_deployed_truncated_repairs_never_execute(tmp_path):
    """Deployment error path: rejected truncated actions never execute or persist."""
    config = _config()
    _request(config, 'POST', '/__control', {
        'scenario': 'length', 'response_protocol': 'code_action', 'response_text': 'TRUNCATED_ACTION_MUST_NOT_RUN',
    }, provider=True)
    conversation = _request(config, 'PUT', '/conversation/create', {'title': 'CMSR rejected repair regression'})
    conversation_id = conversation['data']['conversation_id']
    try:
        response = requests.post(config['runtime'] + '/agent/run', json={
            'query': 'Reply with exactly TRUNCATED_ACTION_MUST_NOT_RUN', 'conversation_id': conversation_id,
            'history': [], 'agent_id': config['agent_id'], 'is_debug': False,
        }, headers={'Authorization': 'Bearer ' + config['token'], 'Accept-Language': 'en'}, timeout=120)
        assert response.status_code == 200
        events = [json.loads(line[5:].strip()) for line in response.text.splitlines()
                  if line.startswith('data:') and line[5:].strip() != '[DONE]']
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'truncated-observed.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
        controls = [e for e in events if e.get('type') == 'model_attempt_control']
        assert [e['phase'] for e in controls] == ['begin', 'rollback'] * 3
        assert not any(e.get('type') in {'parse', 'tool', 'tool-call'} for e in events)
        assert sum(e.get('type') == 'step_count' for e in events) == 1
        stats = _request(config, 'GET', '/__stats', provider=True)
        assert stats['request_count'] == 3
        history = _request(config, 'GET', f'/conversation/{conversation_id}')
        units = _units(history)
        assert not any(u.get('type', '').startswith('model_output_') for u in units)
        assert not any(u.get('type') in {'parse', 'tool', 'tool-call'} for u in units)
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'truncated-repairs.json').write_text(json.dumps({
            'scenario': 'length', 'conversation_id': conversation_id, 'events': events,
            'history': history, 'provider': stats,
        }, ensure_ascii=False, indent=2))
    finally:
        _request(config, 'DELETE', f'/conversation/{conversation_id}')
