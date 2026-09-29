from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from shared.http import assert_status, client

CASE_ID = 'API-AUTO-3113089C9736B2A4'
SERVICE = 'config'

DEFINITION_LIMIT = 100
VALUE_LIMIT = 1000
ASSIGNMENT_LIMIT = 100


def _definition_payload(name, mode, values):
    return {'definition_name': name, 'selection_mode': mode, 'initial_values': values}


def _conflict_detail(body):
    if not isinstance(body, dict):
        return {}, ''
    # Current app_factory serializes domain conflicts under ``message``;
    # older FastAPI paths used ``detail``.  Accept both wrappers while keeping
    # the business message/details assertions exact.
    detail = body.get('detail')
    if not isinstance(detail, dict):
        detail = body.get('message')
    if not isinstance(detail, dict):
        return {}, str(detail or '')
    return detail.get('details') or {}, detail.get('message') or ''


async def _active_definition_count(api, bucket_id):
    response = await api.get(f'/tag-libraries/{bucket_id}/definitions')
    assert_status(response, 200)
    return len(response.json())


async def _discover_tool_resource_id(api):
    for path in ('/tools', '/tool/list'):
        response = await api.get(path)
        if response.status_code == 404:
            continue
        assert_status(response, 200)
        payload = response.json()
        records = payload if isinstance(payload, list) else []
        if not records and isinstance(payload, dict):
            data = payload.get('data')
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                records = data.get('tools') or data.get('list') or data.get('items') or []
            else:
                records = payload.get('tools') or payload.get('list') or payload.get('items') or []
        for record in records:
            if isinstance(record, dict):
                value = record.get('tool_id') or record.get('id')
                if value is not None:
                    return int(value)
    raise AssertionError('no tool resource available for assignment-capacity assertions')


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
async def test_tag_capacity_and_single_select_constraints(tenant_a_admin, tag_asset_guard):
    run = uuid4().hex[:8]
    created_values_by_definition = {}

    async with client(SERVICE, token=tenant_a_admin.access_token) as api:
        libraries = await api.get('/tag-libraries')
        assert_status(libraries, 200)
        default = next((lib for lib in libraries.json() if lib.get('bucket_key') == 'default_resource'), None)
        assert default is not None, 'default_resource tag library not found'
        bucket_id = default['bucket_id']

        initial_count = await _active_definition_count(api, bucket_id)

        value_def = await api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json=_definition_payload(f'api_auto_{run}_values', 'multi_select', [f'api_auto_{run}_values_v0']),
        )
        assert_status(value_def, 200)
        value_def_id = value_def.json()['definition_id']
        value_ids = [v['value_id'] for v in value_def.json()['values']]
        created_values_by_definition[value_def_id] = list(value_ids)

        single_def = await api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json=_definition_payload(
                f'api_auto_{run}_single',
                'single_select',
                [f'api_auto_{run}_ss_a', f'api_auto_{run}_ss_b'],
            ),
        )
        assert_status(single_def, 200)
        single_def_id = single_def.json()['definition_id']
        single_value_ids = [v['value_id'] for v in single_def.json()['values']]
        created_values_by_definition[single_def_id] = list(single_value_ids)

        while await _active_definition_count(api, bucket_id) < DEFINITION_LIMIT - 1:
            index = len(created_values_by_definition)
            name = f'api_auto_{run}_def_{index}'
            created = await api.post(
                f'/tag-libraries/{bucket_id}/definitions',
                json=_definition_payload(name, 'multi_select', [f'{name}_v0']),
            )
            assert_status(created, 200)
            did = created.json()['definition_id']
            created_values_by_definition[did] = [v['value_id'] for v in created.json()['values']]

        race_a = api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json=_definition_payload(f'api_auto_{run}_race_a', 'multi_select', [f'api_auto_{run}_race_a_v0']),
        )
        race_b = api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json=_definition_payload(f'api_auto_{run}_race_b', 'multi_select', [f'api_auto_{run}_race_b_v0']),
        )
        results = await asyncio.gather(race_a, race_b)
        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 409], f'expected one 200 and one 409, got {statuses}'
        winner = next(r for r in results if r.status_code == 200)
        winner_id = winner.json()['definition_id']
        created_values_by_definition[winner_id] = [v['value_id'] for v in winner.json()['values']]

        assert await _active_definition_count(api, bucket_id) == DEFINITION_LIMIT

        overflow = await api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json=_definition_payload(f'api_auto_{run}_overflow_def', 'multi_select', ['x']),
        )
        assert_status(overflow, 409)
        details, message = _conflict_detail(overflow.json())
        assert message == 'Tag definition capacity exceeded'
        assert details.get('scope') == 'definition'
        assert details.get('limit') == DEFINITION_LIMIT

        while len(value_ids) < VALUE_LIMIT:
            idx = len(value_ids)
            created_value = await api.post(
                f'/tag-libraries/{bucket_id}/definitions/{value_def_id}/values',
                json={'display_value': f'api_auto_{run}_v_{idx}', 'sort_order': idx},
            )
            assert_status(created_value, 200)
            value_ids.append(created_value.json()['value_id'])
        created_values_by_definition[value_def_id] = list(value_ids)

        overflow_value = await api.post(
            f'/tag-libraries/{bucket_id}/definitions/{value_def_id}/values',
            json={'display_value': f'api_auto_{run}_v_overflow', 'sort_order': VALUE_LIMIT},
        )
        assert_status(overflow_value, 409)
        details, message = _conflict_detail(overflow_value.json())
        assert message == 'Tag value capacity exceeded'
        assert details.get('scope') == 'value'
        assert details.get('limit') == VALUE_LIMIT

        tool_resource_id = await _discover_tool_resource_id(api)

        assigned = await api.put(
            f'/tag-libraries/assignments/tool/{tool_resource_id}',
            json={'value_ids': value_ids[:ASSIGNMENT_LIMIT]},
        )
        assert_status(assigned, 200)
        assert assigned.json()['assignment_count'] == ASSIGNMENT_LIMIT

        overflow_assignment = await api.put(
            f'/tag-libraries/assignments/tool/{tool_resource_id}',
            json={'value_ids': value_ids[:ASSIGNMENT_LIMIT + 1]},
        )
        assert_status(overflow_assignment, 409)
        details, message = _conflict_detail(overflow_assignment.json())
        assert message == 'Resource tag assignment capacity exceeded'
        assert details.get('scope') == 'assignment'
        assert details.get('limit') == ASSIGNMENT_LIMIT

        single_first = await api.put(
            f'/tag-libraries/assignments/tool/{tool_resource_id}',
            json={'value_ids': [single_value_ids[0]]},
        )
        assert_status(single_first, 200)
        assert single_first.json()['assignment_count'] == 1

        single_conflict = await api.put(
            f'/tag-libraries/assignments/tool/{tool_resource_id}',
            json={'value_ids': single_value_ids},
        )
        assert_status(single_conflict, (400, 409))

        single_get = await api.get(f'/tag-libraries/assignments/tool/{tool_resource_id}')
        assert_status(single_get, 200)
        single_assignments = single_get.json()['assignments']
        single_scoped = [a for a in single_assignments if a.get('definition_id') == single_def_id]
        assert len(single_scoped) == 1

        cleared = await api.put(
            f'/tag-libraries/assignments/tool/{tool_resource_id}',
            json={'value_ids': []},
        )
        assert_status(cleared, 200)
        assert cleared.json()['assignment_count'] == 0

        for did in reversed(list(created_values_by_definition)):
            for vid in reversed(created_values_by_definition[did]):
                try:
                    del_resp = await api.delete(f'/tag-libraries/{bucket_id}/definitions/{did}/values/{vid}')
                    assert_status(del_resp, (200, 404))
                except Exception:
                    pass
            try:
                del_def = await api.delete(f'/tag-libraries/{bucket_id}/definitions/{did}')
                assert_status(del_def, 200)
            except Exception:
                pass

        assert await _active_definition_count(api, bucket_id) == initial_count
