# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only live issuer/owner identities are exposed for a deprovision admission."""

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.knowledge_admission import OWNER_CLEANUP_IDENTITIES as DATASET
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, FieldPatch, PageRequest, RecordQuery

from infrastructure import knowledge_owner_cleanup as module
from test.backend.infrastructure.test_record_store import context


@pytest.fixture
def identities(monkeypatch):
    metadata = sa.MetaData()
    members = sa.Table('members', metadata, sa.Column('user_tenant_id', sa.Integer, primary_key=True),
                       sa.Column('user_id', sa.String), sa.Column('tenant_id', sa.String), sa.Column('delete_flag', sa.String))
    accounts = sa.Table('accounts', metadata, sa.Column('account_id', sa.Integer, primary_key=True),
                        sa.Column('user_id', sa.String), sa.Column('user_roles', sa.JSON), sa.Column('delete_flag', sa.String))
    monkeypatch.setattr(module, 'memberships', members)
    monkeypatch.setattr(module, 'accounts', accounts)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(members.insert(), [{'user_tenant_id': n, 'user_id': u, 'tenant_id': t, 'delete_flag': 'N'}
            for n, u, t in ((1, 'admin', 'operator'), (2, 'owner', 'target'), (3, 'other', 'target'), (4, 'owner', 'other-tenant'))])
        connection.execute(accounts.insert(), [{'account_id': n, 'user_id': u, 'user_roles': r, 'delete_flag': 'N'}
            for n, u, r in ((1, 'admin', ['SU']), (2, 'owner', ['USER']), (3, 'other', ['ADMIN']))])
    actor = SimpleNamespace(user_id='admin', tenant_id='target')
    records = module.bind_owner_cleanup_identities(actor, 'owner', engine)
    try:
        yield records, engine, members, accounts
    finally:
        records.close()
        engine.dispose()


def test_projection_preserves_real_actor_tenant_and_never_enumerates_other_identities(identities):
    records, _, _, _ = identities
    page = records.query(DATASET, RecordQuery(), PageRequest(limit=4), context=context())
    assert [(row['user_id'], row['tenant_id'], row['user_roles']) for row in page.items] == [
        ('admin', 'operator', ['SU']), ('owner', 'target', ['USER']),
    ]
    assert all(row['scope_tenant_id'] == 'target' for row in page.items)
    query = RecordQuery(where=Comparison('user_id', 'eq', 'other'))
    assert not records.query(DATASET, query, PageRequest(), context=context()).items
    with pytest.raises(ScopeDenied):
        records.patch(DATASET, 1, FieldPatch(set_values={'user_roles': ['ADMIN']}), context=context())


@pytest.mark.parametrize('kind', ['membership', 'account'])
def test_removed_identity_cannot_mint_new_cleanup(kind, identities):
    records, engine, members, accounts = identities
    table = members if kind == 'membership' else accounts
    with engine.begin() as connection:
        connection.execute(table.update().where(table.c.user_id == 'admin').values(delete_flag='Y'))
    assert [row['user_id'] for row in records.query(DATASET, RecordQuery(), PageRequest(), context=context()).items] == ['owner']
