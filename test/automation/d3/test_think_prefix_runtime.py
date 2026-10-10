"""TPC-D3-001: deployed parsing, real skill execution, SSE and persistence.

NEXENT_TEST_CREDENTIALS points to a private JSON created by deployment setup.
The controlled provider replaces only generation; the skill and executor are real.
"""
import json
import os
from pathlib import Path

import pytest
import requests

CODE = '<code>skill_content = read_skill_md(skill_name="tpc-quality-check")\nprint(skill_content)</code>'
FINAL = 'TPC_SKILL_READ_OK'
SKILL_MARKER = 'TPC_REAL_SKILL_CONTENT'
PREFIXES = ['</think>', '<think>unfinished thought', '<think>reasoning</think> Read the guide now.']


def config():
    return json.loads(Path(os.environ['NEXENT_TEST_CREDENTIALS']).read_text())


def request(cfg, method, path, body=None, *, provider=False):
    base = cfg['provider'] if provider else cfg['runtime']
    headers = {} if provider else {'Authorization': 'Bearer ' + cfg['token']}
    response = requests.request(method, base + path, json=body, headers=headers, timeout=150)
    assert response.status_code < 400, f'{method} {path}: HTTP {response.status_code}'
    return response.json()


def run_agent(cfg, conversation_id):
    response = requests.post(cfg['runtime'] + '/agent/run', json={
        'query': 'Read tpc-quality-check once. After its guide is in observations, finish with exactly '
                 '<final_answer>' + FINAL + '</final_answer>. Do not call a final_answer Python function.',
        'conversation_id': conversation_id, 'history': [], 'agent_id': cfg['agent_id'], 'is_debug': False,
    }, headers={'Authorization': 'Bearer ' + cfg['token'], 'Accept-Language': 'en'}, timeout=150)
    assert response.status_code == 200
    return [json.loads(line[5:].strip()) for line in response.text.splitlines()
            if line.startswith('data:') and line[5:].strip() != '[DONE]']


def units(history):
    return [unit for conversation in history['data'] for message in conversation['message']
            if isinstance(message.get('message'), list) for unit in message['message']]


@pytest.mark.parametrize('prefix,repairs', [(prefix, 0) for prefix in PREFIXES] + [(PREFIXES[0], 2)])
def test_tpc_d3_001_skill_executes_once_and_history_matches(prefix, repairs, tmp_path):
    cfg = config()
    responses = ['<code>broken(</code>'] * repairs + [prefix + CODE, '</think><final_answer>' + FINAL + '</final_answer>']
    request(cfg, 'POST', '/__control', {'responses': responses}, provider=True)
    cid = request(cfg, 'PUT', '/conversation/create', {'title': 'TPC skill execution regression'})['data']['conversation_id']
    try:
        events = run_agent(cfg, cid)
        history = request(cfg, 'GET', f'/conversation/{cid}')
        persisted = units(history)
        stats = request(cfg, 'GET', '/__stats', provider=True)
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f'tpc-{PREFIXES.index(prefix)}-{repairs}.json').write_text(json.dumps({
            'case_id': 'TPC-D3-001', 'conversation_id': cid, 'prefix': prefix, 'repairs': repairs,
            'events': events, 'history': history, 'provider': stats,
        }, ensure_ascii=False, indent=2))
        for sequence in (events, persisted):
            assert [e['content'] for e in sequence if e.get('type') == 'final_answer'] == [FINAL]
            assert sum(e.get('type') == 'parse' for e in sequence) == 1
            logs = [e for e in sequence if e.get('type') == 'execution_logs' and SKILL_MARKER in str(e.get('content'))]
            assert len(logs) == 1, 'Real skill body must appear in exactly one executed action'
        assert stats['request_count'] == repairs + 2
        assert not any(e.get('type') == 'error' for e in events)
    finally:
        request(cfg, 'DELETE', f'/conversation/{cid}')


def test_tpc_d3_001_marked_exhaustion_never_executes_or_finalizes(tmp_path):
    cfg = config()
    rejected = '</think><code>read_skill_md('
    request(cfg, 'POST', '/__control', {'responses': [rejected]}, provider=True)
    cid = request(cfg, 'PUT', '/conversation/create', {'title': 'TPC malformed exhaustion regression'})['data']['conversation_id']
    try:
        events = run_agent(cfg, cid)
        history = request(cfg, 'GET', f'/conversation/{cid}')
        stats = request(cfg, 'GET', '/__stats', provider=True)
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'tpc-rejected.json').write_text(json.dumps({'events': events, 'history': history,
             'provider': stats, 'conversation_id': cid}, ensure_ascii=False, indent=2))
        for sequence in (events, units(history)):
            assert not any(e.get('type') == 'parse' for e in sequence)
            # The runtime emits an empty log reset before generation. Only
            # nonempty logs would be evidence of an executed action here.
            assert all(str(e.get('content', '')).strip() in {'', '[]'}
                       for e in sequence if e.get('type') == 'execution_logs')
            assert not any(e.get('type') == 'final_answer' and rejected in str(e.get('content')) for e in sequence)
        assert stats['request_count'] == 3
    finally:
        request(cfg, 'DELETE', f'/conversation/{cid}')


def test_tpc_d3_001_real_model_reads_skill(tmp_path):
    """Real Smoke: configured live model, separate from injected-prefix assertions."""
    cfg = config()
    cfg['agent_id'] = cfg['real_agent_id']
    cid = request(cfg, 'PUT', '/conversation/create', {'title': 'TPC real model skill smoke'})['data']['conversation_id']
    try:
        events = run_agent(cfg, cid)
        history = request(cfg, 'GET', f'/conversation/{cid}')
        evidence = Path(os.environ.get('NEXENT_TEST_ARTIFACT_DIR', tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'tpc-real-smoke.json').write_text(json.dumps({'profile': 'real_smoke',
            'conversation_id': cid, 'model': cfg['real_model_name'], 'events': events,
            'history': history}, ensure_ascii=False, indent=2))
        for sequence in (events, units(history)):
            answers = [e['content'] for e in sequence if e.get('type') == 'final_answer']
            assert answers == [FINAL], answers
            assert any(e.get('type') == 'parse' and 'read_skill_md' in str(e.get('content')) for e in sequence)
            assert any(e.get('type') == 'execution_logs' and SKILL_MARKER in str(e.get('content')) for e in sequence)
        assert not any(e.get('type') == 'error' for e in events)
    finally:
        request(cfg, 'DELETE', f'/conversation/{cid}')
