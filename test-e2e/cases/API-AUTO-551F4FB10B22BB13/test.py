'''D2 API-IT for POST /indices/search/hybrid.

Covers the tag_predicates passthrough contract on the hybrid search endpoint:
absent or empty tag_predicates keeps the legacy request shape and behaviour, a
non-empty list is forwarded and narrows results to projection-confirmed
documents, per-KB read isolation still yields 403 / 404, a KB without a
resolvable embedding model yields 409 with detail.error_type ==
KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG, and error responses never leak plaintext
credentials.
'''

from __future__ import annotations

import os
import uuid
from urllib.parse import quote

import pytest

from d3.assets import model_id, model_request
from shared.asset_registry import AssetDependencyError, mark_asset_state, register_asset
from shared.http import assert_no_server_error, assert_status, client, redacted_response_body

CASE_ID = 'API-AUTO-551F4FB10B22BB13'
STAGE = 'D2'

SEARCH_PATH = '/indices/search/hybrid'
EMBEDDING_TYPES = {'embedding', 'multi_embedding', 'multiembedding'}


def _suffix():
    return (os.environ.get('TEST_BATCH') or uuid.uuid4().hex)[:12].lower()


def _as_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('data', 'items', 'models', 'results'):
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
    return []


def _pick_embedding_model_id(payload):
    for model in _as_list(payload):
        if not isinstance(model, dict):
            continue
        model_type = str(model.get('model_type') or model.get('type') or '').lower()
        if model_type in EMBEDDING_TYPES and model.get('model_id') is not None:
            return int(model['model_id'])
    return None


async def _resolve_embedding_model_id(identity, suffix):
    try:
        return await model_id('embedding', identity), None
    except AssetDependencyError:
        # A second test tenant need not share the anchor tenant's models.
        # Create the configured real model in this tenant only.
        async with client('config', token=identity.access_token) as api:
            return await _create_embedding_model(api, suffix, identity)


def _embedding_model_request(suffix):
    # Keep the provider's real model name. Only the tenant-local display name
    # is unique to this case; fabricated model names fail live connectivity.
    return model_request('embedding', display_name=f'tagpred-embedding-{suffix}')


async def _create_embedding_model(api, suffix, identity):
    request = _embedding_model_request(suffix)
    response = await api.post('/model/create', json=request)
    assert_status(response, 200)
    register_asset('case_models',request['display_name'],request['display_name'],owner_case_id=CASE_ID,cleanup={
        'service':'config','identity':identity.id,'method':'POST',
        'path':'/model/delete?display_name='+request['display_name'],'allowed_statuses':[200,404]})
    listed = await api.get('/model/list')
    assert_status(listed, 200)
    model_id = next((item.get('model_id') for item in _as_list(listed.json())
                     if item.get('display_name') == request['display_name']
                     and item.get('model_type') in EMBEDDING_TYPES), None)
    if model_id is None:
        raise AssertionError('create embedding model returned no model_id')
    return int(model_id), request['display_name']


async def _delete_model(api, display_name):
    response = await api.post('/model/delete', params={'display_name': display_name})
    assert_status(response, (200, 404))
    mark_asset_state('case_models',display_name,'DELETED')


async def _create_kb(api, name, embedding_model_id, identity):
    response = await api.post(f'/indices/{name}', json={'embedding_model_id': embedding_model_id})
    assert_status(response, 200)
    body = response.json()
    index_name = body.get('id') or body.get('index_name') or name
    if not index_name:
        raise AssertionError('create knowledge base returned no internal index name')
    register_asset('owned_knowledge',str(index_name),str(index_name),owner_case_id=CASE_ID,cleanup={
        'service':'config','identity':identity.id,'method':'DELETE',
        'path':f'/indices/{index_name}','allowed_statuses':[200,404]})
    return str(index_name)


async def _index_docs(api, index_name, docs):
    response = await api.post(f'/indices/{index_name}/documents', json=docs)
    assert_status(response, 200)
    body = response.json()
    if body.get('total_indexed', 0) < 1:
        raise AssertionError(f'documents were not indexed: {redacted_response_body(response)}')


