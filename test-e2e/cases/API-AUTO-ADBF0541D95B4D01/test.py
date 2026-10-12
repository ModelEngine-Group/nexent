from __future__ import annotations

import uuid

import pytest

from shared.asset_registry import register_asset
from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id
from shared.factories.tag_contract import tag_contract_client

CASE_ID = 'API-AUTO-ADBF0541D95B4D01'

MANAGE_DENIED = 'Tag library management permission is required'
DUPLICATE_MESSAGE = 'A tag definition or value with the same normalized name already exists'
NO_VALUE_WITH_VALUES = 'A no-value tag definition cannot contain tag values'
MISSING_VALUES = 'At least one tag value is required'
EMPTY_UPDATE = 'At least one definition field must be provided'
LIBRARY_NOT_FOUND = 'Tag library not found'
DEFINITION_NOT_FOUND = 'Tag definition not found'
VALUE_NOT_FOUND = 'Tag value not found'
DEFINITION_IN_USE = 'Cannot delete a tag definition with values or active assignments'
VALUE_IN_USE = 'Cannot delete a tag value that is in use'
MULTI_TO_SINGLE = 'Cannot convert to single_select while resources have multiple assigned values'

LIBRARY_FIELDS = {
    'bucket_id',
    'bucket_key',
    'bucket_name',
    'status',
    'resource_types',
    'definition_count',
    'definition_capacity',
}
VALUE_FIELDS = {'value_id', 'display_value', 'normalized_value', 'status'}
USAGE_FIELDS = {'definition_id', 'active_value_count', 'active_usage_count', 'value_capacity'}


def _detail(resp):
    payload = resp.json()
    value = payload.get('detail') or payload.get('message')
    if isinstance(value, list) and value:
        message = str(value[0].get('msg') or '') if isinstance(value[0], dict) else str(value[0])
        return message.removeprefix('Value error, ')
    return value


def _conflict(resp):
    payload = resp.json()
    for key in ('detail', 'message'):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload if isinstance(payload, dict) else {}


def _find_int(payload, key):
    if isinstance(payload, dict):
        for child_key, child in payload.items():
            if child_key == key:
                try:
                    return int(child)
                except (TypeError, ValueError):
                    pass
            found = _find_int(child, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for child in payload:
            found = _find_int(child, key)
            if found is not None:
                return found
    return None


def _register_tag_cleanup(kind, key, path):
    register_asset(
        'tag_resource', f'{CASE_ID}:{kind}:{key}', key, owner_case_id=CASE_ID,
        cleanup={
            'identity': 'tenant_a_admin', 'service': 'config', 'method': 'DELETE',
            'path': path, 'allowed_statuses': [200, 404],
        },
    )


async def _delete_definition_clean(admin, bucket_id, definition_id, value_ids):
    for value_id in value_ids:
        removed = await admin.delete(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value_id)
        )
        assert_status(removed, (200, 404))
    deleted = await admin.delete(
        '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id)
    )
    assert_status(deleted, (200, 404))


async def _cleanup_stale_batch_definitions(admin, bucket_id):
    """Check headroom; a name prefix is never proof of cleanup ownership."""
    listed = await admin.get(f'/tag-libraries/{bucket_id}/definitions')
    assert_status(listed, 200)
    if len(listed.json()) > 96:
        from shared.asset_registry import AssetDependencyError
        raise AssetDependencyError('tags','definition_capacity',detail='Insufficient room for owned definitions; do not delete historical rows')


async def _exercise_assignment_conflicts(admin, run_id, bucket_id):
    created = await admin.post(
        '/tag-libraries/' + str(bucket_id) + '/definitions',
        json={
            'definition_name': run_id + '-multi-def',
            'selection_mode': 'multi_select',
            'initial_values': [run_id + '-mv1', run_id + '-mv2'],
        },
    )
    assert_status(created, 200)
    multi_def = created.json()
    multi_def_id = multi_def['definition_id']
    multi_value_ids = [value['value_id'] for value in multi_def['values']]
    _register_tag_cleanup('definition', multi_def_id, f'/tag-libraries/{bucket_id}/definitions/{multi_def_id}')
    for value_id in multi_value_ids:
        _register_tag_cleanup(
            'value', value_id,
            f'/tag-libraries/{bucket_id}/definitions/{multi_def_id}/values/{value_id}',
        )

    agent_id = admin.owned_agent_id

    existing = await admin.get('/tag-libraries/assignments/agent/' + str(agent_id))
    assert_status(existing,200)
    original_value_ids = [assignment['value_id'] for assignment in existing.json().get('assignments', [])]

    assigned = await admin.put(
        '/tag-libraries/assignments/agent/' + str(agent_id),
        json={'value_ids': multi_value_ids},
    )
    assert_status(assigned,200)

    try:
        converted = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(multi_def_id),
            json={'selection_mode': 'single_select'},
        )
        assert_status(converted, 409)
        conflict = _conflict(converted)
        assert conflict.get('message') == MULTI_TO_SINGLE
        assert conflict.get('details', {}).get('definition_id') == multi_def_id
        assert 'resources_with_multiple_values' in conflict.get('details', {})

        in_use = await admin.delete(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(multi_def_id) + '/values/' + str(multi_value_ids[0])
        )
        assert_status(in_use, 409)
        assert _conflict(in_use).get('message') == VALUE_IN_USE
    finally:
        await admin.put(
            '/tag-libraries/assignments/agent/' + str(agent_id),
            json={'value_ids': original_value_ids},
        )
        await _delete_definition_clean(admin, bucket_id, multi_def_id, multi_value_ids)


