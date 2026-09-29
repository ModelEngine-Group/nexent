from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from shared.config import load_secret_env
from shared.http import assert_status, client
from shared.mock_network import mock_bind_host, mock_callback_url


CASE_ID = 'CTR-AUTO-9ACCCB74F6E72CCC'

_AIDP_PLUGIN_NAME = 'aidp_mem_plugin'
_MEM0_PLUGIN_NAME = 'mem0'


def _expected_mask(value):
    if len(value) <= 8:
        return '***'
    return f'{value[:3]}***{value[-4:]}'


def _read_api_key(provider):
    env = load_secret_env()
    candidates = {
        _AIDP_PLUGIN_NAME: ('MEMORY_PROVIDER_AIDP_API_KEY', 'AIDP_MEMORY_PROVIDER_API_KEY', 'AIDP_API_KEY'),
        _MEM0_PLUGIN_NAME: ('MEMORY_PROVIDER_MEM0_API_KEY', 'MEM0_API_KEY'),
    }
    for key in candidates[provider]:
        value = (env.get(key) or '').strip()
        if value:
            return value
    raise RuntimeError(
        f'config/secrets.env must provide an api_key for {provider!r} '
        f'(one of {candidates[provider]!r})'
    )


class MemoryProviderStub:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = []
        self.force_status = None
        self.event_status = 'SUCCEEDED'
        self._event_counter = 0
        self.aidp_search_results = [
            {
                'memory_id': 'aidp-mem-1',
                'content': 'aidp memory content',
                'score': 0.81,
                'memory_type': 'long_term',
                'timestamp': '2026-09-15T00:00:00Z',
            }
        ]
        self.mem0_search_results = [
            {
                'id': 'mem0-mem-1',
                'memory': 'mem0 memory content',
                'score': 0.77,
                'metadata': {'kind': 'test'},
            }
        ]

        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def _read_body(self):
                length = int(self.headers.get('Content-Length') or 0)
                return self.rfile.read(length) if length else b''

            def _capture(self, body):
                entry = {
                    'method': self.command,
                    'path': self.path,
                    'headers': {k: v for k, v in self.headers.items()},
                    'body': body.decode('utf-8', 'replace'),
                }
                with stub._lock:
                    stub._requests.append(entry)

            def _reply(self, status, payload):
                data = json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _forced(self):
                if stub.force_status is not None:
                    self._reply(stub.force_status, {'detail': 'forced upstream failure'})
                    return True
                return False

            def do_POST(self):
                body = self._read_body()
                self._capture(body)
                if self._forced():
                    return
                path = urlparse(self.path).path
                if path.endswith('/Memories/Query'):
                    self._reply(200, {'value': stub.aidp_search_results})
                elif path.endswith('/v3/memories/search/'):
                    self._reply(200, {'results': stub.mem0_search_results})
                elif path.endswith('/v3/memories/add/'):
                    with stub._lock:
                        stub._event_counter += 1
                        event_id = f'evt-{stub._event_counter}'
                    self._reply(200, {'event_id': event_id})
                else:
                    self._reply(200, {})

            def do_PUT(self):
                body = self._read_body()
                self._capture(body)
                if self._forced():
                    return
                self._reply(200, {'status': 'ok'})

            def do_GET(self):
                body = self._read_body()
                self._capture(body)
                if self._forced():
                    return
                self._reply(200, {'status': stub.event_status})

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer((mock_bind_host(), 0), Handler)
        try:
            self.base_url = mock_callback_url(self._server.server_address[1])
        except Exception:
            self._server.server_close()
            raise
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def clear(self):
        with self._lock:
            self._requests.clear()

    def requests(self):
        with self._lock:
            return list(self._requests)

    def captured(self, method=None, contains=None):
        out = []
        for entry in self.requests():
            if method is not None and entry['method'] != method:
                continue
            if contains is not None and contains not in entry['path']:
                continue
            out.append(entry)
        return out

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_memory_provider_wire_contract(tenant_a_admin):
    identity = tenant_a_admin
    run_id = f'{CASE_ID.lower()}-{uuid.uuid4().hex[:12]}'
    aidp_key = _read_api_key(_AIDP_PLUGIN_NAME)
    mem0_key = _read_api_key(_MEM0_PLUGIN_NAME)
    org_id = f'org-{run_id}'

    stub = MemoryProviderStub()
    created_ids = []

    unit_one = {
        'event_id': f'evt-{run_id}-1',
        'event_type': 'model_output',
        'unit_type': 'model_output',
        'unit_content': 'memory content one',
    }
    unit_two = {
        'event_id': f'evt-{run_id}-2',
        'event_type': 'model_output',
        'unit_type': 'model_output',
        'unit_content': 'memory content two',
    }

    try:
        async with client('config', token=identity.access_token) as api:
            try:
                aidp_name = f'aidp-{run_id}'
                mem0_name = f'mem0-{run_id}'

                create_aidp = await api.post('/memory/providers', json={
                    'provider_name': aidp_name,
                    'connection_type': 'plugin',
                    'enabled': False,
                    'timeout_seconds': 10,
                    'params': {
                        'plugin.name': _AIDP_PLUGIN_NAME,
                        'plugin.api_key': aidp_key,
                        'plugin.base_url': stub.base_url,
                        'plugin.tenant_id': f'tenant-{run_id}',
                        'plugin.instance_name': f'inst-{run_id}',
                    },
                })
                assert_status(create_aidp, 200)
                aidp = create_aidp.json()
                aidp_id = int(aidp['provider_config_id'])
                created_ids.append(aidp_id)
                assert aidp['params']['plugin.api_key'] == _expected_mask(aidp_key)
                assert aidp['params']['plugin.base_url'] == stub.base_url
                assert aidp_key not in json.dumps(aidp)

                create_mem0 = await api.post('/memory/providers', json={
                    'provider_name': mem0_name,
                    'connection_type': 'plugin',
                    'enabled': False,
                    'timeout_seconds': 10,
                    'params': {
                        'plugin.name': _MEM0_PLUGIN_NAME,
                        'plugin.api_key': mem0_key,
                        'plugin.base_url': stub.base_url,
                        'plugin.org_id': org_id,
                    },
                })
                assert_status(create_mem0, 200)
                mem0 = create_mem0.json()
                mem0_id = int(mem0['provider_config_id'])
                created_ids.append(mem0_id)
                assert mem0['params']['plugin.api_key'] == _expected_mask(mem0_key)
                assert mem0_key not in json.dumps(mem0)

                stub.clear()
                s = await api.post(f'/memory/providers/{aidp_id}/test-search', json={'query': 'what did we do', 'top_k': 3})
                assert_status(s, 200)
                search_body = s.json()
                assert search_body['count'] == 1
                item = search_body['items'][0]
                assert item['external_id'] == 'aidp-mem-1'
                assert item['content'] == 'aidp memory content'
                assert item['source'] == 'unifiedmemory'
                assert item['is_external'] is True
                assert item['score'] == 0.81
                q_entries = stub.captured(method='POST', contains='/Memories/Query')
                assert len(q_entries) == 1
                q = q_entries[0]
                assert q['path'].endswith('/Instances/inst-' + run_id + '/Memories/Query')
                assert f'Tenants/tenant-{run_id}' in q['path']
                assert q['headers'].get('Authorization') == f'Bearer {aidp_key}'
                qbody = json.loads(q['body'])
                assert qbody['query'] == 'what did we do'
                assert qbody['top_k'] == 3
                assert qbody['threshold'] == 0
                assert qbody['rerank'] is False

                stub.clear()
                i = await api.post(f'/memory/providers/{aidp_id}/test-ingest', json={'units': [unit_one, unit_two]})
                assert_status(i, 200)
                ingest_body = i.json()
                assert ingest_body['status'] == 'ok'
                assert ingest_body['accepted_count'] == 2
                assert ingest_body['rejected_count'] == 0
                assert ingest_body['provider'] == 'unifiedmemory'
                put_entries = stub.captured(method='PUT', contains='/Memories')
                assert len(put_entries) == 1
                put = put_entries[0]
                assert put['headers'].get('Authorization') == f'Bearer {aidp_key}'
                pbody = json.loads(put['body'])
                assert pbody['messages'] == [
                    {'role': 'user', 'content': 'memory content one'},
                    {'role': 'user', 'content': 'memory content two'},
                ]
                assert 'timestamp' in pbody

                stub.clear()
                s = await api.post(f'/memory/providers/{mem0_id}/test-search', json={'query': 'find mem0', 'top_k': 4})
                assert_status(s, 200)
                search_body = s.json()
                assert search_body['count'] == 1
                item = search_body['items'][0]
                assert item['external_id'] == 'mem0-mem-1'
                assert item['content'] == 'mem0 memory content'
                assert item['source'] == 'mem0'
                assert item['is_external'] is True
                assert item['score'] == 0.77
                entries = stub.captured(method='POST', contains='/v3/memories/search/')
                assert len(entries) == 1
                e = entries[0]
                assert e['headers'].get('Authorization') == f'Token {mem0_key}'
                assert e['headers'].get('X-Org-Id') == org_id
                ebody = json.loads(e['body'])
                assert ebody['query'] == 'find mem0'
                assert ebody['top_k'] == 4
                assert ebody['threshold'] == 0.0
                filters = ebody['filters']
                assert isinstance(filters, dict)
                assert set(filters.keys()) == {'user_id'}
                assert isinstance(filters['user_id'], str) and bool(filters['user_id'])

                stub.clear()
                i = await api.post(f'/memory/providers/{mem0_id}/test-ingest', json={'units': [unit_one, unit_two]})
                assert_status(i, 200)
                ingest_body = i.json()
                assert ingest_body['status'] == 'ok'
                assert ingest_body['accepted_count'] == 2
                assert ingest_body['rejected_count'] == 0
                add_entries = stub.captured(method='POST', contains='/v3/memories/add/')
                assert len(add_entries) == 2
                for entry, unit in zip(add_entries, [unit_one, unit_two]):
                    assert entry['headers'].get('Authorization') == f'Token {mem0_key}'
                    abody = json.loads(entry['body'])
                    assert abody['messages'] == [{'role': 'user', 'content': unit['unit_content']}]
                    assert abody['infer'] is False
                    assert isinstance(abody['user_id'], str) and bool(abody['user_id'])
                    assert abody['metadata']['event_id'] == unit['event_id']
                    assert abody['metadata']['event_type'] == unit['event_type']
                    assert abody['metadata']['unit_type'] == unit['unit_type']
                event_gets = stub.captured(method='GET', contains='/v1/event/')
                assert len(event_gets) == 2

                stub.clear()
                stub.event_status = 'FAILED'
                i = await api.post(f'/memory/providers/{mem0_id}/test-ingest', json={'units': [unit_one]})
                assert_status(i, 200)
                ingest_body = i.json()
                assert ingest_body['status'] == 'error'
                assert ingest_body['accepted_count'] == 0
                assert ingest_body['rejected_count'] == 1
                assert len(stub.captured(method='GET', contains='/v1/event/')) == 1
                stub.event_status = 'SUCCEEDED'

                error_cases = [(401, 'unauthorized'), (403, 'forbidden'), (429, 'rate_limited'), (500, 'provider_error')]
                for provider_id, key in ((aidp_id, aidp_key), (mem0_id, mem0_key)):
                    for status_code, expected in error_cases:
                        stub.force_status = status_code
                        r = await api.post(f'/memory/providers/{provider_id}/test-search', json={'query': 'x', 'top_k': 2})
                        assert_status(r, 400)
                        detail = str(r.json().get('detail') or '')
                        assert 'failed' in detail.lower()
                        assert key not in detail
                        g = await api.get(f'/memory/providers/{provider_id}')
                        assert_status(g, 200)
                        assert g.json()['last_error_code'] == expected
                        stub.force_status = None

                for provider_id, key in ((aidp_id, aidp_key), (mem0_id, mem0_key)):
                    for status_code, _ in error_cases:
                        stub.force_status = status_code
                        r = await api.post(f'/memory/providers/{provider_id}/test-ingest', json={'units': [unit_one]})
                        assert_status(r, 200)
                        body = r.json()
                        assert body['status'] == 'error'
                        assert body['accepted_count'] == 0
                        assert body['rejected_count'] == 1
                        assert key not in json.dumps(body)
                        stub.force_status = None

                r = await api.post(f'/memory/providers/{aidp_id}/test-search', json={'query': 'clear', 'top_k': 2})
                assert_status(r, 200)
                g = await api.get(f'/memory/providers/{aidp_id}')
                assert_status(g, 200)
                assert g.json()['last_error_code'] is None
            finally:
                for pid in created_ids:
                    try:
                        await api.delete(f'/memory/providers/{pid}')
                    except Exception:
                        pass
    finally:
        stub.shutdown()