async def _find_knowledge_content_bucket_id(api):
    response = await api.get('/tag-libraries')
    assert_no_server_error(response)
    libraries = [item for item in _as_list(response.json()) if isinstance(item, dict)]
    for library in libraries:
        if str(library.get('bucket_key') or '') == 'knowledge_content':
            return library.get('bucket_id')
    raise AssetDependencyError(
        'tag_libraries', 'knowledge_content', CASE_ID,
        detail='tenant has no knowledge_content system library; check unified-tag migration/provisioning',
    )


async def _create_tag_definition(api, bucket_id, name, values):
    response = await api.post(
        f'/tag-libraries/{bucket_id}/definitions',
        json={'definition_name': name, 'selection_mode': 'multi_select', 'initial_values': values},
    )
    assert_status(response, (200, 201))
    return response.json()


async def _assign_document_tag(api, provider, knowledge_base_id, document_id, value_ids):
    response = await api.put(
        f'/tag-libraries/assignments/knowledge_document/{quote(document_id, safe="")}',
        params={'provider': provider, 'knowledge_base_id': knowledge_base_id},
        json={'value_ids': value_ids},
    )
    assert_status(response, (200, 201))
    return response.json()


async def _delete_kb(api, index_name):
    response = await api.delete(f'/indices/{index_name}')
    assert_status(response, (200, 404))
    mark_asset_state('owned_knowledge',str(index_name),'DELETED')


def _result_paths(body):
    results = body.get('results') or []
    return [str(item.get('path_or_url') or '') for item in results if isinstance(item, dict)]


def _leaked_secret(text, secrets):
    lowered = text.lower()
    for secret in secrets:
        if secret and secret.lower() in lowered:
            return secret
    return None


