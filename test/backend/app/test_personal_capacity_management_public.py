# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-MGMT-03 preserves public scope, subject and error envelopes."""

from unittest.mock import AsyncMock

import pytest
from management.api.knowledge_base import quota as module
from management.services.knowledge_base.personal_capacity_access import (
    PersonalQuotaDenied,
)
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.app.test_quota_app import client, mock_personal_auth  # noqa: F401

PATHS = [('users', '/api/capacity/personal/users'), ('details', '/api/capacity/personal/users/subject/kbs'),
         ('summary', '/api/capacity/personal/summary')]


@pytest.mark.parametrize(('operation', 'path'), PATHS)
def test_foreign_su_keeps_actual_actor_and_only_details_subject(client, mock_personal_auth, mocker, operation, path):  # noqa: F811
    mock_personal_auth(role='SU', tenant_id='home', user_id='actual')
    service = mocker.patch.object(module, 'personal_capacity_operation', new_callable=AsyncMock, return_value={'total': 0})
    guard = mocker.patch('permissions.depends.has_permission', side_effect=AssertionError('Old RBAC cache'))
    response = client.get(path, params={'tenant_id': 'target'})
    assert response.status_code == 200 and response.json() == {'total': 0}
    expected = {}
    if operation == 'users':
        expected['options'] = {'page': 1, 'page_size': 20, 'sort_by': 'total_bytes', 'sort_order': 'desc', 'keyword': None}
    if operation == 'details':
        expected = {'subject': 'subject', 'options': {'page': 1, 'page_size': 20}}
    service.assert_awaited_once_with(operation, 'target', ServicePrincipal('actual', 'home'), **expected)
    guard.assert_not_called()


@pytest.mark.parametrize(('operation', 'path'), PATHS)
@pytest.mark.parametrize(('error', 'status'), [(PersonalQuotaDenied('Cannot access personal KB capacity for another tenant'), 403),
    (ScopeDenied(), 403), (DeadlineExceeded(), 500)])
def test_live_refusal_and_root_deadline_preserve_error_contract(client, mock_personal_auth, mocker, operation, path, error, status, caplog):  # noqa: F811
    mock_personal_auth()
    service = mocker.patch.object(module, 'personal_capacity_operation', new_callable=AsyncMock, side_effect=error)
    response = client.get(path)
    assert response.status_code == status and service.await_count == 1
    if status == 500:
        assert not [r for r in caplog.records if r.levelname == 'ERROR' and r.name == module.logger.name]


def test_invalid_sort_remains_400_after_authorized_service(client, mock_personal_auth, mocker):  # noqa: F811
    mock_personal_auth()
    service = mocker.patch.object(module, 'personal_capacity_operation', new_callable=AsyncMock,
        side_effect=ValueError('sort_order must be asc or desc'))
    response = client.get(PATHS[0][1], params={'sort_order': 'sideways'})
    assert response.status_code == 400 and response.json()['message'] == 'sort_order must be asc or desc'
    assert service.await_count == 1
