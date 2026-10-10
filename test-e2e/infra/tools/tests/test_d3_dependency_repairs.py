"""Offline negative-detection tests for D3 fixtures, not product acceptance."""
import importlib.util
import json
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))

from shared.asset_registry import AssetDependencyError
from shared.factories import model as model_factory
from shared import memory_mock as fixture
from d3.scenarios import scenario_memory_title_automation_scenarios as memory_scenario


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


section = load('section_negative_repair', 'test-e2e/cases/AGT-010/test.py')
memory_case = load('external_memory_repair', 'test-e2e/cases/AGT-071/test.py')
revision = load('revision_history_repair', 'test-e2e/cases/AGT-AUTO-6A6BC7594487E771/test.py')
server_module = load('external_memory_server_repair', 'test-e2e/infra/mock-services/memory-provider/server.py')


def response(status, body, path='/fixture'):
    return httpx.Response(status, json=body, request=httpx.Request('POST', 'http://fixture' + path))


def test_insert_negative_invalidates_consumed_argument():
    content = 'Answer questions.'
    ranges = section.invalid_ranges(content)
    for bounds in ranges:
        if bounds['mode'] == 'insert':
            assert bounds['start_pos'] < 0 or bounds['start_pos'] > len(content)
        else:
            assert bounds['start_pos'] >= bounds['end_pos']
    assert any(bounds['start_pos'] == -1 for bounds in ranges)


@pytest.mark.parametrize('status,body,after', [
    (200, {'data': {'optimized_content': 'valid result'}}, {'duty_prompt': 'original'}),
    (400, {}, {'duty_prompt': 'original'}),
    (422, {'detail': 'invalid bounds'}, {'duty_prompt': 'changed'}),
    (500, {'message': 'unexpected'}, {'duty_prompt': 'original'}),
])
def test_section_rejection_cannot_pass_false_success_or_partial_write(status, body, after):
    with pytest.raises(AssertionError):
        section.assert_rejected(response(status, body), {'duty_prompt': 'original'}, after)


def test_valid_section_rejection_preserves_draft():
    before = {'duty_prompt': 'original'}
    section.assert_rejected(response(422, {'detail': 'invalid bounds'}), before, dict(before))


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_health', [False, True])
async def test_owned_model_uses_configuration_in_current_tenant_and_cleans_on_failure(monkeypatch, fail_health):
    posts = []

    class API:
        async def post(self, path, **kwargs):
            posts.append((path, kwargs))
            return response(200, {})

        async def get(self, path):
            display = posts[0][1]['json']['display_name']
            return response(200, {'data': [{'display_name': display, 'model_type': 'llm', 'model_id': 19}]})

    @asynccontextmanager
    async def api_client(*args, **kwargs):
        assert kwargs['token'] == 'tenant-b-token'
        yield API()

    monkeypatch.setattr(model_factory, 'client', api_client)
    monkeypatch.setattr(model_factory, 'model_request', lambda kind, display_name: {
        'model_name': 'configured-model', 'model_type': kind, 'api_key': 'fixture-secret',
        'base_url': 'https://fixture.example/v1', 'display_name': display_name})
    monkeypatch.setattr(model_factory, 'configured_model', lambda kind: {'id': 'logical-llm'})
    health, register, state = AsyncMock(), Mock(), Mock()
    if fail_health:
        health.side_effect = AssetDependencyError('models', 'llm', detail='unavailable')
    monkeypatch.setattr(model_factory, 'ensure_model_health', health)
    monkeypatch.setattr(model_factory, 'register_asset', register)
    monkeypatch.setattr(model_factory, 'mark_asset_state', state)
    identity = SimpleNamespace(id='tenant_b_admin', tenant_id='b', access_token='tenant-b-token')
    with pytest.raises(AssetDependencyError if fail_health else AssertionError,
                       match='unavailable' if fail_health else 'product boundary'):
        async with model_factory.owned_configured_model(identity, 'API-095') as model_id:
            assert model_id == 19
            raise AssertionError('product boundary')
    assert posts[0][1]['json']['skip_default_backfill'] is True
    assert posts[0][1]['json']['model_name'] == 'configured-model'
    assert register.call_args.kwargs['cleanup']['identity'] == identity.id
    assert health.await_args.args[0] is identity
    assert posts[-1][0] == '/model/delete'
    assert posts[-1][1]['params']['display_name'] == posts[0][1]['json']['display_name']
    assert state.call_args.args[-1] == 'DELETED'


