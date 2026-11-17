# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant deprovision admits every private scope before disabling memberships."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.permission.identity import tenants


@pytest.fixture
def cascade(monkeypatch):
    events, plans = [], {'u1': object(), 'u2': object()}
    monkeypatch.setattr(tenants, 'get_single_config_info', Mock(return_value={'config_value': 'tenant'}))
    monkeypatch.setattr(tenants, 'deactivate_tenant_models', AsyncMock())
    monkeypatch.setattr(tenants, 'get_users_by_tenant_id', Mock(return_value={'users': [{'user_id': u} for u in plans]}))

    async def prepare(owner, tenant_id, actor_id, *, purpose):
        assert tenant_id == 'target' and actor_id == 'su' and purpose == 'tenant_deletion'
        events.append('prepare-' + owner)
        return plans[owner]

    async def delete(owner, tenant_id, *, actor_id, membership_removed, private_cleanup):
        assert actor_id == 'su' and tenant_id == 'target' and membership_removed
        assert private_cleanup is plans[owner]
        events.append('delete-' + owner)

    monkeypatch.setattr(tenants.user_service, 'prepare_private_cleanup', AsyncMock(side_effect=prepare))
    monkeypatch.setattr(tenants.user_service, 'delete_user_and_cleanup', AsyncMock(side_effect=delete))
    monkeypatch.setattr(tenants, 'soft_delete_users_by_tenant_id', Mock(side_effect=lambda *args: events.append('bulk')))
    for name in ('query_groups_by_tenant', 'query_all_agent_info_by_tenant_id', 'get_mcp_records_by_tenant',
                 'query_invitations_by_tenant', 'get_all_configs_by_tenant_id'):
        monkeypatch.setattr(tenants, name, Mock(return_value=[]))
    monkeypatch.setattr(tenants, 'query_groups_by_tenant', Mock(return_value={'data': []}))
    shared_plan = object()

    async def prepare_shared(tenant_id, actor_id):
        assert (tenant_id, actor_id) == ('target', 'su')
        events.append('prepare-shared')
        return shared_plan

    async def execute_shared(plan):
        assert plan is shared_plan
        events.append('execute-shared')
        return {'total': 1, 'succeeded': 0, 'failed': 0, 'pending': 1}

    monkeypatch.setattr(tenants, 'prepare_tenant_cleanup', AsyncMock(side_effect=prepare_shared))
    monkeypatch.setattr(tenants, 'execute_cleanup', AsyncMock(side_effect=execute_shared))
    async def unlink(tenant_id, actor_id):
        assert (tenant_id, actor_id) == ('target', 'su')
        events.append('unlink-datamate')
        return {'total': 1, 'succeeded': 1, 'failed': 0, 'pending': 0}

    monkeypatch.setattr(tenants, 'unlink_datamate_for_tenant', AsyncMock(side_effect=unlink))
    monkeypatch.setattr(tenants, '_delete_skills_for_tenant', Mock())
    return SimpleNamespace(**locals())


async def test_all_private_authority_precedes_bulk_disable_and_pending_parents_survive(cascade):
    assert await tenants.delete_tenant('target', 'su') is True
    assert cascade.events[:5] == ['prepare-shared', 'unlink-datamate', 'prepare-u1', 'prepare-u2', 'bulk']
    assert set(cascade.events[5:-1]) == {'delete-u1', 'delete-u2'}
    assert cascade.events[-1] == 'execute-shared'
    assert not hasattr(tenants, 'delete_knowledge_record')

