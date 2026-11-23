# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Create only run-owned TPC models, real Skills and published Agents."""
import os
import uuid

import httpx

from shared.asset_registry import AssetDependencyError, register_asset
from shared.auth import sign_in
from shared.config import controlled_asset_url, service_url
from shared.factories.agent import _draft_agent
from shared.factories.skill import _skill_payload
from shared.http import assert_status, client


class FixtureConfig(dict):
    """Keep runtime authentication out of pytest fixture/local representations."""
    def __repr__(self):
        return '<TPC fixture with private runtime authentication>'

    __str__ = __repr__

    def copy(self):
        return type(self)(self)


async def setup(case_id):
    identity = await sign_in('tenant_a_admin')
    nonce = uuid.uuid4().hex
    local = os.environ.get('NEXENT_TEST_ASSETS_LOCAL_URL', '').rstrip('/')
    if not local:
        raise AssetDependencyError('services', 'tpc_provider', detail='Runner-owned controlled HTTP service required')
    provider = local + '/tpc/' + nonce
    async with httpx.AsyncClient(trust_env=False) as control:
        response = await control.post(provider + '/__control', json={'responses': ['<final_answer>TPC ready</final_answer>']})
        assert_status(response, 200)
    display, skill_name = 'tpc_' + nonce, 'tpc-quality-check-' + nonce[:10]
    async with client('config', token=identity.access_token) as api:
        created = await api.post('/model/create', json={
            'model_factory': 'OpenAI-API-Compatible', 'model_name': 'tpc', 'model_type': 'llm',
            'api_key': nonce, 'base_url': controlled_asset_url(f'/tpc/{nonce}/v1'),
            'display_name': display, 'max_tokens': 4096})
        assert_status(created, 200)
        register_asset('owned_models', display, display, owner_case_id=case_id, cleanup={
            'service': 'config', 'identity': identity.id, 'method': 'POST', 'path': '/model/delete',
            'params': {'display_name': display}, 'allowed_statuses': [200, 404]})
        catalog = await api.get('/model/list')
        assert_status(catalog, 200)
        models = catalog.json()['data']
        model_id = next(int(row.get('model_id') or row['id']) for row in models if row['display_name'] == display)
        health = await api.post('/model/healthcheck', params={'display_name': display, 'model_type': 'llm'})
        assert_status(health, 200)
        assert health.json()['data']['connectivity'] is True, 'TPC provider is not product-reachable'
        payload = _skill_payload(skill_name)
        payload['content'] += '\nTPC_REAL_SKILL_CONTENT\nRead this guide exactly once before reporting completion.\n'
        skill = await api.post('/skills', json=payload)
        assert_status(skill, 201)
        skill_id = int(skill.json()['skill_id'])
        register_asset('owned_skills', skill_name, skill_id, owner_case_id=case_id, cleanup={
            'service': 'config', 'identity': identity.id, 'method': 'DELETE',
            'path': '/skills/' + skill_name, 'allowed_statuses': [200, 404]})
    fixtures = {}
    for kind in ('controlled', 'real'):
        async with _draft_agent(identity, name_prefix='tpc-' + kind, retain_for_batch=True,
                                owner_case_id=case_id, registry_role='tpc_' + kind,
                                cleanup_identity=identity.id,
                                model_ids=[model_id] if kind == 'controlled' else None) as (agent_id, body):
            async with client('config', token=identity.access_token) as api:
                updated = await api.post('/agent/update', json={**body,
                    'enabled_skill_ids': [skill_id],
                    'skill_instances': [{'skill_id': skill_id, 'enabled': True, 'config_values': {}}],
                    'enable_protocol_repair_retry': True,
                    'duty_prompt': 'Read the bound Skill exactly once when requested, then return the requested final answer.'})
                assert_status(updated, 200)
                published = await api.post(f'/agent/{agent_id}/publish', json={'version_name': 'tpc-acceptance'})
                assert_status(published, 200)
            fixtures[kind] = {'agent_id': agent_id, 'display_name': body['display_name'],
                              'version_no': published.json()['version_no']}
    return FixtureConfig({'runtime': service_url('runtime'), 'provider': provider, 'token': identity.access_token,
            'agent_id': fixtures['controlled']['agent_id'], 'real_agent_id': fixtures['real']['agent_id'],
            'agent_display': fixtures['controlled']['display_name'], 'skill_name': skill_name,
            'version_no': fixtures['controlled']['version_no'], 'real_version_no': fixtures['real']['version_no'],
            'real_model_name': str((await _real_model_name(identity, models, fixtures))), 'nonce': nonce})


async def _real_model_name(identity, models, fixtures):
    async with client('config', token=identity.access_token) as api:
        read = await api.post('/agent/search_info', json={'agent_id': fixtures['real']['agent_id'], 'version_no': 0})
        assert_status(read, 200)
    body = read.json().get('data') or read.json()
    ids = body['model_ids']
    return next(row.get('model_name') or row.get('name') for row in models
                if int(row.get('model_id') or row.get('id') or 0) in ids)
