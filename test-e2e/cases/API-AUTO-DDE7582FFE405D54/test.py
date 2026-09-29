from __future__ import annotations

import uuid
from typing import Any

import pytest

from shared.asset_registry import AssetDependencyError, mark_asset_state, register_asset
from shared.http import assert_status, client

CASE_ID = 'API-AUTO-DDE7582FFE405D54'
NO_MODEL_DETAIL = 'No available model for regeneration. Please configure an LLM model first.'


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _find_int(data: Any, keys: set[str]) -> int | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys:
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
        for value in data.values():
            found = _find_int(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_int(value, keys)
            if found is not None:
                return found
    return None


async def _create_agent(api, name: str, identity, display_name: str | None = None) -> int:
    payload: dict[str, Any] = {'name': name}
    if display_name is not None:
        payload['display_name'] = display_name
    response = await api.post('/agent/update', json=payload)
    assert_status(response, 200)
    data = response.json()
    agent_id = data.get('agent_id')
    assert isinstance(agent_id, int), data
    register_asset('owned_agents',str(agent_id),agent_id,owner_case_id=CASE_ID,cleanup={
        'service':'config','identity':identity.id,'method':'DELETE','path':'/agent',
        'json':{'agent_id':agent_id},'allowed_statuses':[200,204,404]})
    return agent_id


async def _delete_agent(api, agent_id: int) -> None:
    response = await api.request('DELETE', '/agent', json={'agent_id': agent_id})
    assert_status(response, (200, 204))
    mark_asset_state('owned_agents',str(agent_id),'DELETED')


async def _check_name(api, items: list[dict]) -> list[dict]:
    response = await api.post('/agent/check_name', json={'items': items})
    assert_status(response, 200)
    return response.json()


async def _existing_values(api) -> tuple[set[str], set[str]]:
    response = await api.get('/agent/list')
    assert_status(response, 200)
    names: set[str] = set()
    displays: set[str] = set()
    for item in response.json():
        if item.get('name'):
            names.add(item['name'])
        if item.get('display_name'):
            displays.add(item['display_name'])
    return names, displays


async def _load_llm_model_id(api) -> int | None:
    response = await api.get('/config/load_config')
    assert_status(response, 200)
    llm = ((response.json().get('config') or {}).get('models') or {}).get('llm') or {}
    return _find_int(llm, {'id', 'model_id'})


@pytest.mark.asyncio
@pytest.mark.stage('D2')
@pytest.mark.case_id("API-AUTO-DDE7582FFE405D54")
async def test_api_auto_dde7582ffe405d54(tenant_a_admin, tenant_b_admin):
    suffix = _suffix()
    dup_name = f'dup_name_{suffix}'
    dup_display = f'Dup Name {suffix}'

    created_a: list[int] = []
    created_b: list[int] = []
    try:
        async with client('config', token=tenant_a_admin.access_token) as api:
            agent_a = await _create_agent(api, dup_name, tenant_a_admin, dup_display)
            created_a.append(agent_a)
            agent_b = await _create_agent(api, dup_name, tenant_a_admin, dup_display)
            created_a.append(agent_b)

            result = await _check_name(api, [{'name': dup_name, 'display_name': dup_display}])
            assert isinstance(result, list) and len(result) == 1
            assert result[0]['name_conflict'] is True
            assert result[0]['display_name_conflict'] is True
            assert len(result[0]['conflict_agents']) >= 2
            for entry in result[0]['conflict_agents']:
                assert 'name' in entry and 'display_name' in entry

            result = await _check_name(api, [{'name': dup_name, 'agent_id': agent_a}])
            assert len(result) == 1
            assert result[0]['name_conflict'] is True
            assert len(result[0]['conflict_agents']) == 1
            assert result[0]['conflict_agents'][0]['name'] == dup_name

            result = await _check_name(api, [])
            assert result == []

        async with client('config', token=tenant_b_admin.access_token) as api_b:
            b_name = f'b_only_{suffix}'
            b_agent = await _create_agent(api_b, b_name, tenant_b_admin)
            created_b.append(b_agent)

            # Validate the no-model branch in a tenant that already has no
            # quick-config LLM; never clear a shared tenant's live setting.
            b_model_id = await _load_llm_model_id(api_b)
            if b_model_id is not None:
                raise AssetDependencyError(
                    'isolated_tenants', 'without_llm', CASE_ID,
                    detail='negative regeneration branch requires a tenant without LLM quick config',
                )
            response = await api_b.post(
                '/agent/regenerate_name',
                json={'items': [{'name': b_name, 'display_name': b_name}]},
            )
            assert response.status_code == 400
            error_body = response.json()
            assert NO_MODEL_DETAIL in str(error_body.get('detail') or error_body.get('message') or '')

        async with client('config', token=tenant_a_admin.access_token) as api:
            result = await _check_name(api, [{'name': b_name}])
            assert len(result) == 1
            assert result[0]['name_conflict'] is False
            assert result[0]['conflict_agents'] == []

            if await _load_llm_model_id(api) is None:
                raise AssetDependencyError(
                    'models', 'llm', CASE_ID,
                    detail='positive regeneration branch requires an LLM quick config',
                )

            names, displays = await _existing_values(api)

            response = await api.post(
                '/agent/regenerate_name',
                json={'items': [{'name': dup_name, 'display_name': dup_display}]},
            )
            assert response.status_code == 200
            regen = response.json()
            assert isinstance(regen, list) and len(regen) == 1
            item = regen[0]
            assert 'name' in item and 'display_name' in item
            assert item['name'] and item['name'] != dup_name
            assert item['name'] not in names
            assert item['display_name'] and item['display_name'] != dup_display
            assert item['display_name'] not in displays

            response = await api.post(
                '/agent/regenerate_name',
                json={
                    'items': [
                        {'name': dup_name, 'display_name': dup_display},
                        {'name': dup_name, 'display_name': dup_display},
                    ],
                },
            )
            assert response.status_code == 200
            batch = response.json()
            assert isinstance(batch, list) and len(batch) == 2
            assert batch[0]['name'] != batch[1]['name']
            for entry in batch:
                assert entry['name'] and entry['name'] != dup_name
    finally:
        async with client('config', token=tenant_a_admin.access_token) as api:
            for agent_id in created_a:
                await _delete_agent(api, agent_id)
        async with client('config', token=tenant_b_admin.access_token) as api_b:
            for agent_id in created_b:
                await _delete_agent(api_b, agent_id)
