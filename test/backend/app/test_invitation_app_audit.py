"""Audit entries recorded on successful invitation lifecycle operations.

Feature-scoped companion to ``test_invitation_app.py``: only the audit
assertions live here; the legacy module keeps its endpoint-coverage suites.
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

# Import-time isolation mirrors test_invitation_app.py: storage/search clients
# and DB drivers must not reach live services during import.
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

from apps.invitation_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_create_success_records_audit_entry(caplog):
    """Test successful invitation creation records a security audit entry"""
    with patch("apps.invitation_app.get_current_user_id") as mock_get_user, \
         patch("apps.invitation_app.create_invitation_code") as mock_create:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_create.return_value = {"invitation_id": 5, "invitation_code": "INVITE-ABC"}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post(
                "/invitations",
                headers={"Authorization": "Bearer token"},
                json={"tenant_id": "tenant-1", "code_type": "USER_INVITE",
                      "capacity": 10, "group_ids": [3, 4]},
            )

    assert response.status_code == HTTPStatus.CREATED
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=invitation_create" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert ('details={"invitation_code":"INVITE-ABC","code_type":"USER_INVITE",'
            '"tenant_id":"tenant-1","capacity":10,"group_ids":[3,4]}') in messages[0]


def test_update_success_records_audit_entry(caplog):
    """Test successful invitation update records a security audit entry"""
    with patch("apps.invitation_app.get_current_user_id") as mock_get_user, \
         patch("apps.invitation_app.get_invitation_by_code") as mock_get_invitation, \
         patch("apps.invitation_app.update_invitation_code") as mock_update:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_get_invitation.return_value = {"invitation_id": 5, "invitation_code": "INVITE-ABC"}
        mock_update.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.put(
                "/invitations/INVITE-ABC",
                headers={"Authorization": "Bearer token"},
                json={"capacity": 20},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=invitation_update" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"invitation_code":"INVITE-ABC","updates":{"capacity":20}}' in messages[0]


def test_use_success_records_audit_entry(caplog):
    """Test successful invitation usage records a security audit entry"""
    with patch("apps.invitation_app.get_current_user_id") as mock_get_user, \
         patch("apps.invitation_app.use_invitation_code") as mock_use:
        mock_get_user.return_value = ("user-1", "tenant-1")
        mock_use.return_value = {"group_ids": [3]}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post(
                "/invitations/INVITE-ABC/use",
                headers={"Authorization": "Bearer token"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=invitation_use" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"invitation_code":"INVITE-ABC"}' in messages[0]


def test_delete_success_records_audit_entry(caplog):
    """Test successful invitation deletion records a security audit entry"""
    with patch("apps.invitation_app.get_current_user_id") as mock_get_user, \
         patch("apps.invitation_app.get_invitation_by_code") as mock_get_invitation, \
         patch("apps.invitation_app.delete_invitation_code") as mock_delete:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_get_invitation.return_value = {"invitation_id": 5, "invitation_code": "INVITE-ABC"}
        mock_delete.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.delete(
                "/invitations/INVITE-ABC",
                headers={"Authorization": "Bearer token"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=invitation_delete" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"invitation_code":"INVITE-ABC"}' in messages[0]
