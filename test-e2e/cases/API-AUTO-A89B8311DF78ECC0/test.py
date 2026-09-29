import uuid

import pytest

from database.client import get_db_session
from database.db_models import ResourceTagAssignment, SkillInfo
from database.tag_management_db import TagManagementDB
from shared.http import assert_status, client
from shared.factories.ownership import register_owned_http
from shared.factories.tags import register_tag_definition


CASE_ID = 'API-AUTO-A89B8311DF78ECC0'


def _run_id() -> str:
    return uuid.uuid4().hex[:12]


def _active_assignment_count(tenant_id: str, resource_id: str) -> int:
    with get_db_session() as session:
        return (
            session.query(ResourceTagAssignment)
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.resource_type == 'skill',
                ResourceTagAssignment.resource_id == resource_id,
                ResourceTagAssignment.delete_flag == 'N',
            )
            .count()
        )


def _soft_deleted_assignment_count(tenant_id: str, resource_id: str) -> int:
    with get_db_session() as session:
        return (
            session.query(ResourceTagAssignment)
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.resource_type == 'skill',
                ResourceTagAssignment.resource_id == resource_id,
                ResourceTagAssignment.delete_flag == 'Y',
            )
            .count()
        )


def _skill_delete_flag(tenant_id: str, skill_name: str) -> str:
    with get_db_session() as session:
        skill = (
            session.query(SkillInfo)
            .filter(
                SkillInfo.tenant_id == tenant_id,
                SkillInfo.skill_name == skill_name,
            )
            .first()
        )
        return skill.delete_flag if skill else None


def _assign_skill_tag(identity, skill_id: int, run_id: str) -> dict:
    tenant_id, actor_id = identity.tenant_id, identity.user_id
    libraries = TagManagementDB.list_libraries(tenant_id)
    bucket = next(
        (
            lib
            for lib in libraries
            if lib.get('status') == 'active'
            and 'skill' in (lib.get('resource_types') or [])
        ),
        None,
    )
    if bucket is None:
        raise AssertionError('no active tag library bound to skill resource type')
    bucket_id = bucket['bucket_id']
    library_code = bucket['bucket_key']
    definition = TagManagementDB.create_definition(
        tenant_id,
        bucket_id,
        'cleanup_' + run_id,
        'cleanup_' + run_id,
        'multi_select',
        ['value_' + run_id],
        None,
        actor_id,
    )
    register_tag_definition(identity, bucket_id, definition)
    value_id = definition['values'][0]['value_id']
    TagManagementDB.replace_resource_assignments(
        tenant_id,
        'skill',
        str(skill_id),
        library_code,
        [value_id],
        actor_id,
    )
    return {
        'bucket_id': bucket_id,
        'library_code': library_code,
        'definition_id': definition['definition_id'],
        'value_id': value_id,
    }


def _cleanup_definition(tenant_id: str, actor_id: str, tag: dict) -> None:
    TagManagementDB.delete_value(
        tenant_id, tag['bucket_id'], tag['definition_id'], tag['value_id'], actor_id
    )
    TagManagementDB.delete_definition(
        tenant_id, tag['bucket_id'], tag['definition_id'], actor_id
    )


async def _create_skill(identity, name: str) -> int:
    async with client('config', token=identity.access_token) as api:
        response = await api.post(
            '/skills',
            json={
                'name': name,
                'description': 'temporary skill for tag cascade cleanup test',
                'content': '# ' + name,
            },
        )
        assert_status(response, 201)
        # The successful POST establishes ownership even if response parsing fails.
        register_owned_http(identity, 'skills', name, '/skills/' + name)
        payload = response.json()
        assert payload.get('skill_id'), payload
        return int(payload['skill_id'])


async def _delete_skill(identity, name: str):
    async with client('config', token=identity.access_token) as api:
        return await api.delete('/skills/' + name)


@pytest.mark.asyncio
@pytest.mark.stage('D3')
@pytest.mark.case_id(CASE_ID)
async def test_delete_skill_cascades_soft_cleanup_of_tag_assignments_within_tenant(
    tenant_a_admin,
    tenant_b_admin,
):
    run_id = _run_id()
    name_a = 'skill_cascade_a_' + run_id
    name_b = 'skill_cascade_b_' + run_id

    skill_id_a = await _create_skill(tenant_a_admin, name_a)
    skill_id_b = await _create_skill(tenant_b_admin, name_b)

    tag_a = _assign_skill_tag(tenant_a_admin, skill_id_a, run_id)
    tag_b = _assign_skill_tag(tenant_b_admin, skill_id_b, run_id)

    assert _active_assignment_count(tenant_a_admin.tenant_id, str(skill_id_a)) == 1
    assert _active_assignment_count(tenant_b_admin.tenant_id, str(skill_id_b)) == 1

    try:
        response = await _delete_skill(tenant_a_admin, name_a)
        assert_status(response, 200)
        assert response.json() == {'message': 'Skill ' + name_a + ' deleted successfully'}

        async with client('config', token=tenant_a_admin.access_token) as api:
            missing = await api.get('/skills/' + name_a)
        assert_status(missing, 404)

        assert _skill_delete_flag(tenant_a_admin.tenant_id, name_a) == 'Y'

        assert _active_assignment_count(tenant_a_admin.tenant_id, str(skill_id_a)) == 0
        assert _soft_deleted_assignment_count(tenant_a_admin.tenant_id, str(skill_id_a)) == 1

        assert _active_assignment_count(tenant_b_admin.tenant_id, str(skill_id_b)) == 1
        assert _soft_deleted_assignment_count(tenant_b_admin.tenant_id, str(skill_id_b)) == 0
    finally:
        try:
            await _delete_skill(tenant_b_admin, name_b)
        except Exception:
            pass
        _cleanup_definition(tenant_a_admin.tenant_id, tenant_a_admin.user_id, tag_a)
        _cleanup_definition(tenant_b_admin.tenant_id, tenant_b_admin.user_id, tag_b)
