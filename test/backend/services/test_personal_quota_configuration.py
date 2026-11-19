# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-DEFAULT-01 preserves default quota behavior with live scoped SI."""

from contextlib import contextmanager

import pytest
from nexent.storage.errors import ScopeDenied

from infrastructure import tenant_quota_read as records_module
from infrastructure.knowledge_collection_metadata import (
    bind_collection_permissions,
    permissions_table,
)
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401

KEY = 'PERSONAL_KB_QUOTA_DEFAULT'


@pytest.fixture
def personal(quota):  # noqa: F811
    from management.services.knowledge_base.personal_quota_configuration import (
        PersonalQuotaConfiguration,
    )

    from infrastructure.quota_write import bind_quota_write_records

    s = quota
    s.update('cleanse_accounts', user_roles=['SU'])
    permissions_table.create(s.engine, checkfirst=True)
    with s.engine.begin() as conn:
        conn.execute(permissions_table.insert(), [
            {'role_permission_id': i, 'user_role': role, 'permission_category': 'RESOURCE',
             'permission_type': kind, 'permission_subtype': operation}
            for i, role, kind, operation in [(1, 'SU', 'KB.CAPACITY', 'READ'), (2, 'SU', 'kb.capacity', 'manage'),
                (3, 'OPS', 'resource.inventory', 'read'), (4, 'ASSET_OWNER', 'kb.capacity', 'manage')]])

    @contextmanager
    def ports(actor, *, context, writable):
        with s.ports(actor, context=context) as (identity, _):
            permissions = bind_collection_permissions(actor, s.engine)
            handles = [permissions]

            def records(tenant):
                s.opened.append((actor, tenant))
                port = bind_quota_write_records(actor, tenant, s.engine, writable=writable)
                handles.append(port)
                return port

            try:
                yield identity, permissions, records
            finally:
                for port in handles:
                    port.close()

    s.configuration = PersonalQuotaConfiguration(ports=ports)

    def read(tenant='tenant-a'):
        return s.configuration.run('read', tenant, s.actor, {}, context=context())

    def write(payload, tenant='tenant-a'):
        return s.configuration.run('write', tenant, s.actor, payload, context=context())

    s.read_default, s.write_default = read, write
    return s


def test_missing_default_is_unlimited(personal):
    assert personal.read_default() == {'quota_limit_bytes': None, 'quota_limit_readable': None, 'unlimited': True}


@pytest.mark.parametrize(('raw', 'expected'), [('8', 8), ('0', 0), ('-3', -3), ('broken', 0)])
def test_existing_default_parse_rules(personal, raw, expected):
    s = personal
    with s.engine.begin() as conn:
        conn.execute(records_module.config_table.insert(), {'tenant_config_id': 20, 'tenant_id': 'tenant-a',
            'config_key': KEY, 'config_value': raw, 'delete_flag': 'N'})
    assert s.read_default()['quota_limit_bytes'] == expected


def test_actual_su_can_write_foreign_namespace_with_own_audit(personal):
    s = personal
    assert s.write_default({'quota_limit_bytes': 7}, 'tenant-b') == {'quota_limit_bytes': 7, 'quota_limit_readable': '7 B'}
    with s.engine.connect() as conn:
        row = conn.execute(records_module.config_table.select().where(records_module.config_table.c.config_key == KEY)).mappings().one()
    assert row['tenant_id'] == 'tenant-b' and row['created_by'] == s.actor.user_id and row['user_id'] == s.actor.user_id
    assert s.actor.tenant_id == 'tenant-a'


def test_first_update_and_unlimited_soft_deletes_only_first(personal):
    s = personal
    with s.engine.begin() as conn:
        conn.execute(records_module.config_table.insert(), [
            {'tenant_config_id': i, 'tenant_id': 'tenant-a', 'config_key': KEY, 'config_value': str(i), 'delete_flag': 'N'}
            for i in (20, 21)])
    s.write_default({'quota_limit_bytes': 9})
    assert s.read_default()['quota_limit_bytes'] == 9
    assert s.write_default({'unlimited': True, 'quota_limit_bytes': 123})['quota_limit_bytes'] is None
    assert s.read_default()['quota_limit_bytes'] == 21


def test_legacy_negative_write_and_read_are_unchanged(personal):
    s = personal
    assert s.write_default({'quota_limit_bytes': -3})['quota_limit_bytes'] == -3
    assert s.read_default()['quota_limit_bytes'] == -3


def test_inventory_permission_is_read_only_alternative(personal):
    s = personal
    s.update('cleanse_accounts', user_roles=['OPS'])
    assert s.read_default()['unlimited'] is True
    s.opened.clear()
    with pytest.raises(ScopeDenied):
        s.write_default({'quota_limit_bytes': 1})
    assert not s.opened


def test_asset_owner_does_not_gain_foreign_personal_scope(personal):
    s = personal
    s.update('cleanse_accounts', user_roles=['ASSET_OWNER'])
    with pytest.raises(ScopeDenied):
        s.write_default({'quota_limit_bytes': 1}, 'tenant-b')
    assert not s.opened


def test_role_without_permission_is_denied_before_metadata(personal):
    s = personal
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    with pytest.raises(ScopeDenied):
        s.read_default()
    assert not s.opened


def test_revoked_membership_is_denied(personal):
    s = personal
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.read_default()
    assert not s.opened


def test_permission_revocation_before_commit_rolls_back(personal, mocker):
    s = personal
    original, calls = s.configuration._authorize, []

    def authorize(*args):
        calls.append(True)
        if len(calls) == 2:
            raise ScopeDenied()
        return original(*args)

    mocker.patch.object(s.configuration, '_authorize', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.write_default({'quota_limit_bytes': 8})
    with s.engine.connect() as conn:
        assert not conn.execute(records_module.config_table.select().where(records_module.config_table.c.config_key == KEY)).first()


def test_read_only_binding_cannot_mutate_configuration(personal):
    from nexent.storage.models import FieldPatch

    from infrastructure.quota_write import CONFIGS, bind_quota_write_records

    s = personal
    port = bind_quota_write_records(s.actor, 'tenant-a', s.engine, writable=False)
    try:
        with pytest.raises(ScopeDenied):
            port.patch(CONFIGS, 1, FieldPatch(set_values={'config_value': '99'}), context=context())
    finally:
        port.close()


def test_missing_payload_checked_after_permission_before_metadata(personal):
    from management.services.knowledge_base.personal_quota_configuration import (
        InvalidPersonalQuotaPayload,
    )

    s = personal
    with pytest.raises(InvalidPersonalQuotaPayload, match='Provide quota_limit_bytes or unlimited=true'):
        s.write_default({})
    assert not s.opened
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    with pytest.raises(ScopeDenied):
        s.write_default({})
    assert not s.opened
