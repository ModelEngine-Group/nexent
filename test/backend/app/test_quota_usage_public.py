# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public usage preserves actor scope, refusal and total-deadline responses."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from contracts.errors.exceptions import TokenExpiredError
from management.api.knowledge_base import quota as module
from management.services.knowledge_base import inventory
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.app.test_quota_app import client  # noqa: F401


@pytest.fixture
def usage(mocker):
    mocker.patch.object(module, 'get_current_user_id', return_value=('actual', 'actual-tenant'))
    mocker.patch.object(module, '_get_user_role', side_effect=AssertionError('Legacy role query'))
    constructor = mocker.patch.object(module, 'TenantQuotaUsage')
    reader = constructor.return_value.read = AsyncMock(return_value=(('SU',), {'total_bytes': 27}))
    return reader


def test_foreign_privileged_actor_is_not_replaced_by_resource_tenant(client, usage):  # noqa: F811
    response = client.get('/api/tenants/target/quota/usage?force_refresh=true')
    assert response.status_code == 200 and response.json() == {'total_bytes': 27}
    assert usage.await_args.args == ('target', ServicePrincipal('actual', 'actual-tenant'))
    assert usage.await_args.kwargs['force_refresh'] is True
    assert usage.await_args.kwargs['context'].cancelled.is_set()


def test_foreign_refusal_keeps_existing_public_message(client, usage):  # noqa: F811
    usage.side_effect = ScopeDenied()
    response = client.get('/api/tenants/target/quota/usage')
    assert response.status_code == 403
    assert response.json()['message'] == 'Cannot access usage data for another tenant'
    assert usage.await_count == 1


def test_token_expiry_stays_unauthorized_and_never_opens_reader(client, usage, mocker):  # noqa: F811
    mocker.patch.object(module, 'get_current_user_id', side_effect=TokenExpiredError('expired'))
    response = client.get('/api/tenants/target/quota/usage')
    assert response.status_code == 401
    usage.assert_not_awaited()


def test_identity_scope_refusal_before_tenant_resolution_stays_forbidden(client, usage, mocker):  # noqa: F811
    mocker.patch.object(module, 'get_current_user_id', side_effect=ScopeDenied())
    response = client.get('/api/tenants/target/quota/usage')
    assert response.status_code == 403
    usage.assert_not_awaited()


def test_root_deadline_cancels_producer_and_logs_once(client, usage, mocker, caplog):  # noqa: F811
    contexts, closed = [], []

    async def stalled(*args, **kwargs):
        contexts.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    usage.side_effect = stalled
    mocker.patch.object(inventory, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, monotonic() + .03, **kwargs))
    response = client.get('/api/tenants/target/quota/usage')
    assert response.status_code == 504 and response.json() == {'message': 'Knowledge base list timed out'}
    assert usage.await_count == 1 and closed == [True] and contexts[0].cancelled.is_set()
    assert sum('knowledge_list_timeout' in record.message for record in caplog.records) == 1
    assert not any(record.levelname == 'ERROR' for record in caplog.records)
