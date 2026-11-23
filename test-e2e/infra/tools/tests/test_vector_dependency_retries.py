"""Offline boundary tests for vector prerequisite retries, not product acceptance."""

from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))

from shared import model_health as health
from shared.asset_registry import AssetDependencyError
from shared.model_selection import MissingConfiguredModelError, select_configured_model


def response(status, body=None, headers=None):
    return httpx.Response(status, json=body, headers=headers,
                          request=httpx.Request('POST', 'http://fixture/model/create'))


def failed_dimension(wrapper='message', name='owned-vector', headers=None):
    return response(409, {wrapper: f"Failed to get embedding dimension for model '{name}'. "
                          'Please verify the URL, API key, and network connection.'}, headers)


@pytest.fixture
def events(monkeypatch):
    events = []
    monkeypatch.setattr(health, 'record', events.append)
    monkeypatch.setattr(health.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(health, 'retry_delay', lambda header, attempt: float(header) if header else 0)
    return events


def model_payload():
    return {'model_type': 'embedding', 'model_name': 'configured-provider-model',
            'display_name': 'owned-vector', 'api_key': 'offline-fixture-credential',
            'base_url': 'https://fixture.test/embeddings', 'skip_default_backfill': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapper', ['message', 'detail'])
async def test_dimension_failure_then_success_retries_only_before_persistence(events, wrapper):
    api = SimpleNamespace(post=AsyncMock(side_effect=[failed_dimension(wrapper), response(200, {})]))
    payload = model_payload()
    assert (await health.create_configured_model_dependency(api, payload, case_id='FIXTURE')).status_code == 200
    assert api.post.await_count == 2
    assert [event['outcome'] for event in events] == ['dimension_probe_failed', 'http_200']
    assert all(call.kwargs['json'] is payload for call in api.post.await_args_list)
    assert payload['skip_default_backfill'] is True
    assert 'offline-fixture-credential' not in json.dumps(events)


@pytest.mark.asyncio
async def test_persistent_dimension_failure_is_blocked_not_pass(events):
    api = SimpleNamespace(post=AsyncMock(side_effect=[failed_dimension()] * 3))
    with pytest.raises(AssetDependencyError, match='before model creation') as caught:
        await health.create_configured_model_dependency(api, model_payload(), case_id='FIXTURE')
    assert caught.value.consumer_case_id == 'FIXTURE'
    assert api.post.await_count == 3
    assert len(events) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [
    (409, {'message': 'Name already in use'}),
    (409, {'message': "Failed to get embedding dimension for model 'different-model'."}),
    (400, {'message': 'invalid configuration'}), (401, {}), (403, {}), (422, {}), (500, {}),
])
async def test_unrelated_errors_remain_failures_and_are_never_retried(events, status, body):
    api = SimpleNamespace(post=AsyncMock(return_value=response(status, body)))
    with pytest.raises(AssertionError):
        await health.create_configured_model_dependency(api, model_payload(), case_id='FIXTURE')
    assert api.post.await_count == 1


@pytest.mark.asyncio
async def test_non_vector_model_does_not_reclassify_dimension_text(events):
    api = SimpleNamespace(post=AsyncMock(return_value=failed_dimension()))
    with pytest.raises(AssertionError):
        await health.create_configured_model_dependency(api, {**model_payload(), 'model_type': 'llm'}, case_id='FIXTURE')
    assert api.post.await_count == 1


@pytest.mark.asyncio
async def test_long_retry_after_is_not_ignored(events):
    api = SimpleNamespace(post=AsyncMock(return_value=failed_dimension(headers={'Retry-After': '60'})))
    with pytest.raises(AssetDependencyError):
        await health.create_configured_model_dependency(api, model_payload(), case_id='FIXTURE')
    assert api.post.await_count == 1
    health.asyncio.sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_write_outcome_is_not_repeated(events):
    api = SimpleNamespace(post=AsyncMock(side_effect=httpx.ReadTimeout('unknown POST outcome')))
    with pytest.raises(httpx.ReadTimeout):
        await health.create_configured_model_dependency(api, model_payload(), case_id='FIXTURE')
    assert api.post.await_count == 1
    assert events[-1]['outcome'] == 'ambiguous_transport_write'


def install_health_fixture(monkeypatch, tmp_path, responses):
    contexts = []

    @asynccontextmanager
    async def fresh_client(*args, **kwargs):
        api = SimpleNamespace()
        contexts.append(api)
        async def post(*args, **kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        api.post = AsyncMock(side_effect=post)
        yield api

    monkeypatch.setattr(health, 'client', fresh_client)
    monkeypatch.setattr(health, 'test_root', lambda: tmp_path)
    monkeypatch.setattr(health, 'fingerprint', lambda *args: 'fixture-health-key')
    monkeypatch.setenv('RESULT_DIR', str(tmp_path / 'results'))
    monkeypatch.setenv('NEXENT_MODEL_HEALTH_TTL', '300')
    return contexts


IDENTITY = SimpleNamespace(access_token='offline-identity', tenant_id='fixture-tenant')
ROW = {'display_name': 'owned-vector', 'model_name': 'configured-provider-model', 'model_type': 'embedding'}


@pytest.mark.asyncio
async def test_health_uses_new_connections_and_recovers_without_false_cache(monkeypatch, tmp_path, events):
    responses = [response(200, {'data': {'connectivity': False}}),
                 httpx.RemoteProtocolError('connection closed'), response(200, {'data': {'connectivity': True}})]
    contexts = install_health_fixture(monkeypatch, tmp_path, responses)
    await health.ensure_model_health(IDENTITY, {}, ROW)
    assert len(contexts) == 3 and len({id(api) for api in contexts}) == 3
    assert [event['outcome'] for event in events] == ['connectivity_false', 'RemoteProtocolError', 'connected']
    assert (tmp_path / 'state/model-health/fixture-health-key.json').is_file()


@pytest.mark.asyncio
async def test_failed_force_recheck_removes_previous_success(monkeypatch, tmp_path, events):
    responses = [response(200, {'data': {'connectivity': True}})]
    contexts = install_health_fixture(monkeypatch, tmp_path, responses)
    await health.ensure_model_health(IDENTITY, {}, ROW)
    responses.extend([response(200, {'data': {'connectivity': False}})] * 3)
    with pytest.raises(AssetDependencyError, match='connectivity_false, connectivity_false, connectivity_false'):
        await health.ensure_model_health(IDENTITY, {}, ROW, force=True)
    assert len(contexts) == 4
    assert not (tmp_path / 'state/model-health/fixture-health-key.json').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(403, {}), (200, {'data': {'connectivity': 'true'}})])
