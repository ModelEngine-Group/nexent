"""Audit entries recorded on successful northbound user creation.

Feature-scoped companion to ``test_northbound_app.py``. The branch has no
``/api-users/batch`` or key-management endpoints yet, so the single carrier is
``POST /nb/v1/users``; the plaintext password in the payload must never reach
the audit line.
"""

import logging
from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# The global conftest sets up the third-party mocks required at import time.
from apps.northbound_app import router
from services.northbound_service import NorthboundContext

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_northbound_user_create_records_audit_entry(caplog, mocker):
    """Northbound user creation records the caller, target and intent, never the password."""
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
    mocker.patch(
        "apps.northbound_app.admin_create_user",
        new_callable=AsyncMock,
        return_value={"user_id": "u-1", "email": "api.user@example.com", "role": "USER"},
    )

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/nb/v1/users",
            headers={"Authorization": "Bearer access-key", "X-Request-Id": "req-1"},
            json={"email": "api.user@example.com", "password": "secret1", "role": "USER"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=northbound_api_users_batch_create" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert ('details={"target_user_id":"u-1","target_email":"api.user@example.com",'
            '"role":"USER","request_id":"req-1"}') in messages[0]
    assert "secret1" not in messages[0]
