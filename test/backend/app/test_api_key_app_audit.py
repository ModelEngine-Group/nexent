"""Audit entries recorded on successful platform API key operations.

Feature-scoped companion to ``test_api_key_app.py``.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api_key_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_refresh_api_key_success_records_audit_entry(caplog, mocker):
    """Refreshing a target user's key records the operator, never the new plaintext key."""
    mocker.patch("apps.api_key_app.get_current_user_context",
                 return_value=("admin-1", "tenant-1", "ADMIN"))
    mocker.patch("apps.api_key_app.refresh_user_api_key", return_value={
        "user_id": "user-1",
        "email": "api.user@example.com",
        "api_key": "nexent-secret-key",
        "revoked_count": 2,
    })

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/api-keys/refresh",
            headers={"Authorization": "Bearer token"},
            json={"email": "api.user@example.com"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=api_key_refresh" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert ('details={"target_user_id":"user-1","target_email":"api.user@example.com",'
            '"revoked_count":2}') in messages[0]
    assert "nexent-secret-key" not in messages[0]
    assert response.json()["data"]["api_key"] == "nexent-secret-key"


def test_revoke_api_keys_success_records_audit_entry(caplog, mocker):
    """Revoking a target user's keys records the operator and the revoked count."""
    mocker.patch("apps.api_key_app.get_current_user_context",
                 return_value=("admin-1", "tenant-1", "ADMIN"))
    mocker.patch("apps.api_key_app.revoke_user_api_keys", return_value={
        "user_id": "user-1",
        "email": None,
        "api_key": None,
        "revoked_count": 3,
    })

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.delete(
            "/api-keys?user_id=user-1",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=api_key_revoke" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"target_user_id":"user-1","target_email":null,"revoked_count":3}' in messages[0]