@pytest.mark.asyncio
async def test_memory_embedding_dependency_fails_before_memory_is_created(monkeypatch):
    health = AsyncMock(side_effect=AssetDependencyError('models', 'embedding', detail='TLS connection reset'))
    create = AsyncMock()
    monkeypatch.setattr(memory_scenario, 'model_id', health)
    monkeypatch.setattr(memory_scenario, '_create_agent_memory', create)
    with pytest.raises(AssetDependencyError, match='TLS connection reset'):
        await memory_scenario._memory_agent_context(SimpleNamespace(), 'core')
    health.assert_awaited_once()
    create.assert_not_awaited()


def test_external_memory_final_answer_not_query_or_tool_echo():
    with pytest.raises(AssertionError, match='Missing actual final answer'):
        memory_case.final_text([{'data': {'type': 'execution_logs', 'content': 'EXTMEM-fixture'}}])
    with pytest.raises(AssertionError, match='runtime error'):
        memory_case.final_text([{'data': {'type': 'error', 'content': 'failure'}},
                                {'data': {'type': 'final_answer', 'content': 'EXTMEM-fixture'}}])
    assert memory_case.final_text([{'data': {'type': 'final_answer', 'content': 'EXTMEM-fixture'}}]) == 'EXTMEM-fixture'


@pytest.mark.parametrize('text', ['', '请确认其他字段是否同步'])
def test_clarification_history_matches_ui_text_not_data_card(text):
    result = {'final_text': text, 'nl2a_payloads': [{'questions': [{'question_id': 'sync_fields'}]}]}
    history = revision.confirmation_history('modify duty', result)
    assert history == [{'role': 'user', 'content': 'modify duty'}, {'role': 'assistant', 'content': text}]
    assert 'sync_fields' not in json.dumps(history), 'Invisible card was injected as assistant prose'


@pytest.mark.asyncio
async def test_memory_control_cleanup_is_scoped_and_uses_actual_plugin_keys():
    credential = 'ephemeral-offline-fixture-credential'
    server = server_module.MemoryServer(('127.0.0.1', 0), credential)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        async with httpx.AsyncClient(base_url=url, headers={'Authorization': 'Token ' + credential,
                                    'X-Org-Id': 'owned'}, trust_env=False) as api:
            mock = fixture.MemoryMock(api, {'plugin': 'mem0', 'endpoint': url, 'api_key': credential}, 'user', 'owned')
            params = mock.provider_params()
            assert params['plugin.base_url'] == url and 'plugin.endpoint' not in params
            assert params['plugin.org_id'] == 'owned'
            mock.provider_params(org='owned-empty')
            payload = {'messages': [{'role': 'user', 'content': 'lookup answer'}], 'user_id': 'user', 'infer': False}
            assert (await api.post('/v3/memories/add/', json=payload)).status_code == 200
            assert (await api.post('/v3/memories/add/', headers={'X-Org-Id': 'foreign'}, json=payload)).status_code == 200
            await mock.fault(503)
            assert (await api.post('/v3/memories/search/', json={'query': 'lookup', 'filters': {'user_id': 'user'}})).status_code == 503
            await mock.cleanup()
            own = await api.post('/v3/memories/search/', json={'query': 'lookup', 'filters': {'user_id': 'user'}})
            other = await api.post('/v3/memories/search/', headers={'X-Org-Id': 'foreign'},
                                   json={'query': 'lookup', 'filters': {'user_id': 'user'}})
            assert own.json()['results'] == []
            assert len(other.json()['results']) == 1, 'Cleanup touched another org'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_memory_conflicting_credentials_do_not_silently_override(monkeypatch):
    monkeypatch.setattr(fixture, 'load_secret_env', lambda: {'NEXENT_EXTERNAL_MEMORY_API_KEY': 'first'})
    monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_PLUGIN', 'mem0')
    monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_ENDPOINT', 'http://fixture')
    monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_API_KEY', 'second')
    with pytest.raises(AssetDependencyError, match='Conflicting'):
        fixture.memory_settings()