@pytest.mark.asyncio
@pytest.mark.stage(STAGE)
@pytest.mark.case_id(CASE_ID)
async def test_hybrid_search_tag_predicates_and_isolation(
    tenant_a_admin,
    tenant_a_user,
    tenant_b_admin,
):
    suffix = _suffix()
    kb_a_name = f'tagpred-a-{suffix}'
    kb_b_name = f'tagpred-b-{suffix}'

    a_token = tenant_a_admin.access_token
    b_token = tenant_b_admin.access_token
    secrets = [
        a_token,
        tenant_a_admin.refresh_token or '',
        b_token,
        tenant_b_admin.refresh_token or '',
    ]

    created_a = []
    created_b = []
    owned_model_a = None
    owned_model_b = None
    dedicated_model_name = None
    definition_id = None
    bucket_id = None
    values = {}

    try:
        model_a_id, owned_model_a = await _resolve_embedding_model_id(tenant_a_admin, suffix+'-a')
        model_b_id, owned_model_b = await _resolve_embedding_model_id(tenant_b_admin, suffix+'-b')
        async with client('config', token=a_token) as api:
            index_a = await _create_kb(api, kb_a_name, model_a_id, tenant_a_admin)
            created_a.append(index_a)

            docs = [
                {
                    'content': 'green apple crisp and fresh',
                    'path_or_url': f'{suffix}-green.txt',
                    'filename': 'green.txt',
                    'source_type': 'local',
                    'metadata': {'title': 'green apple'},
                },
                {
                    'content': 'red apple ripe and sweet',
                    'path_or_url': f'{suffix}-red.txt',
                    'filename': 'red.txt',
                    'source_type': 'local',
                    'metadata': {'title': 'red apple'},
                },
            ]
            await _index_docs(api, index_a, docs)

            default_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [kb_a_name], 'top_k': 20,
            })
            assert_status(default_resp, 200)
            default_body = default_resp.json()
            assert 'results' in default_body
            for item in default_body['results']:
                assert 'score' in item and 'index' in item
            default_paths = set(_result_paths(default_body))

            empty_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [kb_a_name], 'top_k': 20, 'tag_predicates': [],
            })
            assert_status(empty_resp, 200)
            assert set(_result_paths(empty_resp.json())) == default_paths

            bucket_id = await _find_knowledge_content_bucket_id(api)
            definition = await _create_tag_definition(api, bucket_id, f'color-{suffix}', ['green', 'red'])
            definition_id = definition.get('definition_id')
            values = {
                item.get('display_value'): item.get('value_id')
                for item in (definition.get('values') or [])
            }
            assert definition_id and values.get('green') and values.get('red')
            register_asset('tag_definitions',str(definition_id),definition_id,owner_case_id=CASE_ID,cleanup={
                'service':'config','identity':tenant_a_admin.id,'method':'DELETE',
                'path':f'/tag-libraries/{bucket_id}/definitions/{definition_id}',
                'allowed_statuses':[200,404]})

            await _assign_document_tag(api, 'local', index_a, f'{suffix}-green.txt', [values['green']])
            await _assign_document_tag(api, 'local', index_a, f'{suffix}-red.txt', [values['red']])

            filtered_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [kb_a_name], 'top_k': 20,
                'tag_predicates': [{'definition_id': definition_id, 'value_ids': [values['green']]}],
            })
            assert_status(filtered_resp, 200)
            filtered_paths = _result_paths(filtered_resp.json())
            assert f'{suffix}-green.txt' in filtered_paths
            assert f'{suffix}-red.txt' not in filtered_paths

            dedicated_model_id, dedicated_model_name = await _create_embedding_model(api, suffix, tenant_a_admin)
            index_no_model = await _create_kb(api, f'{kb_a_name}-nomodel', dedicated_model_id, tenant_a_admin)
            created_a.append(index_no_model)
            await _delete_model(api, dedicated_model_name)
            dedicated_model_name = None

            no_model_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [index_no_model], 'top_k': 10,
            })
            assert_status(no_model_resp, 409)
            error_body = no_model_resp.json()
            detail = error_body.get('detail') or error_body.get('message') or error_body
            assert isinstance(detail, dict) and detail.get('error_type') == 'KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG', redacted_response_body(no_model_resp)
            assert _leaked_secret(no_model_resp.text, secrets) is None

        async with client('config', token=b_token) as api:
            index_b = await _create_kb(api, kb_b_name, model_b_id, tenant_b_admin)
            created_b.append(index_b)
            await _index_docs(api, index_b, [
                {
                    'content': 'blue truck parked outside',
                    'path_or_url': f'{suffix}-truck.txt',
                    'filename': 'truck.txt',
                    'source_type': 'local',
                    'metadata': {'title': 'blue truck'},
                },
            ])

            own_resp = await api.post(SEARCH_PATH, json={
                'query': 'truck', 'index_names': [kb_b_name], 'top_k': 10,
            })
            assert_status(own_resp, 200)
            own_paths = _result_paths(own_resp.json())
            assert f'{suffix}-truck.txt' in own_paths
            assert f'{suffix}-green.txt' not in own_paths
            assert f'{suffix}-red.txt' not in own_paths

            cross_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [index_a], 'top_k': 10,
            })
            assert_status(cross_resp, 403)
            assert _leaked_secret(cross_resp.text, secrets) is None

            missing_resp = await api.post(SEARCH_PATH, json={
                'query': 'apple', 'index_names': [f'not-exist-{suffix}'], 'top_k': 10,
            })
            assert_status(missing_resp, 404)
            assert _leaked_secret(missing_resp.text, secrets) is None
    finally:
        async with client('config', token=a_token) as api:
            for index_name in created_a:
                await _delete_kb(api, index_name)
            if definition_id is not None and bucket_id is not None:
                for value_id in values.values():
                    removed_value = await api.delete(
                        f'/tag-libraries/{bucket_id}/definitions/{definition_id}/values/{value_id}'
                    )
                    assert_status(removed_value, (200, 404))
                removed = await api.delete(f'/tag-libraries/{bucket_id}/definitions/{definition_id}')
                assert_status(removed, (200, 404))
                mark_asset_state('tag_definitions',str(definition_id),'DELETED')
            if dedicated_model_name is not None:
                await _delete_model(api, dedicated_model_name)
            if owned_model_a is not None:
                await _delete_model(api, owned_model_a)
        async with client('config', token=b_token) as api:
            for index_name in created_b:
                await _delete_kb(api, index_name)
            if owned_model_b is not None:
                await _delete_model(api, owned_model_b)