@pytest.mark.stage('D2')
@pytest.mark.case_id(CASE_ID)
async def test_tag_library_definition_value_crud(tenant_a_admin, tenant_a_dev):
    run_id = CASE_ID.lower() + '-' + uuid.uuid4().hex[:8]
    admin_token = tenant_a_admin.access_token
    dev_token = tenant_a_dev.access_token

    async with tag_contract_client(tenant_a_admin) as admin, client('config', token=dev_token) as dev:
        libs = await admin.get('/tag-libraries')
        assert_status(libs, 200)
        libraries = libs.json()
        assert isinstance(libraries, list) and libraries
        for library in libraries:
            assert LIBRARY_FIELDS <= set(library)
            assert library['definition_capacity'] == 100
        default_bucket = next(lib for lib in libraries if lib['bucket_key'] == 'default_resource')
        bucket_id = default_bucket['bucket_id']
        await _cleanup_stale_batch_definitions(admin, bucket_id)

        readonly = await dev.get('/tag-libraries')
        assert_status(readonly, 200)
        readonly_definitions = await dev.get(f'/tag-libraries/{bucket_id}/definitions')
        assert_status(readonly_definitions, 200)
        denied = await dev.post(f'/tag-libraries/{bucket_id}/definitions', json={
            'definition_name': run_id + '-denied',
            'selection_mode': 'multi_select', 'initial_values': [run_id + '-denied-value'],
        })
        assert_status(denied, 403)
        assert _detail(denied) == MANAGE_DENIED
        after_denial = await dev.get(f'/tag-libraries/{bucket_id}/definitions')
        assert_status(after_denial, 200)
        assert after_denial.json() == readonly_definitions.json()

        create = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions',
            json={
                'definition_name': run_id + '-def-a',
                'selection_mode': 'multi_select',
                'initial_values': [run_id + '-v1', run_id + '-v2'],
            },
        )
        assert_status(create, 200)
        definition = create.json()
        definition_id = definition['definition_id']
        assert definition['selection_mode'] == 'multi_select'
        assert definition['status'] == 'active'
        assert definition['value_capacity'] == 1000
        assert isinstance(definition['values'], list)
        assert len(definition['values']) == 2
        initial_value_ids = [value['value_id'] for value in definition['values']]
        _register_tag_cleanup('definition', definition_id, f'/tag-libraries/{bucket_id}/definitions/{definition_id}')
        for value_id in initial_value_ids:
            _register_tag_cleanup(
                'value', value_id,
                f'/tag-libraries/{bucket_id}/definitions/{definition_id}/values/{value_id}',
            )
        for value in definition['values']:
            assert VALUE_FIELDS <= set(value)

        dup = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions',
            json={
                'definition_name': '  ' + run_id + '-DEF-A  ',
                'selection_mode': 'multi_select',
                'initial_values': [run_id + '-dup'],
            },
        )
        assert_status(dup, 409)
        assert _conflict(dup).get('message') == DUPLICATE_MESSAGE

        no_value_with_values = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions',
            json={
                'definition_name': run_id + '-no-value',
                'selection_mode': 'no_value',
                'initial_values': [run_id + '-x'],
            },
        )
        assert_status(no_value_with_values, 422)
        assert _detail(no_value_with_values) == NO_VALUE_WITH_VALUES

        multi_without_values = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions',
            json={'definition_name': run_id + '-missing', 'selection_mode': 'multi_select'},
        )
        assert_status(multi_without_values, 422)
        assert _detail(multi_without_values) == MISSING_VALUES

        listed = await admin.get('/tag-libraries/' + str(bucket_id) + '/definitions')
        assert_status(listed, 200)
        listed_ids = [item['definition_id'] for item in listed.json()]
        assert definition_id in listed_ids

        renamed = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id),
            json={'definition_name': run_id + '-def-a-renamed'},
        )
        assert_status(renamed, 200)
        assert renamed.json()['definition_name'] == run_id + '-def-a-renamed'

        empty_update = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id),
            json={},
        )
        assert_status(empty_update, 400)
        assert _detail(empty_update) == EMPTY_UPDATE

        disabled = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/status',
            json={'status': 'disabled'},
        )
        assert_status(disabled, 200)
        assert disabled.json()['status'] == 'disabled'

        active = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/status',
            json={'status': 'active'},
        )
        assert_status(active, 200)
        assert active.json()['status'] == 'active'

        ordered = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/order',
            json={'sort_order': 42},
        )
        assert_status(ordered, 200)
        assert ordered.json()['sort_order'] == 42

        topped = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/top'
        )
        assert_status(topped, 200)
        assert topped.json()['sort_order'] == 0

        definition_usage = await admin.get(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/usage'
        )
        assert_status(definition_usage, 200)
        usage = definition_usage.json()
        assert USAGE_FIELDS <= set(usage)
        assert usage['definition_id'] == definition_id

        value_created = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values',
            json={'display_value': run_id + '-v3', 'sort_order': 3},
        )
        assert_status(value_created, 200)
        value3 = value_created.json()
        value3_id = value3['value_id']
        _register_tag_cleanup(
            'value', value3_id,
            f'/tag-libraries/{bucket_id}/definitions/{definition_id}/values/{value3_id}',
        )
        assert VALUE_FIELDS <= set(value3)
        assert value3['status'] == 'active'

        value_dup = await admin.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values',
            json={'display_value': '  ' + run_id + '-V3  '},
        )
        assert_status(value_dup, 409)
        assert _conflict(value_dup).get('message') == DUPLICATE_MESSAGE

        value_renamed = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value3_id),
            json={'display_value': run_id + '-v3-renamed'},
        )
        assert_status(value_renamed, 200)
        assert value_renamed.json()['display_value'] == run_id + '-v3-renamed'
        assert value_renamed.json()['normalized_value'] == (run_id + '-v3-renamed').lower()

        value_disabled = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value3_id) + '/status',
            json={'status': 'disabled'},
        )
        assert_status(value_disabled, 200)
        assert value_disabled.json()['status'] == 'disabled'

        value_ordered = await admin.patch(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value3_id) + '/order',
            json={'sort_order': 9},
        )
        assert_status(value_ordered, 200)
        assert value_ordered.json()['sort_order'] == 9

        value_usage = await admin.get(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value3_id) + '/usage'
        )
        assert_status(value_usage, 200)
        value_usage_body = value_usage.json()
        assert {'value_id', 'active_usage_count'} <= set(value_usage_body)
        assert value_usage_body['value_id'] == value3_id

        missing_bucket_id = absent_numeric_id(__name__ + ':bucket')
        missing_definition_id = absent_numeric_id(__name__ + ':definition')
        missing_value_id = absent_numeric_id(__name__ + ':value')
        missing_bucket = await admin.get(f'/tag-libraries/{missing_bucket_id}/definitions')
        assert_status(missing_bucket, 404)
        assert _detail(missing_bucket) == LIBRARY_NOT_FOUND

        missing_definition = await admin.get(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(missing_definition_id) + '/usage'
        )
        assert_status(missing_definition, 404)
        assert _detail(missing_definition) == DEFINITION_NOT_FOUND

        missing_value = await admin.get(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(missing_value_id) + '/usage'
        )
        assert_status(missing_value, 404)
        assert _detail(missing_value) == VALUE_NOT_FOUND

        delete_definition_in_use = await admin.delete(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id)
        )
        assert_status(delete_definition_in_use, 409)
        delete_conflict = _conflict(delete_definition_in_use)
        assert delete_conflict.get('message') == DEFINITION_IN_USE
        assert delete_conflict.get('details', {}).get('definition_id') == definition_id

        await _exercise_assignment_conflicts(admin, run_id, bucket_id)

        for value_id in list(initial_value_ids) + [value3_id]:
            removed = await admin.delete(
                '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id) + '/values/' + str(value_id)
            )
            assert_status(removed, 200)
            assert removed.json() == {'success': True}

        delete_definition = await admin.delete(
            '/tag-libraries/' + str(bucket_id) + '/definitions/' + str(definition_id)
        )
        assert_status(delete_definition, 200)
        assert delete_definition.json() == {'success': True}
