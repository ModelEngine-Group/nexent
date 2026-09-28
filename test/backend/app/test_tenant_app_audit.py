"""Audit entries recorded on successful tenant lifecycle operations.

Feature-scoped companion to ``test_tenant_app.py``: only the audit assertions
live here; the legacy module keeps its endpoint-coverage suites.
"""

import importlib.machinery
import logging
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http import HTTPStatus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Import-time isolation mirrors test_tenant_app.py: storage/search clients and
# DB drivers must not reach live services during import.
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules["boto3"] = boto3_module
sys.modules["psycopg2"] = MagicMock()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch("nexent.storage.storage_client_factory.create_storage_client_from_config",
      return_value=storage_client_mock).start()
patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None).start()
patch("backend.database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.MinioClient", return_value=minio_mock).start()
patch("elasticsearch.Elasticsearch", return_value=MagicMock()).start()

from apps.tenant_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_create_success_records_audit_entry(caplog):
    """Test successful tenant creation records a security audit entry"""
    with patch("apps.tenant_app.get_current_user_id") as mock_get_user, \
         patch("apps.tenant_app.create_tenant") as mock_create:
        mock_get_user.return_value = ("user-1", "tenant-1")
        mock_create.return_value = {"tenant_id": "new-tenant"}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post("/tenants", json={"tenant_name": "New tenant"})

    assert response.status_code == HTTPStatus.CREATED
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=tenant_create" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"tenant_id":"new-tenant","tenant_name":"New tenant"}' in messages[0]


def test_update_success_records_audit_entry(caplog):
    """Test successful tenant update records a security audit entry"""
    with patch("apps.tenant_app.get_current_user_id") as mock_get_user, \
         patch("apps.tenant_app.update_tenant_info") as mock_update:
        mock_get_user.return_value = ("user-1", "tenant-1")
        mock_update.return_value = {"tenant_name": "Updated"}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.put("/tenants/tenant-1", json={"tenant_name": "Updated"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=tenant_update" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"tenant_id":"tenant-1","tenant_name":"Updated"}' in messages[0]


def test_delete_success_records_audit_entry(caplog):
    """Test successful tenant deletion records a security audit entry"""
    with patch("apps.tenant_app.get_current_user_id") as mock_get_user, \
         patch("apps.tenant_app.delete_tenant", new_callable=AsyncMock) as mock_delete:
        mock_get_user.return_value = ("user-1", "tenant-1")
        mock_delete.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.delete("/tenants/tenant-1")

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=tenant_delete" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"tenant_id":"tenant-1"}' in messages[0]