async def test_health_never_accepts_permission_error_or_non_boolean_success(monkeypatch, tmp_path, events, status, body):
    contexts = install_health_fixture(monkeypatch, tmp_path, [response(status, body)] * 3)
    with pytest.raises(AssetDependencyError):
        await health.ensure_model_health(IDENTITY, {}, ROW)
    assert len(contexts) == (1 if status == 403 else 3)
    assert not (tmp_path / 'state/model-health/fixture-health-key.json').exists()


def load_tag_case():
    spec = importlib.util.spec_from_file_location('vector_tag_case', ROOT / 'test-e2e/cases/API-AUTO-551F4FB10B22BB13/test.py')
    case = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(case)
    return case


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['provider health failed', 'multiple matching configured models'])
async def test_health_and_ambiguity_do_not_trigger_temporary_model_creation(monkeypatch, reason):
    case = load_tag_case()
    monkeypatch.setattr(case, 'model_id', AsyncMock(side_effect=AssetDependencyError('models', 'embedding', detail=reason)))
    create = AsyncMock()
    monkeypatch.setattr(case, '_create_embedding_model', create)
    with pytest.raises(AssetDependencyError):
        await case._resolve_embedding_model_id(IDENTITY, 'fixture')
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_genuine_missing_model_is_created_and_registered_without_default_mutation(monkeypatch, events):
    case = load_tag_case()
    monkeypatch.setattr(case, 'model_request', lambda *args, display_name: {**model_payload(), 'display_name': display_name})
    monkeypatch.setattr(case, 'model_id', AsyncMock(side_effect=MissingConfiguredModelError('models', 'embedding')))
    api = SimpleNamespace(post=AsyncMock(return_value=response(200, {})),
                          get=AsyncMock(return_value=response(200, {'data': [
                              {'display_name': 'tagpred-embedding-fixture', 'model_type': 'embedding', 'model_id': 19}]})))

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield api

    monkeypatch.setattr(case, 'client', client)
    register = Mock()
    monkeypatch.setattr(case, 'register_asset', register)
    identity = SimpleNamespace(id='fixture-admin', access_token='fixture-token')
    assert await case._resolve_embedding_model_id(identity, 'fixture') == (19, 'tagpred-embedding-fixture')
    assert api.post.await_args.kwargs['json']['skip_default_backfill'] is True
    assert register.call_args.kwargs['cleanup']['identity'] == identity.id


def test_strict_selector_distinguishes_absence_from_invalid_configuration():
    with pytest.raises(MissingConfiguredModelError):
        select_configured_model({'model': 'fixture-model'}, 'embedding', [])
    with pytest.raises(AssetDependencyError) as caught:
        select_configured_model({}, 'embedding', [])
    assert not isinstance(caught.value, MissingConfiguredModelError)


def test_evidence_has_timestamp_and_no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv('RESULT_DIR', str(tmp_path))
    health.record({'operation': 'dependency_health', 'outcome': 'RemoteProtocolError'})
    item = json.loads((tmp_path / 'runtime/model-health.jsonl').read_text())
    assert item['timestamp'].endswith('+00:00')
    assert item['outcome'] == 'RemoteProtocolError'
