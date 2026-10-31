from __future__ import annotations

import os
import uuid

import pytest

from shared.http import assert_status, client
from shared.factories.ownership import register_owned_http
from shared.factories.tags import register_tag_definition
from d3.assets import model_id

CASE_ID = 'API-AUTO-E6315598A0EBDD6B'


def _unique_suffix() -> str:
    batch = os.environ.get('TEST_BATCH') or os.environ.get('RUN_ID')
    if batch:
        return f'{batch[:8]}_{uuid.uuid4().hex[:6]}'
    return uuid.uuid4().hex[:12]


@pytest.mark.stage('D3')
@pytest.mark.case_id(CASE_ID)
async def test_delete_index_cascades_cleanup_knowledge_base_tag_assignments(
    tenant_a_admin,
    tenant_b_admin,
):
    suffix = _unique_suffix()
    kb_name = f'api_auto_kb_{suffix}'
    token = tenant_a_admin.access_token

    bucket_id = None
    definition_id = None
    value_id = None
    kb_created = False
    kb_deleted = False

    try:
        async with client('config', token=token) as api:
            create = await api.post(f'/indices/{kb_name}', json={
                'embedding_model_id': await model_id('embedding', tenant_a_admin),
            })
            assert_status(create, (200, 201))
            # The create path is a display name. Subsequent tag and delete
            # endpoints require the internal index ID returned by Nexent.
            kb_name = str(create.json()['id'])
            kb_created = True
            register_owned_http(tenant_a_admin, 'owned_knowledge_bases', kb_name,
                                f'/indices/{kb_name}')

            libraries_response = await api.get('/tag-libraries')
            assert_status(libraries_response, 200)
            libraries = libraries_response.json()
            bucket = next(
                (item for item in libraries if item.get('bucket_key') == 'default_resource'),
                None,
            )
            assert bucket is not None, f'default_resource tag library not found: {libraries}'
            bucket_id = bucket['bucket_id']

            created_definition = await api.post(
                f'/tag-libraries/{bucket_id}/definitions',
                json={
                    'definition_key': f'kb_cascade_{suffix}',
                    'definition_name': f'kb_cascade_{suffix}',
                    'selection_mode': 'multi_select',
                    'initial_values': [f'kb_cascade_val_{suffix}'],
                },
            )
            assert_status(created_definition, 200)
            definition = created_definition.json()
            definition_id = definition['definition_id']
            register_tag_definition(tenant_a_admin, bucket_id, definition)
            values = definition.get('values') or []
            assert values, f'definition response missing values: {definition}'
            value_id = values[0]['value_id']

            assign = await api.put(
                f'/tag-libraries/assignments/knowledge_base/{kb_name}',
                json={'value_ids': [value_id]},
            )
            assert_status(assign, 200)
            assert assign.json().get('assignment_count', 0) >= 1

            read_assign = await api.get(
                f'/tag-libraries/assignments/knowledge_base/{kb_name}'
            )
            assert_status(read_assign, 200)
            assert read_assign.json().get('assignment_count', 0) >= 1

        async with client('config', token=tenant_b_admin.access_token) as other_api:
            cross_read = await other_api.get(
                f'/tag-libraries/assignments/knowledge_base/{kb_name}'
            )
            assert cross_read.status_code == 404, (
                f'cross-tenant assignment read must be 404, got {cross_read.status_code}'
            )

        async with client('config', token=token) as api:
            delete = await api.delete(f'/indices/{kb_name}')
            assert_status(delete, (200, 204))
            kb_deleted = True

            after = await api.get(
                f'/tag-libraries/assignments/knowledge_base/{kb_name}'
            )
            if after.status_code == 404:
                pass
            else:
                assert_status(after, 200)
                assert after.json().get('assignment_count', 0) == 0

    finally:
        async with client('config', token=token) as api:
            if kb_created and not kb_deleted:
                try:
                    await api.delete(f'/indices/{kb_name}')
                except Exception:
                    pass
            if value_id is not None and definition_id is not None and bucket_id is not None:
                try:
                    await api.delete(
                        f'/tag-libraries/{bucket_id}/definitions/{definition_id}/values/{value_id}'
                    )
                except Exception:
                    pass
            if definition_id is not None and bucket_id is not None:
                try:
                    await api.delete(f'/tag-libraries/{bucket_id}/definitions/{definition_id}')
                except Exception:
                    pass