@pytest.mark.asyncio
@pytest.mark.parametrize('break_proof', [None, 'echo', 'wire', 'error_code', 'hot_update'])
async def test_external_memory_workflow_requires_each_independent_proof(monkeypatch, break_proof):
    class Mock:
        settings = {'api_key': 'ephemeral-mock-credential'}
        org = 'owned-org'
        count, status, delay = 0, 200, 0

        def provider_params(self, org=None):
            return {'plugin.name': 'mem0', 'plugin.base_url': 'http://fixture',
                    'plugin.api_key': self.settings['api_key'], 'plugin.org_id': org or self.org}

        async def counts(self):
            return {'search': self.count}

        async def fault(self, status=200, delay=0):
            self.status, self.delay = status, delay

    mock = Mock()

    class API:
        marker, local_marker, published = '', '', False

        async def post(self, path, json):
            if path.endswith('/publish'):
                self.published = True
                return response(200, {'version_no': 1})
            if path == '/memory/long-term/user/versions':
                self.local_marker = json['content'].split()[-1]
                return response(201, {'version_id': 25})
            if path == '/memory/providers':
                assert 'plugin.base_url' in json['params'] and 'plugin.endpoint' not in json['params']
                assert json['enabled'] is True
                return response(200, {'provider_config_id': 13})
            if path.endswith('/test-ingest'):
                unit = json['units'][0]
                assert unit['event_type'] == 'memory_stored' and unit['unit_type'] == 'text'
                self.marker = unit['unit_content'].split()[-1]
                return response(200, {'accepted_count': 1, 'rejected_count': 0})
            if path.endswith('/test-search'):
                if mock.status != 200 or mock.delay:
                    return response(400, {'detail': 'controlled Provider error'})
                return response(200, {'items': [{'content': self.marker, 'is_external': True}] if self.marker else []})
            return response(200, {})

        async def put(self, path, json):
            return response(200, {})

        async def get(self, path):
            code = 'timeout' if mock.delay else 'provider_error'
            if break_proof == 'error_code':
                code = 'unknown'
            return response(200, {'timeout_seconds': 2, 'last_error_code': code, 'params': {'plugin.api_key': '***'}})

    api = API()

    @asynccontextmanager
    async def model(*args, **kwargs):
        yield 88

    @asynccontextmanager
    async def agent(*args, **kwargs):
        assert kwargs['model_ids'] == [88]
        yield 77, {'agent_id': 77, 'name': 'owned'}

    async def run(identity, agent_id, query, phase):
        assert api.published, 'Normal memory chat requires the owned published Agent'
        assert api.marker not in query and api.local_marker not in query, 'Answer leaked into input'
        if break_proof != 'wire':
            mock.count += 1
        if phase.startswith('local-'):
            return api.local_marker
        if phase == 'hot-update':
            return api.marker if break_proof == 'hot_update' else 'NOT_FOUND'
        return query if break_proof == 'echo' else api.marker

    monkeypatch.setattr(memory_case, 'owned_configured_model', model)
    monkeypatch.setattr(memory_case, '_draft_agent', agent)
    monkeypatch.setattr(memory_case, 'run_memory_agent', run)
    monkeypatch.setattr(memory_case, 'write_case_evidence', lambda *args, **kwargs: None)
    identity = SimpleNamespace()
    if break_proof:
        with pytest.raises(AssertionError):
            await memory_case.exercise_external_memory(identity, mock, api)
    else:
        await memory_case.exercise_external_memory(identity, mock, api)
        assert mock.status == 200 and mock.delay == 0


@pytest.mark.asyncio
async def test_external_memory_chat_uses_non_debug_runtime(monkeypatch):
    @asynccontextmanager
    async def conversation(*args):
        yield 101

    class API:
        @asynccontextmanager
        async def stream(self, method, path, json):
            assert method == 'POST' and path == '/agent/run'
            assert json['is_debug'] is False
            assert json['agent_id'] == 77 and json['conversation_id'] == 101
            yield response(200, {})

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield API()

    monkeypatch.setattr(memory_case, 'temporary_conversation', conversation)
    monkeypatch.setattr(memory_case, 'client', client)
    monkeypatch.setattr(memory_case, 'read_sse_with_evidence', AsyncMock(return_value=[
        {'data': {'type': 'final_answer', 'content': 'retrieved answer'}}]))
    identity = SimpleNamespace(access_token='fixture', refresh_token=None)
    assert await memory_case.run_memory_agent(identity, 77, 'lookup', 'test') == 'retrieved answer'
