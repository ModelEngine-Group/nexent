# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-MGMT-01 reads only selected active identity display through SI."""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied, Unavailable
from nexent.storage.models import PageRequest, RecordQuery

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def display(mocker):
    from management.services.knowledge_base.personal_capacity_display import (
        PersonalCapacityDisplay,
    )

    from infrastructure import personal_capacity_display as adapter

    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    metadata = sa.MetaData()
    accounts = sa.Table('display_accounts', metadata, sa.Column('account_id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.String), sa.Column('user_email', sa.String), sa.Column('delete_flag', sa.String))
    members = sa.Table('display_members', metadata, sa.Column('user_tenant_id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.String), sa.Column('tenant_id', sa.String), sa.Column('delete_flag', sa.String))
    oauth = adapter.oauth_table.to_metadata(metadata)
    metadata.create_all(engine)
    mocker.patch.object(adapter, 'accounts_table', accounts)
    mocker.patch.object(adapter, 'members_table', members)
    mocker.patch.object(adapter, 'oauth_table', oauth)
    actor = ServicePrincipal('actual', 'home')
    with engine.begin() as conn:
        conn.execute(accounts.insert(), [{'account_id': i, 'user_id': user, 'user_email': user+'@example.test', 'delete_flag': flag}
            for i, user, flag in [(1, 'one', 'N'), (2, 'two', 'N'), (3, 'inactive', 'Y')]])
        conn.execute(members.insert(), [{'user_tenant_id': i, 'user_id': user, 'tenant_id': 'elsewhere', 'delete_flag': flag}
            for i, user, flag in [(1, 'one', 'N'), (2, 'two', 'Y'), (3, 'inactive', 'N')]])
        conn.execute(oauth.insert(), [{'oauth_account_id': i, 'user_id': user, 'provider': provider, 'provider_username': name, 'delete_flag': flag}
            for i, user, provider, name, flag in [(1, 'one', 'cas', ' ', 'N'), (2, 'one', 'cas', ' First ', 'N'),
                (3, 'one', 'cas', 'Second', 'N'), (4, 'one', 'other', 'Provider', 'N'),
                (5, 'two', 'cas', 'Disabled member', 'N'), (6, 'inactive', 'cas', 'Kept optional display', 'N')]])
    opened, closed = [], []

    @contextmanager
    def ports(principal, tenant, *, context):
        opened.append((principal, tenant))
        records = adapter.bind_personal_capacity_display(principal, tenant, engine)
        try:
            yield records
        finally:
            records.close()
            closed.append(True)

    service = PersonalCapacityDisplay(ports=ports)
    yield SimpleNamespace(**locals())
    engine.dispose()


def test_selected_display_uses_active_membership_and_first_nonblank_cas(display):
    s = display
    emails, identities = s.service.read('resource', s.actor, ['one', 'two', 'inactive'], context=context())
    assert emails == {'one': 'one@example.test'}
    assert identities == {'one': {'cas_username': 'First'}, 'inactive': {'cas_username': 'Kept optional display'}}
    assert s.opened == [(s.actor, 'resource')] and s.closed == [True]


def test_unselected_identity_is_not_returned_and_port_is_readonly(display):
    s = display
    assert s.service.read('resource', s.actor, ['unknown'], context=context()) == ({}, {})
    port = s.adapter.bind_personal_capacity_display(s.actor, 'resource', s.engine)
    try:
        assert port.scope.actor_id == 'actual' and port.scope.tenant_id == 'resource' and not port.scope.system
        with pytest.raises(ScopeDenied):
            port.create(s.adapter.EMAILS, {}, context=context())
        result = port.query(s.adapter.EMAILS, RecordQuery(), PageRequest(limit=5), context=context())
        assert all(set(row) == {'account_id', 'user_id', 'user_email', 'tenant_id'} for row in result.items)
    finally:
        port.close()


def test_optional_cas_error_keeps_email_without_native_fallback(display, mocker):
    s = display
    original = s.service._rows

    def rows(records, dataset, subjects, ctx):
        if dataset == s.adapter.CAS:
            raise Unavailable()
        return original(records, dataset, subjects, ctx)

    mocker.patch.object(s.service, '_rows', side_effect=rows)
    assert s.service.read('resource', s.actor, ['one'], context=context()) == ({'one': 'one@example.test'}, {})


def test_email_failure_and_cas_scope_refusal_are_not_optional(display, mocker):
    s = display
    mocker.patch.object(s.service, '_rows', side_effect=Unavailable())
    with pytest.raises(Unavailable):
        s.service.read('resource', s.actor, ['one'], context=context())
    mocker.patch.object(s.service, '_rows', side_effect=[[], ScopeDenied()])
    with pytest.raises(ScopeDenied):
        s.service.read('resource', s.actor, ['one'], context=context())


def test_personal_catalog_dates_match_original_public_z_format(mocker):
    from infrastructure import tenant_quota_read as adapter
    from infrastructure.knowledge_catalog import knowledge

    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    knowledge.create(engine)
    mocker.patch.object(adapter, 'knowledge_table', knowledge)
    date = datetime(2026, 1, 2, 3, 4, 5)  # noqa: DTZ001 - The existing column stores naive timestamps.
    with engine.begin() as conn:
        conn.execute(knowledge.insert(), {'knowledge_id': 1, 'tenant_id': 'resource', 'index_name': 'one', 'update_time': date,
            'last_doc_update_time': date, 'version': 1, 'delete_flag': 'N'})
    port = adapter.bind_tenant_quota_records(ServicePrincipal('actual', 'home'), 'resource', engine, usage=True, personal=True)
    try:
        result = port.query(adapter.CATALOG, RecordQuery(), PageRequest(limit=1), context=context()).items[0]
        assert result['update_time'] == result['last_doc_update_time'] == '2026-01-02T03:04:05Z'
    finally:
        port.close()
        engine.dispose()
