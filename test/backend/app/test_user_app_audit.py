"""Audit entries recorded on successful user management operations.

Feature-scoped companion to ``test_user_app.py``: only the audit assertions
live here; the legacy module keeps its endpoint-coverage suites.
"""

import importlib.machinery
import logging
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http import HTTPStatus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Import-time isolation mirrors test_user_app.py: nexent SDK modules and
# storage/search clients must not reach live services during import.
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules["boto3"] = boto3_module
sys.modules["nexent"] = MagicMock()
sys.modules["nexent.core"] = MagicMock()
sys.modules["nexent.core.agents"] = MagicMock()
sys.modules["nexent.core.agents.agent_model"] = MagicMock()
sys.modules["nexent.storage"] = MagicMock()
sys.modules["nexent.storage.storage_client_factory"] = MagicMock()
sys.modules["nexent.storage.minio_config"] = MagicMock()
sys.modules["nexent.memory"] = MagicMock()
sys.modules["nexent.memory.memory_service"] = MagicMock()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch("nexent.storage.storage_client_factory.create_storage_client_from_config",
      return_value=storage_client_mock).start()
patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None).start()
patch("backend.database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.MinioClient", return_value=minio_mock).start()

from apps.user_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_update_user_success_records_audit_entry(caplog):
    """Test successful user update records a security audit entry with the changed fields"""
    with patch("apps.user_app.get_current_user_context") as mock_get_user, \
         patch("apps.user_app.update_user_for_requester") as mock_update_user:
        mock_get_user.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_update_user.return_value = {"user_id": "user-9", "role": "ADMIN"}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.put(
                "/users/user-9",
                headers={"Authorization": "Bearer token"},
                json={"role": "ADMIN"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=user_update" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"target_user_id":"user-9","changes":{"role":"ADMIN"}}' in messages[0]


def test_delete_user_success_records_audit_entry(caplog):
    """Test successful user deletion records a security audit entry with the target user/tenant"""
    with patch("apps.user_app.get_current_user_id") as mock_get_user, \
         patch("apps.user_app.get_user_tenant_by_user_id") as mock_get_user_tenant, \
         patch("apps.user_app.delete_user_and_cleanup") as mock_delete:
        mock_get_user.return_value = ("admin-1", "operator-tenant")
        mock_get_user_tenant.return_value = {"user_id": "user-9", "tenant_id": "tenant-9"}
        mock_delete.return_value = None

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.delete(
                "/users/user-9",
                headers={"Authorization": "Bearer token"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=user_delete" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=operator-tenant" in messages[0]
    assert 'details={"target_user_id":"user-9","target_tenant_id":"tenant-9"}' in messages[0]
