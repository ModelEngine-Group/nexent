# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Platform overview retains HTTP contracts and a bounded async lifetime."""

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
def overview(mocker):
    mocker.patch.object(module, 'get_current_user_id', return_value=('platform-admin', 'actual-tenant'))
    assert not hasattr(module, '_get_user_role')
    assert not hasattr(module, '_require_platform_quota_manager')
    read = mocker.patch.object(module, 'PlatformQuotaOverview').return_value.read = AsyncMock(
        return_value={'tenant_count': 0, 'tenants': []})
    return read


def test_platform_overview_passes_actual_actor_and_closes_context(client, overview):  # noqa: F811
    response = client.get('/api/platform/quota/overview')
    assert response.status_code == 200 and response.json() == {'tenant_count': 0, 'tenants': []}
    assert overview.await_args.args == (ServicePrincipal('platform-admin', 'actual-tenant'),)
    assert overview.await_args.kwargs['context'].cancelled.is_set()


def test_platform_overview_denial_preserves_role_message(client, overview):  # noqa: F811
    overview.side_effect = ScopeDenied()
    response = client.get('/api/platform/quota/overview')
    assert response.status_code == 403
    assert response.json() == {'message': 'This operation requires SU or ASSET_OWNER role'}
    assert overview.await_count == 1


def test_platform_token_expiry_never_opens_service(client, overview, mocker):  # noqa: F811
    mocker.patch.object(module, 'get_current_user_id', side_effect=TokenExpiredError('expired'))
    assert client.get('/api/platform/quota/overview').status_code == 401
    overview.assert_not_awaited()


def test_platform_root_deadline_preserves_500_without_duplicate_error(client, overview, mocker, caplog):  # noqa: F811
    contexts, closed = [], []

    async def stalled(*args, **kwargs):
        contexts.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    overview.side_effect = stalled
    mocker.patch.object(inventory, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, monotonic() + .03, **kwargs))
    response = client.get('/api/platform/quota/overview')
    assert response.status_code == 500 and response.json()['message'].startswith('Error getting platform overview:')
    assert overview.await_count == 1 and closed == [True] and contexts[0].cancelled.is_set()
    assert sum('knowledge_list_timeout' in record.message for record in caplog.records) == 1
    assert not any(record.levelname == 'ERROR' for record in caplog.records)
