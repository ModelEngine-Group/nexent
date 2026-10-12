"""Owned A2A discovery assets and redacted, read-only Mock observations."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import hashlib
import os
import uuid

import httpx
import jsonschema

from shared.asset_registry import AssetDependencyError, register_asset, mark_asset_state
from shared.config import load_secret_env, load_yaml, repo_root
from shared.http import assert_status, client


class SecretMapping(dict):
    def __repr__(self):
        return '<redacted A2A test credentials>'

    __str__ = __repr__


class A2AMock:
    def __init__(self):
        schema = json.loads((repo_root() / 'test-e2e/infra/config/a2a.schema.json').read_text(encoding='utf-8'))
        try:
            settings = load_yaml('a2a.yaml')
            jsonschema.validate(settings, schema)
        except (OSError, ValueError, jsonschema.ValidationError) as exc:
            raise AssetDependencyError('a2a', 'mock', detail='config/a2a.yaml must match the maintained Schema') from exc
        self.settings = settings['mock']
        key = self.settings['control_token_env_key']
        token = os.environ.get(key) or load_secret_env().get(key)
        if not token:
            raise AssetDependencyError('a2a', 'mock', detail='configured control token is missing')
        self.control = httpx.AsyncClient(base_url=self.settings['control_url'], trust_env=False,
                                        headers={'X-A2A-Control-Token': token}, timeout=30)

    async def close(self):
        await self.control.aclose()

    async def ready(self):
        response = await self.control.get('/readyz')
        if response.status_code != 200 or response.json().get('status') != 'ready':
            raise AssetDependencyError('a2a', 'mock', detail='controlled A2A stack is not READY')
        response = await self.control.get('/__test/scenario')
        assert_status(response, 200)
        assert response.json()['current'] == 'happy-jsonrpc', 'Mock has an outstanding fault injection'

    def card_url(self, nonce, profile='basic'):
        return f"{self.settings['product_url'].rstrip('/')}/{profile}/.well-known/agent-card.json?test_run={nonce}"

    async def auth_fixture(self, profile, mode):
        response = await self.control.get('/__test/auth-fixture', params={'agent': profile, 'mode': mode})
        assert_status(response, 200)
        fixture = SecretMapping({key: SecretMapping(value) if isinstance(value, dict) else value
                                 for key, value in response.json().items()})
        fixture['header_fingerprints'] = {
            key.lower(): hashlib.sha256(value.encode()).hexdigest()[:16]
            for key, value in fixture['discovery_headers'].items()
        }
        return fixture

    async def nacos_fixture(self):
        response = await self.control.get('/__test/nacos-fixture')
        assert_status(response, 200)
        return SecretMapping(response.json())

    @asynccontextmanager
    async def nacos_latency(self, nonce):
        control_url = self.settings.get('fault_proxy_control_url')
        if not control_url or not self.settings.get('nacos_proxy_product_url'):
            raise AssetDependencyError('a2a', 'mock', detail='declared Nacos fault proxy configuration is missing')
        path = '/proxies/nacos-a2a/toxics'
        async with httpx.AsyncClient(base_url=control_url, trust_env=False, timeout=15) as proxy:
            existing = await proxy.get(path)
            assert_status(existing, 200)
            assert existing.json() == [], 'Do not overwrite another batch fault'
            try:
                injected = await proxy.post(path, json={
                    'name': nonce, 'type': 'latency', 'stream': 'downstream',
                    'toxicity': 1.0, 'attributes': {'latency': 40000, 'jitter': 0},
                })
                assert_status(injected, 200)
                yield
            finally:
                assert_status(await proxy.delete(f'{path}/{nonce}'), (204, 404))
                remaining = await proxy.get(path)
                assert_status(remaining, 200)
                assert not any(row['name'] == nonce for row in remaining.json())

    @asynccontextmanager
    async def fault(self, name):
        response = await self.control.get('/__test/scenario')
        assert_status(response, 200)
        previous = response.json()['current']
        assert previous == 'happy-jsonrpc', 'Do not overwrite another batch fault'
        try:
            assert_status(await self.control.post('/__test/scenario', json={'name': name}), 200)
            yield
        finally:
            assert_status(await self.control.post('/__test/scenario', json={'name': previous}), 200)
            response = await self.control.get('/__test/scenario')
            assert_status(response, 200)
            assert response.json()['current'] == previous

    async def observations(self, nonce):
        response = await self.control.get('/__test/observations')
        assert_status(response, 200)
        digest = hashlib.sha256(json.dumps({'test_run': nonce}, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        rows = [row for row in response.json()['items']
                if row.get('headers', {}).get('x-nexent-test-run') == nonce
                or row.get('payload_summary', {}).get('metadata_sha256') == digest]
        evidence = os.environ.get('RESULT_DIR')
        if evidence:
            from pathlib import Path
            target = Path(evidence) / 'a2a-wire'
            target.mkdir(parents=True, exist_ok=True)
            (target / f'{nonce}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        return rows


@asynccontextmanager
async def mock_asset():
    mock = A2AMock()
    try:
        await mock.ready()
        yield mock
    finally:
        await mock.close()


@asynccontextmanager
async def nacos_config(identity, mock, case_id, *, through_proxy=False):
    fixture = await mock.nacos_fixture()
    nonce = f'{case_id}-{uuid.uuid4().hex}'
    payload = SecretMapping({key: fixture[key] for key in (
        'nacos_addr', 'nacos_username', 'nacos_password', 'namespace_id')})
    payload['name'] = nonce
    if through_proxy:
        address = mock.settings.get('nacos_proxy_product_url')
        if not address:
            raise AssetDependencyError('a2a', 'mock', detail='Nacos proxy product URL is missing')
        payload['nacos_addr'] = address
    owned_agents = set()
    async with client('config', token=identity.access_token, timeout=90) as api:
        created = await api.post('/a2a/client/nacos-configs', json=payload)
        assert_status(created, 200)
        config_id = created.json()['data']['config_id']
        try:
            register_asset('owned_nacos', config_id, config_id, owner_case_id=case_id,
                           cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                    'path': f'/a2a/client/nacos-configs/{config_id}', 'allowed_statuses': [200, 404]})

            async def discover():
                response = await api.post('/a2a/client/discover/nacos', json={
                    'nacos_config_id': config_id, 'agent_names': [fixture['agent_name']],
                    'namespace': fixture['namespace_id'],
                })
                if response.status_code == 200:
                    for row in response.json()['data']:
                        agent_id = int(row.get('id') or row.get('external_agent_id') or 0)
                        assert agent_id > 0
                        owned_agents.add(agent_id)
                        register_asset('owned_a2a', str(agent_id), agent_id, owner_case_id=case_id,
                                       cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                                'path': f'/a2a/client/agents/{agent_id}', 'allowed_statuses': [200, 404]})
                return response

            yield api, config_id, nonce, discover
        finally:
            for agent_id in owned_agents:
                assert_status(await api.delete(f'/a2a/client/agents/{agent_id}'), (200, 404))
                assert_status(await api.get(f'/a2a/client/agents/{agent_id}'), 404)
                mark_asset_state('owned_a2a', str(agent_id), 'DELETED')
            assert_status(await api.delete(f'/a2a/client/nacos-configs/{config_id}'), (200, 404))
            assert_status(await api.get(f'/a2a/client/nacos-configs/{config_id}'), 404)
            mark_asset_state('owned_nacos', config_id, 'DELETED')


@asynccontextmanager
async def discovered_agent(identity, mock, case_id, *, profile='basic', auth=None, timeout=30):
    nonce = f'{case_id}-{uuid.uuid4().hex}'
    source_url = mock.card_url(nonce, profile)
    headers = SecretMapping(auth['discovery_headers'] if auth else {})
    headers['X-Nexent-Test-Run'] = nonce
    async with client('config', token=identity.access_token, timeout=timeout) as api:
        # Use a unique source URL, not a shared Mock name, to own the DB row.
        response = await api.post('/a2a/client/discover/url', json={
            'url': source_url, 'custom_headers': headers,
        })
        assert_status(response, 200)
        row = response.json()['data']
        agent_id = int(row.get('id') or row.get('external_agent_id') or 0)
        assert agent_id > 0, 'discovery must return a dynamic external Agent ID'
        try:
            register_asset('owned_a2a', str(agent_id), agent_id, owner_case_id=case_id,
                           cleanup={'service': 'config', 'identity': identity.id,
                                    'method': 'DELETE', 'path': f'/a2a/client/agents/{agent_id}',
                                    'allowed_statuses': [200, 404]},
                           metadata={'source_url': source_url, 'cleanup_identity': identity.id})
            detail = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(detail, 200)
            assert detail.json()['data']['source_url'] == source_url
            yield api, agent_id, nonce
        finally:
            deleted = await api.delete(f'/a2a/client/agents/{agent_id}')
            assert_status(deleted, (200, 404))
            absent = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(absent, 404)
            mark_asset_state('owned_a2a', str(agent_id), 'DELETED')
