# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The real user orchestrator prepares authority before revoking identities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.permission.identity import users


@pytest.fixture
def deletion(monkeypatch):
    events, plan = [], object()

    async def prepare(*args, **kwargs):
        events.append('prepare')
        return plan

    async def execute(actual):
        assert actual is plan
        events.append('execute')
        return {'total': 1, 'succeeded': 0, 'failed': 0, 'pending': 1}

    preparation, execution = AsyncMock(side_effect=prepare), AsyncMock(side_effect=execute)
    monkeypatch.setattr(users, 'prepare_private_cleanup', preparation)
    monkeypatch.setattr(users, 'execute_cleanup', execution)
    for name in ('remove_user_from_all_groups', 'soft_delete_all_configs_by_user_id',
                 'soft_delete_all_conversations_by_user', 'soft_delete_all_oauth_accounts_by_user_id'):
        monkeypatch.setattr(users, name, Mock(return_value=0))
    membership = Mock(side_effect=lambda *args: events.append('membership') or True)
    monkeypatch.setattr(users, 'soft_delete_user_tenant_by_user_id', membership)
    monkeypatch.setattr(users, 'soft_delete_tokens_by_user', Mock(side_effect=lambda *args: events.append('tokens')))
    monkeypatch.setattr(users, 'delete_account', Mock(side_effect=lambda *args: events.append('account')))
    return SimpleNamespace(**locals())


@pytest.mark.parametrize('actor_id', ['admin', None])
async def test_prepare_then_revoke_then_execute_under_original_actor(deletion, actor_id):
    result = await users.delete_user_and_cleanup('owner', 'tenant', actor_id=actor_id)
    assert deletion.events == ['prepare', 'membership', 'tokens', 'account', 'execute']
    deletion.preparation.assert_awaited_once_with('owner', 'tenant', actor_id or 'owner')
    assert result == {'total': 1, 'succeeded': 0, 'failed': 0, 'pending': 1}


async def test_tenant_prepared_plan_is_not_readmitted_after_bulk_deactivation(deletion):
    await users.delete_user_and_cleanup('owner', 'tenant', actor_id='admin', membership_removed=True,
                                        private_cleanup=deletion.plan)
    deletion.preparation.assert_not_awaited()
    deletion.membership.assert_not_called()
    assert deletion.events == ['tokens', 'account', 'execute']


async def test_core_failure_never_executes_prepared_resource_deletion(deletion):
    deletion.membership.return_value = False
    deletion.membership.side_effect = None
    with pytest.raises(ValueError, match='not found'):
        await users.delete_user_and_cleanup('owner', 'tenant', actor_id='admin')
    deletion.execution.assert_not_awaited()
    users.delete_account.assert_not_called()


async def test_preparation_failure_still_revokes_credentials_without_impersonation(deletion):
    deletion.preparation.side_effect = RuntimeError('prepare failed')
    assert await users.delete_user_and_cleanup('owner', 'tenant', actor_id='admin') is None
    assert deletion.events == ['membership', 'tokens', 'account']
    deletion.execution.assert_not_awaited()
