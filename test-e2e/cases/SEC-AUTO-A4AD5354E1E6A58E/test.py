from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import uuid

import pytest

from shared.config import load_secret_env
from shared.http import client
from shared.factories.tags import register_tag_definition

CASE_ID = 'SEC-AUTO-A4AD5354E1E6A58E'
FORBIDDEN_DETAIL = 'Tag library management permission is required'
NOT_FOUND_DETAIL = 'Resource not found'
RESOURCE_TYPES = ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')


async def _call(api, responses, method, path, payload=None):
    kwargs = {} if payload is None else {'json': payload}
    resp = await api.request(method, path, **kwargs)
    responses.append(resp)
    return resp


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
async def test_tag_library_governance_idor_and_assignment_fail_closed(
    super_admin,
    tenant_a_admin,
    tenant_a_dev,
    tenant_a_user,
    tenant_b_admin,
    tenant_b_user,
):
    responses = []
    unprivileged = (tenant_a_dev, tenant_a_user, tenant_b_user)

    governance_calls = [
        ('GET', '/tag-libraries'),
        ('GET', '/tag-libraries/1/definitions'),
        ('POST', '/tag-libraries/1/definitions', {'definition_name': 'sec_probe', 'selection_mode': 'multi_select', 'initial_values': ['probe_v1']}),
        ('PATCH', '/tag-libraries/1/definitions/1', {'definition_name': 'sec_probe'}),
        ('DELETE', '/tag-libraries/1/definitions/1'),
        ('POST', '/tag-libraries/1/definitions/1/values', {'display_value': 'probe_v1'}),
        ('PATCH', '/tag-libraries/1/definitions/1/values/1', {'display_value': 'probe_v1'}),
        ('GET', '/tag-libraries/1/definitions/1/usage'),
    ]

    for identity in unprivileged:
        async with client('config', token=identity.access_token) as api:
            for item in governance_calls:
                method = item[0]
                path = item[1]
                payload = item[2] if len(item) > 2 else None
                resp = await _call(api, responses, method, path, payload)
                assert resp.status_code == 403, (
                    f'{identity.id} {method} {path} expected 403, got {resp.status_code}: {resp.text!r}'
                )
                assert FORBIDDEN_DETAIL in resp.text
                body = resp.json()
                assert set(body.keys()) <= {'detail', 'message'}, f'403 body leaked tag data: {body}'

    async with client('config', token=tenant_a_admin.access_token) as api:
        resp = await _call(api, responses, 'GET', '/tag-libraries')
        assert resp.status_code == 200, f'tenant_a_admin list libraries: {resp.status_code}'
        buckets = resp.json()
        assert buckets, 'tenant_a has no provisioned tag libraries'
        ta_default = next((b for b in buckets if b.get('bucket_key') == 'default_resource'), buckets[0])
        ta_bucket = ta_default['bucket_id']

    async with client('config', token=super_admin.access_token) as api:
        resp = await _call(api, responses, 'GET', '/tag-libraries')
        assert resp.status_code != 403, f'super_admin list libraries unexpectedly 403'

    ta_def_id = None
    ta_value_ids = []
    tb_def_id = None
    tb_value_ids = []
    tb_bucket = None
    def_name_ta = f'sec_auto_ta_{uuid.uuid4().hex[:8]}'
    def_name_tb = f'sec_auto_tb_{uuid.uuid4().hex[:8]}'

    async with client('config', token=tenant_b_admin.access_token) as api:
        resp = await _call(api, responses, 'GET', '/tag-libraries')
        assert resp.status_code == 200, f'tenant_b_admin list libraries: {resp.status_code}'
        tb_buckets = resp.json()
        assert tb_buckets, 'tenant_b has no provisioned tag libraries'
        tb_default = next((b for b in tb_buckets if b.get('bucket_key') == 'default_resource'), tb_buckets[0])
        tb_bucket = tb_default['bucket_id']

    try:
        async with client('config', token=tenant_a_admin.access_token) as api:
            resp = await _call(api, responses, 'POST', f'/tag-libraries/{ta_bucket}/definitions', {
                'definition_name': def_name_ta,
                'selection_mode': 'multi_select',
                'initial_values': ['alpha', 'beta'],
            })
            assert resp.status_code == 200, f'create ta definition: {resp.status_code} {resp.text!r}'
            ta_def = resp.json()
            ta_def_id = ta_def['definition_id']
            register_tag_definition(tenant_a_admin, ta_bucket, ta_def)
            ta_value_ids = [v['value_id'] for v in ta_def.get('values', [])]

        async with client('config', token=tenant_b_admin.access_token) as api:
            resp = await _call(api, responses, 'POST', f'/tag-libraries/{tb_bucket}/definitions', {
                'definition_name': def_name_tb,
                'selection_mode': 'multi_select',
                'initial_values': ['gamma', 'delta'],
            })
            assert resp.status_code == 200, f'create tb definition: {resp.status_code} {resp.text!r}'
            tb_def = resp.json()
            tb_def_id = tb_def['definition_id']
            register_tag_definition(tenant_b_admin, tb_bucket, tb_def)
            tb_value_ids = [v['value_id'] for v in tb_def.get('values', [])]

        assert tb_value_ids, 'tb definition created without values'
        tb_value_id = tb_value_ids[0]
        tb_display = tb_def.get('values', [{}])[0].get('display_value', '')

        async with client('config', token=tenant_a_admin.access_token) as api:
            resp = await _call(api, responses, 'GET', f'/tag-libraries/{tb_bucket}/definitions')
            assert resp.status_code == 404, f'cross-tenant bucket -> {resp.status_code}'
            assert 'Tag library not found' in resp.text
            assert def_name_tb not in resp.text

            resp = await _call(api, responses, 'GET', f'/tag-libraries/{ta_bucket}/definitions/{tb_def_id}/usage')
            assert resp.status_code == 404, f'cross-tenant definition usage -> {resp.status_code}'
            assert 'Tag definition not found' in resp.text

            resp = await _call(api, responses, 'GET', f'/tag-libraries/{ta_bucket}/definitions/{ta_def_id}/values/{tb_value_id}/usage')
            assert resp.status_code == 404, f'cross-tenant value usage -> {resp.status_code}'
            assert 'Tag value not found' in resp.text

            resp = await _call(api, responses, 'PATCH', f'/tag-libraries/{ta_bucket}/definitions/{tb_def_id}', {'definition_name': 'hijack'})
            assert resp.status_code == 404, f'cross-tenant definition update -> {resp.status_code}'
            assert tb_display not in resp.text

            resp = await _call(api, responses, 'DELETE', f'/tag-libraries/{ta_bucket}/definitions/{tb_def_id}')
            assert resp.status_code == 404, f'cross-tenant definition delete -> {resp.status_code}'

        absent_doc = 'sec_auto_absent_doc'
        absent_kb = f'sec_auto_absent_kb_{uuid.uuid4().hex[:8]}'
        async with client('config', token=tenant_a_admin.access_token) as api:
            for rt in RESOURCE_TYPES:
                rid = absent_kb if rt == 'knowledge_base' else (absent_doc if rt == 'knowledge_document' else str(absent_numeric_id(__name__)))
                path = f'/tag-libraries/assignments/{rt}/{rid}'
                if rt == 'knowledge_document':
                    path += f'?provider=local&knowledge_base_id={absent_kb}'
                resp = await _call(api, responses, 'GET', path)
                assert resp.status_code == 404, f'GET assignment {rt} -> {resp.status_code}'
                assert NOT_FOUND_DETAIL in resp.text

            for suffix in ('projection-status', 'compatibility/flat-tags'):
                path = f'/tag-libraries/assignments/knowledge_document/{absent_doc}/{suffix}?provider=local&knowledge_base_id={absent_kb}'
                resp = await _call(api, responses, 'GET', path)
                assert resp.status_code == 404, f'GET document {suffix} -> {resp.status_code}'

            for provider in ('local', 'aidp'):
                resp = await _call(api, responses, 'POST', f'/tag-libraries/documents/batch-status?provider={provider}&knowledge_base_id={absent_kb}', {'document_ids': ['doc1']})
                assert resp.status_code == 404, f'batch-status provider={provider} -> {resp.status_code}'
                assert 'Knowledge base not found' in resp.text

        secret_values = [v for v in load_secret_env().values() if v and len(v) >= 8]
        secret_keys = ('api_key', 'authorization_token', 'access_key', 'apikey')
        for resp in responses:
            lowered = resp.text.lower()
            for key in secret_keys:
                assert key not in lowered, f'secret field {key} leaked from {resp.request.url}'
            for value in secret_values:
                assert value not in resp.text, f'secret value leaked from {resp.request.url}'

    finally:
        async with client('config', token=tenant_a_admin.access_token) as api:
            if ta_def_id is not None:
                for value_id in ta_value_ids:
                    await api.delete(f'/tag-libraries/{ta_bucket}/definitions/{ta_def_id}/values/{value_id}')
                await api.delete(f'/tag-libraries/{ta_bucket}/definitions/{ta_def_id}')
        async with client('config', token=tenant_b_admin.access_token) as api:
            if tb_def_id is not None and tb_bucket is not None:
                for value_id in tb_value_ids:
                    await api.delete(f'/tag-libraries/{tb_bucket}/definitions/{tb_def_id}/values/{value_id}')
                await api.delete(f'/tag-libraries/{tb_bucket}/definitions/{tb_def_id}')
