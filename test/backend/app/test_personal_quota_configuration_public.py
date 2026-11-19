# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Default personal quota preserves public identity, scope and error envelopes."""

from unittest.mock import AsyncMock

import pytest
from management.api.knowledge_base import quota as module
from management.services.knowledge_base.personal_quota_configuration import (
    InvalidPersonalQuotaPayload,
    PersonalQuotaDenied,
)
from nexent.storage.errors import DeadlineExceeded

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.app.test_quota_app import client, mock_personal_auth  # noqa: F401


@pytest.fixture
def configuration(mocker):
    return mocker.patch.object(module, 'personal_quota_configuration', new_callable=AsyncMock,
                              return_value={'quota_limit_bytes': 5, 'quota_limit_readable': '5 B', 'unlimited': False})


@pytest.mark.parametrize(('method', 'operation', 'payload'), [('get', 'read', None),
    ('put', 'write', {'quota_limit_bytes': 5})])
def test_foreign_su_preserves_actual_identity(client, mock_personal_auth, configuration, method, operation, payload):  # noqa: F811
    mock_personal_auth(role='SU', tenant_id='home', user_id='actor')
    kwargs = {'json': payload} if payload is not None else {}
    result = getattr(client, method)('/api/capacity/personal/default-quota?tenant_id=target', **kwargs)
    assert result.status_code == 200
    expected = (operation, 'target', ServicePrincipal('actor', 'home'))
    if operation == 'write':
        configuration.assert_awaited_once_with(*expected, {'quota_limit_bytes': 5, 'unlimited': False})
    else:
        configuration.assert_awaited_once_with(*expected)


def test_asset_owner_foreign_default_denied_by_live_scope(client, mock_personal_auth, configuration):  # noqa: F811
    mock_personal_auth(role='ASSET_OWNER', tenant_id='home')
    configuration.side_effect = PersonalQuotaDenied('Cannot access personal KB capacity for another tenant')
    assert client.get('/api/capacity/personal/default-quota?tenant_id=target').status_code == 403
    configuration.assert_awaited_once_with('read', 'target', ServicePrincipal('admin-user-id', 'home'))


@pytest.mark.parametrize('method', ['get', 'put'])
@pytest.mark.parametrize(('error', 'status'), [(PersonalQuotaDenied('Missing required permission: kb.capacity:read'), 403),
                                             (DeadlineExceeded(), 500)])
def test_live_refusal_and_deadline_preserve_envelope(client, mock_personal_auth, configuration, method, error, status, caplog):  # noqa: F811
    mock_personal_auth()
    configuration.side_effect = error
    kwargs = {'json': {'quota_limit_bytes': 5}} if method == 'put' else {}
    response = getattr(client, method)('/api/capacity/personal/default-quota', **kwargs)
    assert response.status_code == status and configuration.await_count == 1
    if status == 403:
        assert response.json()['message'] == str(error)
    else:
        assert 'personal KB default quota' in response.json()['message']
        assert not [r for r in caplog.records if r.levelname == 'ERROR' and r.name == module.logger.name]


def test_missing_value_still_rejected_by_authorized_service(client, mock_personal_auth, configuration):  # noqa: F811
    mock_personal_auth()
    configuration.side_effect = InvalidPersonalQuotaPayload('Provide quota_limit_bytes or unlimited=true')
    assert client.put('/api/capacity/personal/default-quota', json={}).status_code == 400
    assert configuration.await_count == 1


def test_default_routes_do_not_use_legacy_permission_cache(client, mock_personal_auth, configuration, mocker):  # noqa: F811
    mock_personal_auth()
    guard = mocker.patch('permissions.depends.has_permission', side_effect=AssertionError('Legacy permission cache'))
    assert client.get('/api/capacity/personal/default-quota').status_code == 200
    assert client.put('/api/capacity/personal/default-quota', json={'quota_limit_bytes': 5}).status_code == 200
    assert configuration.await_count == 2
    guard.assert_not_called()
