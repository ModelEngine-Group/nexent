# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-SELF-03 keeps the authenticated actor and public error contract."""

from unittest.mock import AsyncMock

import pytest
from management.api.knowledge_base import quota as module
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.app.test_quota_app import client, mock_personal_auth  # noqa: F401


def test_me_cannot_select_another_subject_or_tenant(client, mock_personal_auth, mocker):  # noqa: F811
    mock_personal_auth(role='DEV', tenant_id='home', user_id='actor')
    service = mocker.patch.object(module, 'personal_self_capacity', new_callable=AsyncMock, return_value={'used_bytes': 5})
    guard = mocker.patch('permissions.depends.has_permission', side_effect=AssertionError('No capacity permission required'))
    result = client.get('/api/capacity/personal/me?tenant_id=foreign&user_id=other')
    assert result.status_code == 200 and result.json() == {'used_bytes': 5}
    service.assert_awaited_once_with(ServicePrincipal('actor', 'home'))
    guard.assert_not_called()


@pytest.mark.parametrize(('error', 'status'), [(ScopeDenied(), 403), (DeadlineExceeded(), 500)])
def test_me_current_identity_refusal_and_deadline(client, mock_personal_auth, mocker, caplog, error, status):  # noqa: F811
    mock_personal_auth()
    service = mocker.patch.object(module, 'personal_self_capacity', new_callable=AsyncMock, side_effect=error)
    result = client.get('/api/capacity/personal/me')
    assert result.status_code == status and service.await_count == 1
    if status == 500:
        assert 'Error getting personal KB capacity' in result.json()['message']
        assert not [r for r in caplog.records if r.levelname == 'ERROR' and r.name == module.logger.name]
