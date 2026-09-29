from __future__ import annotations

import base64
import json

import pytest

from shared.asset_registry import resolve_asset
from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id
from shared.factories.tags import select_owned_definitions


CASE_ID = 'API-AUTO-3DDBA5C9A0148698'

_RESOURCE_TYPES = ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')


def _resolve_resource(resource_type):
    value = resolve_asset('tag_assignments', resource_type, required=True, consumer_case_id=CASE_ID)
    if isinstance(value, dict):
        return value
    return {'resource_id': value}


async def _get_assignments(api, resource_type, resource_id, provider=None, knowledge_base_id=None):
    params = {}
    if provider:
        params['provider'] = provider
    if knowledge_base_id:
        params['knowledge_base_id'] = knowledge_base_id
    return await api.get(f'/tag-libraries/assignments/{resource_type}/{resource_id}', params=params)


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
async def test_resource_tag_assignment_contract(super_admin, tenant_a_admin, tenant_a_dev, tenant_a_user):
    matrix = [
        (super_admin, 200),
        (tenant_a_admin, 200),
        (tenant_a_dev, 403),
        (tenant_a_user, 403),
    ]
    for identity, expected in matrix:
        async with client('config', token=identity.access_token) as api:
            response = await api.get('/tag-libraries')
        assert_status(response, expected)

    async with client('config', token=tenant_a_admin.access_token) as api:
        libraries = await api.get('/tag-libraries')
    assert_status(libraries, 200)
    buckets = {item['bucket_key']: item for item in libraries.json()}
    assert 'default_resource' in buckets
    assert 'knowledge_content' in buckets
    default_bucket_id = buckets['default_resource']['bucket_id']

    async with client('config', token=tenant_a_admin.access_token) as api:
        definitions_response = await api.get(f'/tag-libraries/{default_bucket_id}/definitions')
    assert_status(definitions_response, 200)
    definitions = definitions_response.json()
    multi_select = select_owned_definitions(definitions,'multi_select')
    single_select = select_owned_definitions(definitions,'single_select')
    assert multi_select, 'precondition: multi_select definition with active values is required'
    assert single_select, 'precondition: single_select definition with active values is required'
    multi_definition = multi_select[0]
    multi_value_ids = [v['value_id'] for v in multi_definition['values'] if v['status'] == 'active']
    assert multi_value_ids, 'precondition: multi_select definition has active values'

    for resource_type in _RESOURCE_TYPES:
        async with client('config', token=tenant_a_admin.access_token) as api:
            missing = await api.get(f'/tag-libraries/assignments/{resource_type}/__nonexistent__')
        assert_status(missing, 404)

    async with client('config', token=tenant_a_admin.access_token) as api:
        echo = await api.post(
            '/tag-libraries/assignments/agent/filter',
            json={'resource_ids': ['1', '2'], 'predicates': []},
        )
    assert_status(echo, 200)
    assert echo.json()['resource_type'] == 'agent'
    assert echo.json()['matched_resource_ids'] == ['1', '2']

    async with client('config', token=tenant_a_admin.access_token) as api:
        document_filter = await api.post(
            '/tag-libraries/assignments/knowledge_document/filter',
            json={'resource_ids': ['1'], 'predicates': []},
        )
    assert_status(document_filter, 400)
    document_body = document_filter.json()
    assert 'batch-status' in str(document_body.get('detail') or document_body.get('message') or '')

    async with client('config', token=tenant_a_admin.access_token) as api:
        bad_type = await api.post(
            '/tag-libraries/assignments/not_a_type/filter',
            json={'resource_ids': ['1'], 'predicates': []},
        )
    assert_status(bad_type, 400)

    async with client('config', token=tenant_a_admin.access_token) as api:
        bulk_missing = await api.put(
            '/tag-libraries/assignments/agent/bulk',
            json={'targets': [{'resource_id': '__nonexistent__', 'value_ids': [1]}]},
        )
    assert_status(bulk_missing, 200)
    assert bulk_missing.json()[0]['outcome'] == 'not_found_or_forbidden'

    async with client('config', token=tenant_a_admin.access_token) as api:
        batch_status = await api.post(
            '/tag-libraries/documents/batch-status',
            json={'document_ids': ['x'], 'predicates': []},
        )
    assert_status(batch_status, 400)

    agent = _resolve_resource('agent')
    agent_id = str(agent['resource_id'])
    async with client('config', token=tenant_a_admin.access_token) as api:
        initial = await _get_assignments(api, 'agent', agent_id)
    assert_status(initial, 200)
    initial_body = initial.json()
    assert initial_body['resource_type'] == 'agent'
    assert initial_body['resource_id'] == agent_id
    assert initial_body['assignment_capacity'] == 100
    assert initial_body['assignment_count'] == len(initial_body['assignments'])

    submitted_value_ids = multi_value_ids[:2]
    async with client('config', token=tenant_a_admin.access_token) as api:
        replaced = await api.put(
            f'/tag-libraries/assignments/agent/{agent_id}',
            json={'value_ids': submitted_value_ids},
        )
    assert_status(replaced, 200)
    replaced_body = replaced.json()
    assert replaced_body['assignment_count'] == len(submitted_value_ids)
    assert replaced_body['assignment_capacity'] == 100
    assert {item['value_id'] for item in replaced_body['assignments']} == set(submitted_value_ids)
    for item in replaced_body['assignments']:
        assert item['definition_id'] == multi_definition['definition_id']
        assert item['definition_key'] == multi_definition['definition_key']
        assert item['selection_mode'] == 'multi_select'
        assert item['value_status'] in {'active', 'disabled'}

    async with client('config', token=tenant_a_admin.access_token) as api:
        persisted = await _get_assignments(api, 'agent', agent_id)
    assert_status(persisted, 200)
    assert persisted.json()['assignment_count'] == len(submitted_value_ids)

    single_definition = single_select[0]
    single_value_ids = [v['value_id'] for v in single_definition['values'] if v['status'] == 'active']
    if len(single_value_ids) >= 2:
        async with client('config', token=tenant_a_admin.access_token) as api:
            single_conflict = await api.put(
                f'/tag-libraries/assignments/agent/{agent_id}',
                json={'value_ids': single_value_ids[:2]},
            )
        assert_status(single_conflict, 400)
        single_body = single_conflict.json()
        assert (single_body.get('detail') or single_body.get('message')) == 'A single-select tag definition accepts only one assigned value'
        async with client('config', token=tenant_a_admin.access_token) as api:
            after_conflict = await _get_assignments(api, 'agent', agent_id)
        assert after_conflict.json()['assignment_count'] == len(submitted_value_ids)

    async with client('config', token=tenant_a_admin.access_token) as api:
        foreign_value = await api.put(
            f'/tag-libraries/assignments/agent/{agent_id}',
            json={'value_ids': [absent_numeric_id(__name__)]},
        )
    assert_status(foreign_value, 400)
    foreign_body = foreign_value.json()
    assert (foreign_body.get('detail') or foreign_body.get('message')) == 'Each assigned tag value must be active and belong to the resource library'

    async with client('config', token=tenant_a_admin.access_token) as api:
        capacity = await api.put(
            f'/tag-libraries/assignments/agent/{agent_id}',
            json={'value_ids': list(range(1, 102))},
        )
    assert_status(capacity, 409)
    capacity_body = capacity.json()
    capacity_detail = capacity_body.get('detail')
    if not isinstance(capacity_detail, dict) or not capacity_detail.get('message'):
        capacity_detail = capacity_body.get('message', {})
    assert isinstance(capacity_detail, dict), capacity_body
    assert capacity_detail['message'] == 'Resource tag assignment capacity exceeded'
    assert capacity_detail['details']['scope'] == 'assignment'

    async with client('config', token=tenant_a_admin.access_token) as api:
        bulk_mixed = await api.put(
            '/tag-libraries/assignments/agent/bulk',
            json={
                'targets': [
                    {'resource_id': agent_id, 'value_ids': submitted_value_ids},
                    {'resource_id': '__cross__', 'value_ids': [1]},
                ]
            },
        )
    assert_status(bulk_mixed, 200)
    bulk_outcomes = {o['resource_id']: o['outcome'] for o in bulk_mixed.json()}
    assert bulk_outcomes[agent_id] == 'updated'
    assert bulk_outcomes['__cross__'] == 'not_found_or_forbidden'

    async with client('config', token=tenant_a_admin.access_token) as api:
        filtered = await api.post(
            '/tag-libraries/assignments/agent/filter',
            json={
                'resource_ids': [agent_id, '__other__'],
                'predicates': [{'definition_id': multi_definition['definition_id'], 'value_ids': [submitted_value_ids[0]]}],
            },
        )
    assert_status(filtered, 200)
    matched = filtered.json()['matched_resource_ids']
    assert agent_id in matched
    assert '__other__' not in matched

    for resource_type in ('skill', 'tool', 'mcp_service', 'knowledge_base'):
        resource = _resolve_resource(resource_type)
        resource_id = str(resource['resource_id'])
        async with client('config', token=tenant_a_admin.access_token) as api:
            read = await _get_assignments(api, resource_type, resource_id)
        assert_status(read, 200)
        body = read.json()
        assert body['resource_type'] == resource_type
        assert body['resource_id'] == resource_id
        assert body['assignment_capacity'] == 100
        assert body['assignment_count'] == len(body['assignments'])

    document = _resolve_resource('knowledge_document')
    doc_id = str(document['resource_id'])
    provider = str(document['provider'])
    knowledge_base_id = str(document['knowledge_base_id'])
    async with client('config', token=tenant_a_admin.access_token) as api:
        document_read = await _get_assignments(api, 'knowledge_document', doc_id, provider=provider, knowledge_base_id=knowledge_base_id)
    assert_status(document_read, 200)
    document_body = document_read.json()
    assert document_body['resource_type'] == 'knowledge_document'
    canonical = json.loads(base64.urlsafe_b64decode(document_body['resource_id']).decode('utf-8'))
    assert canonical == [provider, knowledge_base_id, doc_id]
