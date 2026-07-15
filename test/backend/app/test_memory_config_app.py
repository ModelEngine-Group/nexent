import types
import importlib.machinery
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes
from consts.exceptions import UnauthorizedError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http import HTTPStatus

# Build app with target router
from apps.memory_config_app import router as memory_router

app = FastAPI()
app.include_router(memory_router)
client = TestClient(app)


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


class TestMemoryConfigLoad:
    def test_load_configs_success(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.get_user_configs", return_value={"k": "v"}) as m_get:
                resp = client.get("/memory/config/load",
                                  headers=_auth_headers())
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"k": "v"}
                m_get.assert_called_once_with("u")

    def test_load_configs_unauthorized(self):
        with patch("apps.memory_config_app.get_current_user_id", side_effect=UnauthorizedError("unauth")):
            resp = client.get("/memory/config/load",
                              headers=_auth_headers())
            assert resp.status_code == HTTPStatus.UNAUTHORIZED

    def test_load_configs_generic_error(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.get_user_configs", side_effect=Exception("boom")):
                resp = client.get("/memory/config/load",
                                  headers=_auth_headers())
                assert resp.status_code == HTTPStatus.BAD_REQUEST
                assert resp.json()[
                    "detail"] == "Failed to load configuration"


class TestSetSingleConfig:
    def test_set_memory_switch_true_string(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.set_memory_switch", return_value=True) as m_set:
                resp = client.post(
                    "/memory/config/set",
                    json={"key": "MEMORY_SWITCH", "value": "true"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}
                m_set.assert_called_once_with("u", True)

    def test_set_memory_switch_yes_uppercase(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.set_memory_switch", return_value=True) as m_set:
                resp = client.post(
                    "/memory/config/set",
                    json={"key": "MEMORY_SWITCH", "value": "YES"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}
                m_set.assert_called_once_with("u", True)

    def test_set_memory_switch_false_numeric_and_fail(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.set_memory_switch", return_value=False) as m_set:
                resp = client.post(
                    "/memory/config/set",
                    json={"key": "MEMORY_SWITCH", "value": 0},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST
                assert resp.json()[
                    "detail"] == "Failed to update configuration"
                m_set.assert_called_once_with("u", False)

    def test_set_agent_share_valid(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.set_agent_share", return_value=True) as m_set:
                resp = client.post(
                    "/memory/config/set",
                    json={"key": "MEMORY_AGENT_SHARE", "value": "ask"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}
                # enum constructed from string 'ask'
                args, _ = m_set.call_args
                assert args[0] == "u"
                assert str(args[1]) == "MemoryAgentShareMode.ASK" or str(
                    args[1]).endswith("ask")

    def test_set_agent_share_invalid_value(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            resp = client.post(
                "/memory/config/set",
                json={"key": "MEMORY_AGENT_SHARE", "value": "invalid"},
                headers=_auth_headers(),
            )
            assert resp.status_code == HTTPStatus.NOT_ACCEPTABLE

    def test_set_unsupported_key(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            resp = client.post(
                "/memory/config/set",
                json={"key": "NOT_SUPPORTED", "value": "x"},
                headers=_auth_headers(),
            )
            assert resp.status_code == HTTPStatus.NOT_ACCEPTABLE

    def test_set_agent_share_backend_failure(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.set_agent_share", return_value=False):
                resp = client.post(
                    "/memory/config/set",
                    json={"key": "MEMORY_AGENT_SHARE", "value": "always"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST
                assert resp.json()[
                    "detail"] == "Failed to update configuration"


class TestDisableAgentEndpoints:
    def test_add_disable_agent_success(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.add_disabled_agent_id", return_value=True):
                resp = client.post(
                    "/memory/config/disable_agent",
                    json={"agent_id": "A1"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}

    def test_add_disable_agent_failure(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.add_disabled_agent_id", return_value=False):
                resp = client.post(
                    "/memory/config/disable_agent",
                    json={"agent_id": "A1"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_remove_disable_agent_success(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.remove_disabled_agent_id", return_value=True):
                resp = client.delete(
                    "/memory/config/disable_agent/A1",
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}

    def test_remove_disable_agent_failure(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.remove_disabled_agent_id", return_value=False):
                resp = client.delete(
                    "/memory/config/disable_agent/A1",
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST


class TestDisableUserAgentEndpoints:
    def test_add_disable_useragent_success(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.add_disabled_useragent_id", return_value=True):
                resp = client.post(
                    "/memory/config/disable_useragent",
                    json={"agent_id": "UA1"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}

    def test_add_disable_useragent_failure(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.add_disabled_useragent_id", return_value=False):
                resp = client.post(
                    "/memory/config/disable_useragent",
                    json={"agent_id": "UA1"},
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_remove_disable_useragent_success(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.remove_disabled_useragent_id", return_value=True):
                resp = client.delete(
                    "/memory/config/disable_useragent/UA1",
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.OK
                assert resp.json() == {"success": True}

    def test_remove_disable_useragent_failure(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.remove_disabled_useragent_id", return_value=False):
                resp = client.delete(
                    "/memory/config/disable_useragent/UA1",
                    headers=_auth_headers(),
                )
                assert resp.status_code == HTTPStatus.BAD_REQUEST


# Legacy ``TestMemoryCrud`` class has been removed alongside the mem0-era
# ``/memory/add``, ``/memory/search``, ``/memory/list``, ``/memory/delete/{id}``
# and ``/memory/clear`` endpoints. New tests for the ``MemoryService`` facade
# will land once Phase 2 of the memory refactor ships.

