"""Audit entries recorded on successful northbound API key operations.

Feature-scoped companion to ``test_northbound_app.py``.
"""

import logging
import sys
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Agent management is outside the HTTP boundary exercised in this module.
with pytest.MonkeyPatch.context() as import_mocks:
    import_mocks.setitem(sys.modules, "management.services.agent.service", MagicMock())
    from apps.northbound_app import router

from services.northbound_service import NorthboundContext

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def _stub_northbound_caller(mocker):
    """Stub the AK/SK identity resolution and role lookup for a northbound caller."""
    mocker.patch(
        "apps.northbound_app._get_northbound_context",
        new_callable=AsyncMock,
        return_value=NorthboundContext(
            request_id="req-1",
            tenant_id="tenant-1",
            user_id="admin-1",
            authorization="Bearer access-key",
            token_id=7,
        ),
    )
    mocker.patch("apps.northbound_app.get_user_role_by_tenant", return_value="ADMIN")


def test_api_users_batch_create_records_audit_entry(caplog, mocker):
    """Batch API user creation records the request intent, never the plaintext keys."""
    _stub_northbound_caller(mocker)
    mocker.patch("apps.northbound_app.create_api_users_batch", return_value=[
        {"user_id": "u-1", "role": "USER", "group_id": 5, "group_name": "default",
         "api_key": "nexent-secret-1"},
        {"user_id": "u-2", "role": "USER", "group_id": 5, "group_name": "default",
         "api_key": "nexent-secret-2"},
    ])

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/nb/v1/api-users/batch",
            headers={"Authorization": "Bearer access-key", "X-Request-Id": "req-1"},
            json={"role": "USER", "group_id": 5, "count": 2},
        )

    assert response.status_code == HTTPStatus.CREATED
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=northbound_api_users_batch_create" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert ('details={"role":"USER","group_id":5,"count":2,"user_ids":["u-1","u-2"],'
            '"request_id":"req-1"}') in messages[0]
    assert "nexent-secret-1" not in messages[0]
    assert "nexent-secret-2" not in messages[0]


def test_northbound_api_key_refresh_records_audit_entry(caplog, mocker):
    """Refreshing a key through the northbound API records the caller, never the new key."""
    _stub_northbound_caller(mocker)
    mocker.patch("apps.northbound_app.refresh_user_api_key", return_value={
        "user_id": "user-1",
        "email": "api.user@example.com",
        "api_key": "nexent-secret-key",
        "revoked_count": 1,
    })

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/nb/v1/api-keys/refresh",
            headers={"Authorization": "Bearer access-key", "X-Request-Id": "req-1"},
            json={"email": "api.user@example.com"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=northbound_api_key_refresh" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert ('details={"target_user_id":"user-1","target_email":"api.user@example.com",'
            '"revoked_count":1,"request_id":"req-1"}') in messages[0]
    assert "nexent-secret-key" not in messages[0]


def test_northbound_api_key_revoke_records_audit_entry(caplog, mocker):
    """Revoking keys through the northbound API records the caller and the revoked count."""
    _stub_northbound_caller(mocker)
    mocker.patch("apps.northbound_app.revoke_user_api_keys", return_value={
        "user_id": "user-1",
        "email": None,
        "api_key": None,
        "revoked_count": 2,
    })

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.delete(
            "/nb/v1/api-keys?user_id=user-1",
            headers={"Authorization": "Bearer access-key", "X-Request-Id": "req-1"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=northbound_api_key_revoke" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert ('details={"target_user_id":"user-1","target_email":null,"revoked_count":2,'
            '"request_id":"req-1"}') in messages[0]
