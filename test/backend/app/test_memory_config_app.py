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


class TestMemoryCrud:
    def test_add_memory_success(self):
        async def _ok_add(**kwargs):
            return {"added": True, "payload": kwargs.get("messages")}

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_add_memory", _ok_add):
                    resp = client.post(
                        "/memory/add",
                        json={
                            "messages": [{"role": "user", "content": "hi"}],
                            "memory_level": "user",
                            "agent_id": None,
                            "infer": True,
                        },
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    data = resp.json()
                    assert data["added"] is True

    def test_add_memory_error(self):
        async def _err_add(**kwargs):
            raise RuntimeError("add-fail")

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_add_memory", _err_add):
                    resp = client.post(
                        "/memory/add",
                        json={
                            "messages": [{"role": "user", "content": "hi"}],
                            "memory_level": "user",
                        },
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_add_memory_infer_flag_false(self):
        async def _ok_add(**kwargs):
            return {"added": True, "infer": kwargs.get("infer")}

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_add_memory", _ok_add):
                    resp = client.post(
                        "/memory/add",
                        json={
                            "messages": [{"role": "user", "content": "hi"}],
                            "memory_level": "user",
                            "infer": False,
                        },
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    data = resp.json()
                    assert data["infer"] is False

    def test_search_memory_success_and_error(self):
        async def _ok_search(**kwargs):
            return {"hits": [1, 2], "top_k": kwargs.get("top_k")}

        async def _err_search(**kwargs):
            raise ValueError("search-fail")

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_search_memory", _ok_search):
                    resp = client.post(
                        "/memory/search",
                        json={
                            "query_text": "hello",
                            "memory_level": "user",
                            "top_k": 3,
                        },
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    assert resp.json()["top_k"] == 3

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_search_memory", _err_search):
                    resp = client.post(
                        "/memory/search",
                        json={"query_text": "hello",
                              "memory_level": "user"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_search_memory_default_top_k(self):
        async def _ok_search(**kwargs):
            return {"hits": [], "top_k": kwargs.get("top_k")}

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_search_memory", _ok_search):
                    resp = client.post(
                        "/memory/search",
                        json={
                            "query_text": "hello",
                            "memory_level": "user",
                        },
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    assert resp.json()["top_k"] == 5

    def test_list_memory_success_and_error(self):
        async def _ok_list(**kwargs):
            return {"items": [1], "total": 1}

        async def _err_list(**kwargs):
            raise RuntimeError("list-fail")

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_list_memory", _ok_list):
                    resp = client.get(
                        "/memory/list",
                        params={"memory_level": "user"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    assert resp.json()["total"] == 1

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_list_memory", _err_list):
                    resp = client.get(
                        "/memory/list",
                        params={"memory_level": "user"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_list_memory_with_agent_id(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_list_memory", new=AsyncMock(return_value={"items": [], "total": 0})) as m_list:
                    resp = client.get(
                        "/memory/list",
                        params={"memory_level": "user", "agent_id": "A1"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    # Verify agent_id is passed through
                    assert m_list.await_args.kwargs.get("agent_id") == "A1"

    def test_delete_memory_success_and_error(self):
        async def _ok_delete(**kwargs):
            return {"deleted": True}

        async def _err_delete(**kwargs):
            raise RuntimeError("delete-fail")

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_delete_memory", _ok_delete):
                    resp = client.delete(
                        "/memory/delete/ID1", headers=_auth_headers())
                    assert resp.status_code == HTTPStatus.OK
                    assert resp.json()["deleted"] is True

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_delete_memory", _err_delete):
                    resp = client.delete(
                        "/memory/delete/ID1", headers=_auth_headers())
                    assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_clear_memory_success_and_error(self):
        async def _ok_clear(**kwargs):
            return {"cleared": True}

        async def _err_clear(**kwargs):
            raise RuntimeError("clear-fail")

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_clear_memory", _ok_clear):
                    resp = client.delete(
                        "/memory/clear",
                        params={"memory_level": "user"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    assert resp.json()["cleared"] is True

        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_clear_memory", _err_clear):
                    resp = client.delete(
                        "/memory/clear",
                        params={"memory_level": "user"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_clear_memory_with_agent_id(self):
        with patch("apps.memory_config_app.get_current_user_id", return_value=("u", "t")):
            with patch("apps.memory_config_app.build_memory_config", return_value={"cfg": 1}):
                with patch("apps.memory_config_app.svc_clear_memory", new=AsyncMock(return_value={"cleared": True})) as m_clear:
                    resp = client.delete(
                        "/memory/clear",
                        params={"memory_level": "user", "agent_id": "A1"},
                        headers=_auth_headers(),
                    )
                    assert resp.status_code == HTTPStatus.OK
                    # Verify agent_id is passed through
                    assert m_clear.await_args.kwargs.get(
                        "agent_id") == "A1"
