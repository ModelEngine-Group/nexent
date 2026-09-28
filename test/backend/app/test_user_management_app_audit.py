"""Audit entries recorded on successful user account lifecycle operations.

Feature-scoped companion to ``test_user_management_app.py``: audit assertions
live here so the legacy module does not grow past its existing size.
"""

import importlib.machinery
import logging
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Import-time isolation mirrors test_user_management_app.py: the app pulls in
# storage and search clients that must not reach live services during import.
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules["boto3"] = boto3_module

patch("botocore.client.BaseClient._make_api_call", return_value={}).start()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch("nexent.storage.storage_client_factory.create_storage_client_from_config",
      return_value=storage_client_mock).start()
patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None).start()
patch("backend.database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.MinioClient", return_value=minio_mock).start()
patch("backend.database.client.minio_client", minio_mock).start()
patch("elasticsearch.Elasticsearch", return_value=MagicMock()).start()

from http import HTTPStatus  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.user_management_app import router  # noqa: E402

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_signup_success_records_audit_entry(caplog, mocker):
    """Successful registration records the operator identity, never the password."""
    mock_signup = mocker.patch("apps.user_management_app.signup_user_with_invitation")
    mock_signup.return_value = {
        "user": {"id": "u-1", "email": "new@example.com", "role": "USER"},
        "session": None,
        "registration_type": "user",
    }

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/user/signup",
            json={
                "email": "new@example.com",
                "password": "password123",
                "invite_code": "INVITE123",
            },
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=user_signup" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=u-1" in messages[0]
    assert "email=new@example.com" in messages[0]
    assert '"registration_type":"user"' in messages[0]
    assert "password123" not in messages[0]


def test_signin_success_records_audit_entry(caplog, mocker):
    """Successful login records the operator identity, never the session tokens."""
    mock_signin = mocker.patch("apps.user_management_app.signin_user")
    mock_signin.return_value = {
        "message": "Login successful",
        "data": {
            "user": {"id": "u-2", "email": "user@example.com", "role": "USER"},
            "session": {"access_token": "secret-token", "refresh_token": "secret-refresh"},
        },
    }

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/user/signin",
            json={"email": "user@example.com", "password": "password123"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=user_signin" in messages[0]
    assert "user_id=u-2" in messages[0]
    assert "email=user@example.com" in messages[0]
    assert "secret-token" not in messages[0]
    assert "password123" not in messages[0]


def test_logout_success_records_audit_entry(caplog, mocker):
    """Successful logout records the resolved operator and tenant."""
    mocker.patch("apps.user_management_app.get_authorized_client", return_value=MagicMock())
    mocker.patch("apps.user_management_app.get_current_user_id", return_value=("u-3", "t-3"))

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post("/user/logout", headers={"Authorization": "Bearer token"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=user_logout" in messages[0]
    assert "user_id=u-3" in messages[0]
    assert "tenant_id=t-3" in messages[0]


def test_account_revoke_success_records_audit_entry(caplog, mocker):
    """Successful account revocation records the revoked account owner."""
    user = MagicMock()
    user.user_metadata = {"role": "user"}
    mocker.patch("apps.user_management_app.delete_user_and_cleanup", new_callable=AsyncMock)
    mocker.patch("apps.user_management_app.validate_token", return_value=(True, user))
    mocker.patch("apps.user_management_app.get_current_user_id", return_value=("user123", "tenant456"))

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post("/user/revoke", headers={"Authorization": "Bearer token"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=account_revoke" in messages[0]
    assert "user_id=user123" in messages[0]
    assert "tenant_id=tenant456" in messages[0]


def test_token_create_records_token_id_but_not_secret(caplog, mocker):
    """Token creation records only the token id; the access key never reaches the log."""
    mock_create_token = mocker.patch("apps.user_management_app.create_token")
    mock_create_token.return_value = {
        "token_id": 7,
        "access_key": "nexent-secret-key",
        "user_id": "u-4",
    }
    mocker.patch("apps.user_management_app.get_current_user_id", return_value=("u-4", "t-4"))

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post("/user/tokens", headers={"Authorization": "Bearer test-jwt-token"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=token_create" in messages[0]
    assert "user_id=u-4" in messages[0]
    assert "tenant_id=t-4" in messages[0]
    assert 'details={"token_id":7}' in messages[0]
    assert "nexent-secret-key" not in messages[0]


def test_token_delete_success_records_audit_entry(caplog, mocker):
    """Successful token deletion records the operator and the deleted token id."""
    mocker.patch("apps.user_management_app.delete_token", return_value=True)
    mocker.patch("apps.user_management_app.get_current_user_id", return_value=("u-5", "t-5"))

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.delete("/user/tokens/3", headers={"Authorization": "Bearer test-jwt-token"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=token_delete" in messages[0]
    assert "user_id=u-5" in messages[0]
    assert 'details={"token_id":3}' in messages[0]


def test_password_update_success_records_audit_entry(caplog, mocker):
    """Password change records the operator identity, never the passwords."""
    mocker.patch("apps.user_management_app.update_password", new_callable=AsyncMock)
    mocker.patch("apps.user_management_app.get_current_user_id", return_value=("u-6", "t-6"))

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.put(
            "/user/password",
            json={"old_password": "OldPass123", "new_password": "NewPass456"},
            headers={"Authorization": "Bearer test-jwt-token"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=password_update" in messages[0]
    assert "user_id=u-6" in messages[0]
    assert "tenant_id=t-6" in messages[0]
    assert "OldPass123" not in messages[0]
    assert "NewPass456" not in messages[0]
