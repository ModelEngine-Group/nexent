# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only admitted PRIVATE commands whose target identity is disabled are discoverable."""

import pytest
import sqlalchemy as sa
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery

from infrastructure.rdb import knowledge_base_dispatch as module
from test.backend.infrastructure.test_record_store import context


@pytest.fixture
def pending(monkeypatch):
    metadata = sa.MetaData()
    knowledge = sa.Table('kb', metadata, sa.Column('knowledge_id', sa.Integer, primary_key=True),
        *(sa.Column(name, sa.String) for name in ('tenant_id', 'index_name', 'created_by', 'updated_by',
                                                 'ingroup_permission', 'knowledge_sources', 'delete_flag')),
        sa.Column('deletion_request', sa.JSON))
    accounts = sa.Table('accounts', metadata, sa.Column('id', sa.Integer, primary_key=True),
                        sa.Column('user_id', sa.String), sa.Column('delete_flag', sa.String))
    memberships = sa.Table('members', metadata, sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.String), sa.Column('tenant_id', sa.String), sa.Column('delete_flag', sa.String))
    monkeypatch.setattr(module, 'knowledge', knowledge)
    monkeypatch.setattr(module, 'accounts', accounts)
    monkeypatch.setattr(module, 'memberships', memberships)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    value = {'schema_version': 1, 'knowledge_id': 1, 'index_name': 'private', 'user_id': 'admin', 'phase': 'files',
             'owner_cleanup': {'owner_user_id': 'owner', 'purpose': 'user_deletion', 'actor_tenant_id': 'operator'}}
    with engine.begin() as conn:
        conn.execute(knowledge.insert(), {'knowledge_id': 1, 'tenant_id': 'target', 'index_name': 'private', 'created_by': 'owner',
            'updated_by': 'admin', 'ingroup_permission': 'PRIVATE', 'knowledge_sources': 'elasticsearch', 'delete_flag': 'N',
            'deletion_request': value})
        conn.execute(accounts.insert(), {'id': 1, 'user_id': 'owner', 'delete_flag': 'Y'})
        conn.execute(memberships.insert(), {'id': 1, 'user_id': 'owner', 'tenant_id': 'target', 'delete_flag': 'Y'})
    records = module.bind_base_dispatch(engine)
    try:
        yield records, engine, knowledge, accounts, memberships, value
    finally:
        records.close()
        engine.dispose()


def test_disabled_owner_preserves_actual_issuer_and_only_minimum_dispatch_fields(pending):
    records, *_ = pending
    (row,) = records.query(module.DATASET, RecordQuery(), PageRequest(), context=context()).items
    assert row == {'knowledge_id': 1, 'tenant_id': 'target', 'index_name': 'private', 'user_id': 'admin',
                       'owner_user_id': 'owner', 'purpose': 'user_deletion', 'delete_flag': 'N', 'cleanup_kind': 'owner'}
    with pytest.raises(ScopeDenied):
        records.patch(module.DATASET, 1, FieldPatch(set_values={'user_id': 'owner'}), context=context())
    with pytest.raises(InvalidInput):
        records.query(module.DATASET, RecordQuery(fields=('deletion_request',)), PageRequest(), context=context())


@pytest.mark.parametrize('kind', ['account', 'membership'])
def test_live_or_ambiguous_target_does_not_start_before_identity_revocation(pending, kind):
    records, engine, _, accounts, memberships, _ = pending
    table = accounts if kind == 'account' else memberships
    with engine.begin() as conn:
        conn.execute(table.update().values(delete_flag='N'))
    assert not records.query(module.DATASET, RecordQuery(), PageRequest(), context=context()).items


@pytest.mark.parametrize('kind', ['account', 'membership'])
def test_additional_live_identity_prevents_background_execution(pending, kind):
    records, engine, _, accounts, memberships, _ = pending
    table = accounts if kind == 'account' else memberships
    values = {'id': 2, 'user_id': 'owner', 'delete_flag': 'N'}
    if kind == 'membership':
        values['tenant_id'] = 'target'
    with engine.begin() as conn:
        conn.execute(table.insert().values(**values))
    assert not records.query(module.DATASET, RecordQuery(), PageRequest(), context=context()).items


@pytest.mark.parametrize('changes', [
    {'phase': 'deleted'}, {'owner_cleanup': None}, {'user_id': None},
    {'owner_cleanup': {'owner_user_id': 'foreign', 'purpose': 'user_deletion'}},
    {'owner_cleanup': {'owner_user_id': 'owner', 'purpose': 'arbitrary'}},
])
def test_terminal_unadmitted_or_wrong_scope_is_not_discovered(pending, changes):
    records, engine, knowledge, _, _, value = pending
    with engine.begin() as conn:
        conn.execute(knowledge.update().values(deletion_request={**value, **changes}))
    assert not records.query(module.DATASET, RecordQuery(), PageRequest(), context=context()).items


@pytest.mark.parametrize('live_member', [False, True])
def test_tenant_scope_waits_for_bulk_member_revocation_without_needing_creator_identity(pending, live_member):
    records, engine, knowledge, _, memberships, value = pending
    value = {**value, 'owner_cleanup': None, 'tenant_cleanup': {'actor_tenant_id': 'operator'}}
    with engine.begin() as conn:
        conn.execute(knowledge.update().values(created_by='long-departed', ingroup_permission='EDIT', deletion_request=value))
        if live_member:
            conn.execute(memberships.update().values(delete_flag='N'))
    page = records.query(module.DATASET, RecordQuery(), PageRequest(), context=context())
    if live_member:
        assert not page.items
    else:
        (row,) = page.items
        assert row['cleanup_kind'] == 'tenant' and row['user_id'] == 'admin' and row['tenant_id'] == 'target'
        assert row['owner_user_id'] is None and row['purpose'] == 'tenant_deletion'
