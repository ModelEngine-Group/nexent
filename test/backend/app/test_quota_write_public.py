# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public quota mutations retain paths, payloads, actors and response envelopes."""

import pytest
from contracts.errors.exceptions import PlatformQuotaConflictError, TokenExpiredError
from fastapi.testclient import TestClient
from management.api.knowledge_base import quota as api
from management.services.knowledge_base.quota_write import (
    InvalidQuotaWarning,
    QuotaWriteDenied,
)
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from backend.http.server.app_factory import create_app
from infrastructure.agentos_identity import ServicePrincipal

CASES = [
    ('put', '/tenants/target/quota', 'update', 'target', {'hard_limit_mb': 1}, 'Quota configuration updated successfully'),
    ('delete', '/tenants/target/quota', 'remove', 'target', {}, 'Quota configuration removed successfully'),
    ('put', '/platform/quota/capacity', 'capacity', None, {'capacity_gb': 1}, 'Platform capacity updated successfully'),
    ('delete', '/platform/quota/capacity', 'capacity', None, {}, 'Platform capacity removed successfully'),
    ('put', '/platform/quota/tenants/target', 'hard', 'target', {'hard_limit_gb': 1}, 'Tenant hard quota updated successfully'),
    ('delete', '/platform/quota/tenants/target', 'remove-platform', 'target', {}, 'Tenant hard quota removed successfully'),
]


@pytest.fixture
def endpoint(mocker):
    app = create_app(title='Quota mutation test', root_path='/api', enable_monitoring=False)
    app.include_router(api.tenant_quota_router)
    app.include_router(api.platform_quota_router)
    auth = mocker.patch.object(api, 'get_current_user_id', return_value=('actor', 'actual-tenant'))
    write = mocker.patch.object(api, 'write_quota')
    write.return_value = {'hard_limit_bytes': 1}
    with TestClient(app) as client:
        yield client, write, auth


@pytest.mark.parametrize(('method', 'path', 'action', 'tenant', 'payload', 'message'), CASES)
def test_public_write_preserves_success_and_actual_identity(endpoint, method, path, action, tenant, payload, message):
    client, write, _ = endpoint
    response = client.request(method, '/api' + path, json=payload if method == 'put' else None,
                              headers={'Authorization': 'signed-user'})
    assert response.status_code == 200 and response.json()['message'] == message
    write.assert_awaited_once_with(action, tenant, ServicePrincipal('actor', 'actual-tenant'), payload)
    if action in {'update', 'hard'} or method == 'put':
        assert response.json()['hard_limit_bytes'] == 1
    if path.startswith('/platform/quota/tenants/'):
        assert response.json()['tenant_id'] == 'target'


@pytest.mark.parametrize(('method', 'path', 'action', 'tenant', 'payload', 'message'), CASES)
@pytest.mark.parametrize(('error', 'status'), [(QuotaWriteDenied('Cannot modify quota config for another tenant'), 403),
    (ScopeDenied(), 403), (RuntimeError('database down'), 500), (DeadlineExceeded(), 500)])
def test_public_error_and_timeout_contract(endpoint, method, path, action, tenant, payload, message, error, status, caplog):
    client, write, _ = endpoint
    write.side_effect = error
    response = client.request(method, '/api' + path, json=payload if method == 'put' else None)
    assert response.status_code == status
    assert write.await_count == 1
    if isinstance(error, DeadlineExceeded):
        assert not [r for r in caplog.records if r.levelname == 'ERROR' and r.name == api.logger.name]
    elif isinstance(error, RuntimeError):
        assert 'database down' in response.json()['message']


@pytest.mark.parametrize(('path', 'error'), [('/tenants/target/quota', 'TenantQuotaBelowUsage'),
    ('/platform/quota/tenants/target', 'PlatformCapacityExceeded'),
    ('/platform/quota/capacity', 'PlatformCapacityBelowAllocation')])
def test_conflicts_keep_original_error_envelope(endpoint, path, error):
    client, write, _ = endpoint
    write.side_effect = PlatformQuotaConflictError('original message', error, {'remaining_allocatable_bytes': 10})
    response = client.put('/api' + path, json={'hard_limit_mb': 1})
    assert response.status_code == 409
    assert response.json() == {'error': error, 'message': 'original message', 'remaining_allocatable_bytes': 10}


def test_invalid_warning_remains_bad_request(endpoint):
    client, write, _ = endpoint
    write.side_effect = InvalidQuotaWarning('warning threshold must be lower')
    response = client.put('/api/tenants/target/quota', json={'warning_threshold_pct': 95})
    assert response.status_code == 400 and 'warning threshold must be lower' in response.json()['message']


@pytest.mark.parametrize(('method', 'path', 'action', 'tenant', 'payload', 'message'), CASES)
def test_expired_identity_never_starts_write(endpoint, method, path, action, tenant, payload, message):
    client, write, auth = endpoint
    auth.side_effect = TokenExpiredError('expired')
    response = client.request(method, '/api' + path, json=payload if method == 'put' else None)
    assert response.status_code == 401
    write.assert_not_awaited()
