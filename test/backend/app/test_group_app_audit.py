"""Audit entries recorded on successful group and membership operations.

Feature-scoped companion to ``test_group_app.py``: only the audit assertions
live here; the legacy module keeps its endpoint-coverage suites. The
``group_default_set`` endpoint has no audit assertion in the reference PR
either.
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

# Import-time isolation mirrors test_group_app.py: storage/search clients and
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

from apps.group_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_create_success_records_audit_entry(caplog):
    """Test successful group creation records a security audit entry"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.create_group") as mock_create:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_create.return_value = {"group_id": 7, "group_name": "QA"}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post(
                "/groups",
                headers={"Authorization": "Bearer token"},
                json={"tenant_id": "tenant-1", "group_name": "QA"},
            )

    assert response.status_code == HTTPStatus.CREATED
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_create" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert "tenant_id=tenant-1" in messages[0]
    assert 'details={"tenant_id":"tenant-1","group_name":"QA"}' in messages[0]


def test_update_success_records_audit_entry(caplog):
    """Test successful group update records a security audit entry with the changed field names"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.update_group") as mock_update:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_update.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.put(
                "/groups/7",
                headers={"Authorization": "Bearer token"},
                json={"group_name": "Renamed"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_update" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert 'details={"group_id":7,"updated_fields":["group_name"]}' in messages[0]


def test_delete_success_records_audit_entry(caplog):
    """Test successful group deletion records a security audit entry"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.delete_group") as mock_delete:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_delete.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.delete("/groups/7", headers={"Authorization": "Bearer token"})

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_delete" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert 'details={"group_id":7}' in messages[0]


def test_add_member_success_records_audit_entry(caplog):
    """Test successful member addition records who added which user to which group"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.add_user_to_single_group") as mock_add_user:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_add_user.return_value = {"added": True}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post(
                "/groups/7/members",
                headers={"Authorization": "Bearer token"},
                json={"user_id": "user-9"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_member_add" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert 'details={"target_user_id":"user-9","group_id":7}' in messages[0]


def test_remove_member_success_records_audit_entry(caplog):
    """Test successful member removal records who removed which user from which group"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.remove_user_from_single_group") as mock_remove_user:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_remove_user.return_value = True

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.delete(
                "/groups/7/members/user-9",
                headers={"Authorization": "Bearer token"},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_member_remove" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert 'details={"target_user_id":"user-9","group_id":7}' in messages[0]


def test_update_members_success_records_audit_entry(caplog):
    """Test setting the exact member list records the group and the bounded user ids"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.update_group_members") as mock_update_members:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_update_members.return_value = {"added": 2, "removed": 1}

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.put(
                "/groups/7/members",
                headers={"Authorization": "Bearer token"},
                json={"user_ids": ["u-1", "u-2"]},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_member_update" in messages[0]
    assert 'details={"group_id":7,"user_count":2,"user_ids":["u-1","u-2"]}' in messages[0]


def test_batch_add_success_records_audit_entry(caplog):
    """Test batch membership addition records the user and the bounded group ids"""
    with patch("apps.group_app.get_current_user_id") as mock_get_user, \
         patch("apps.group_app.add_user_to_groups") as mock_add_user_groups:
        mock_get_user.return_value = ("admin-1", "tenant-1")
        mock_add_user_groups.return_value = [{"added": True}, {"added": True}]

        with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
            response = client.post(
                "/groups/members/batch",
                headers={"Authorization": "Bearer token"},
                json={"user_id": "user-9", "group_ids": [3, 4]},
            )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=group_member_batch_add" in messages[0]
    assert "user_id=admin-1" in messages[0]
    assert 'details={"target_user_id":"user-9","group_count":2,"group_ids":[3,4]}' in messages[0]
