'''D3 API-IT: 外部记忆提供者 test-search/test-ingest 绕过 enabled 开关并回写 last_error_code。

用例 ID: API-AUTO-40529BB837906592（F-178 记忆/外部记忆提供者）

覆盖 backend/apps/memory_provider_app.py:291-416 的连通性测试端点：
- enabled=false 时 test-search/test-ingest 仍真实调用外部提供者（绕过开关）；
- 成功路径清空 last_error_code；
- 失败路径按错误矩阵回写 unauthorized / forbidden；
- 返回结构与前端 ProviderTestPanel 解析约定一致（search: items/count；ingest: accepted_count/rejected_count）。

本地 MemoryBank 兼容 stub 内置于本用例（200/401/403 可切换），不依赖外部
services/test-memory-provider/ 资产。
'''

from __future__ import annotations

import json
import os
import threading
from uuid import uuid4
from shared.mock_network import mock_bind_host, mock_callback_url
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shared.http import assert_status, client, response_message

CASE_ID = 'API-AUTO-40529BB837906592'
PLUGIN_NAME = 'AIDP_Memorybank'


class _MemoryBankStubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self._respond()

    def do_PUT(self) -> None:
        self._respond()

    def _respond(self) -> None:
        mode = getattr(self.server, 'mode', 'ok')
        if mode == 'unauthorized':
            self._send(401, {'error': 'unauthorized'})
        elif mode == 'forbidden':
            self._send(403, {'error': 'forbidden'})
        elif 'Query' in self.path:
            self._send(200, {'value': [{
                'memory_id': 'mem-1',
                'content': 'hello from stub',
                'score': 0.95,
                'memory_type': 'user_message',
                'timestamp': '2026-09-15T00:00:00Z',
            }]})
        else:
            self._send(200, {'ok': True})

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


class _MemoryBankStubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler):
        super().__init__(addr, handler)
        self.mode = 'ok'


@pytest.fixture(scope='module')
def memorybank_stub():
    server = _MemoryBankStubServer((mock_bind_host(), 0), _MemoryBankStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


async def _create_provider(api, stub) -> int:
    host, port = stub.server_address[:2]
    base_url = mock_callback_url(port)
    response = await api.post('/memory/providers', json={
        'provider_name': f'run-{CASE_ID}-{uuid4().hex[:10]}',
        'connection_type': 'plugin',
        'enabled': False,
        'timeout_seconds': 30,
        'params': {
            'plugin.name': PLUGIN_NAME,
            'plugin.base_url': base_url,
            'plugin.api_key': 'test-api-key',
            'plugin.tenant_id': 'test-tenant',
        },
    })
    assert_status(response, 200)
    payload = response.json()
    provider_id = payload.get('provider_config_id')
    assert provider_id is not None, f'create response missing provider_config_id: {payload}'
    return provider_id


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
async def test_provider_test_endpoints_bypass_enabled(tenant_a_admin, memorybank_stub):
    async with client('config', token=tenant_a_admin.access_token) as api:
        provider_id = await _create_provider(api, memorybank_stub)
        try:
            memorybank_stub.mode = 'unauthorized'
            pre = await api.post(
                f'/memory/providers/{provider_id}/test-search',
                json={'query': 'hello', 'top_k': 3},
            )
            assert_status(pre, 400)
            assert 'Provider test-search failed' in response_message(pre)

            memorybank_stub.mode = 'ok'
            search = await api.post(
                f'/memory/providers/{provider_id}/test-search',
                json={'query': 'hello', 'top_k': 3},
            )
            assert_status(search, 200)
            search_body = search.json()
            assert isinstance(search_body.get('items'), list)
            assert search_body.get('count') == len(search_body['items'])

            got = await api.get(f'/memory/providers/{provider_id}')
            assert_status(got, 200)
            assert got.json().get('last_error_code') is None

            ingest = await api.post(
                f'/memory/providers/{provider_id}/test-ingest',
                json={'units': [{
                    'event_id': 'evt-1',
                    'event_type': 'test',
                    'unit_type': 'user_message',
                    'unit_content': 'hello from test',
                }]},
            )
            assert_status(ingest, 200)
            ingest_body = ingest.json()
            assert 'accepted_count' in ingest_body
            assert 'rejected_count' in ingest_body

            memorybank_stub.mode = 'unauthorized'
            unauth = await api.post(
                f'/memory/providers/{provider_id}/test-search',
                json={'query': 'hello', 'top_k': 3},
            )
            assert_status(unauth, 400)
            assert 'Provider test-search failed' in response_message(unauth)
            got = await api.get(f'/memory/providers/{provider_id}')
            assert got.json().get('last_error_code') == 'unauthorized'

            memorybank_stub.mode = 'forbidden'
            forbidden = await api.post(
                f'/memory/providers/{provider_id}/test-search',
                json={'query': 'hello', 'top_k': 3},
            )
            assert_status(forbidden, 400)
            assert 'Provider test-search failed' in response_message(forbidden)
            got = await api.get(f'/memory/providers/{provider_id}')
            assert got.json().get('last_error_code') == 'forbidden'
        finally:
            cleanup = await api.delete(f'/memory/providers/{provider_id}')
            assert_status(cleanup, (200, 404))
