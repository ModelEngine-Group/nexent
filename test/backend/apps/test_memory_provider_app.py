import sys
import types
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

consts_const = types.ModuleType("consts.const")
consts_const.MEMORY_PROVIDER_PLUGINS_DIR = "/tmp/test-plugins"
sys.modules["consts.const"] = consts_const
sys.modules["consts"] = types.ModuleType("consts")

database_pkg = types.ModuleType("database")
config_db_mod = types.ModuleType("database.memory_provider_config_db")
param_db_mod = types.ModuleType("database.memory_provider_config_param_db")
database_pkg.memory_provider_config_db = config_db_mod
database_pkg.memory_provider_config_param_db = param_db_mod
sys.modules["database"] = database_pkg
sys.modules["database.memory_provider_config_db"] = config_db_mod
sys.modules["database.memory_provider_config_param_db"] = param_db_mod

nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []
memory_models = types.ModuleType("nexent.memory.models")


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__


class MemoryIngestRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemoryIngestResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__


class MemoryIngestUnit:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ProviderErrorCode:
    UNAUTHORIZED = types.SimpleNamespace(value="unauthorized")
    FORBIDDEN = types.SimpleNamespace(value="forbidden")
    UNKNOWN = types.SimpleNamespace(value="unknown")
    INVALID_PAYLOAD = types.SimpleNamespace(value="invalid_payload")


memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_models.MemoryIngestRequest = MemoryIngestRequest
memory_models.MemoryIngestResult = MemoryIngestResult
memory_models.MemoryIngestUnit = MemoryIngestUnit
memory_models.ProviderErrorCode = ProviderErrorCode
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models
nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg

providers_base = types.ModuleType("nexent.memory.providers.base")
providers_base.SearchableMemoryProvider = MagicMock
providers_base.IngestibleMemoryProvider = MagicMock
providers_pkg = types.ModuleType("nexent.memory.providers")
providers_pkg.__path__ = []
providers_pkg.base = providers_base
sys.modules["nexent.memory.providers"] = providers_pkg
sys.modules["nexent.memory.providers.base"] = providers_base

retry_mod = types.ModuleType("nexent.memory.providers.retry")


class NonRetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class RetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class DegradableProviderError(Exception):
    def __init__(self, msg="", error=None, removable_units=None):
        super().__init__(msg)
        self.error = error
        self.removable_units = removable_units or []


retry_mod.NonRetryableProviderError = NonRetryableProviderError
retry_mod.RetryableProviderError = RetryableProviderError
retry_mod.DegradableProviderError = DegradableProviderError
sys.modules["nexent.memory.providers.retry"] = retry_mod

services_pkg = types.ModuleType("services")
ext_provider_svc_mod = types.ModuleType("services.memory_external_provider_service")
config_svc_mod = types.ModuleType("services.memory_provider_config_service")
plugin_loader_mod = types.ModuleType("services.memory_provider_plugin_loader")
ext_provider_svc_mod.MemoryExternalProviderService = MagicMock
config_svc_mod.MemoryProviderConfigService = MagicMock
plugin_loader_mod.PluginLoader = MagicMock
sys.modules["services"] = services_pkg
sys.modules["services.memory_external_provider_service"] = ext_provider_svc_mod
sys.modules["services.memory_provider_config_service"] = config_svc_mod
sys.modules["services.memory_provider_plugin_loader"] = plugin_loader_mod

auth_utils_mod = types.ModuleType("utils.auth_utils")
auth_utils_mod.get_current_user_id = MagicMock(return_value=("u1", "t1"))
sys.modules["utils.auth_utils"] = auth_utils_mod

from apps import memory_provider_app


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(memory_provider_app.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_plugin_loader():
    memory_provider_app._plugin_loader = None
    yield
    memory_provider_app._plugin_loader = None


def _mock_plugin_loader():
    loader = MagicMock()
    loader.list_plugins.return_value = []
    loader.load_all.return_value = None
    return loader


def test_service_factories_load_plugins_once():
    loader = _mock_plugin_loader()
    with patch.object(memory_provider_app, "PluginLoader", return_value=loader), patch.object(
        memory_provider_app, "MemoryProviderConfigService"
    ) as config_service_type, patch.object(
        memory_provider_app, "MemoryExternalProviderService"
    ) as provider_service_type:
        first = memory_provider_app._get_plugin_loader()
        second = memory_provider_app._get_plugin_loader()
        config_service = memory_provider_app._get_config_service()
        provider_service = memory_provider_app._get_provider_service()

    assert first is loader
    assert second is loader
    loader.load_all.assert_called_once_with()
    config_service_type.assert_called()
    provider_service_type.assert_called()
    assert config_service is config_service_type.return_value
    assert provider_service is provider_service_type.return_value


def test_extract_error_code_defaults_to_unknown():
    assert memory_provider_app._extract_error_code(RuntimeError("boom")) == "unknown"
    assert (
        memory_provider_app._extract_error_code(NonRetryableProviderError("bad"))
        == "unknown"
    )


@contextmanager
def _provider_runtime(provider_service):
    """Patch the dependencies shared by provider search and ingest endpoints."""
    with patch.object(memory_provider_app, "memory_provider_config_db") as config_db, \
         patch.object(memory_provider_app, "memory_provider_config_param_db") as param_db, \
         patch.object(memory_provider_app, "_get_provider_service", return_value=provider_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        config_db.get_provider_config.return_value = {"provider_config_id": 1}
        param_db.get_params.return_value = {"plugin.name": "mem0"}
        config_db.update_provider_config.return_value = True
        yield config_db


def test_create_provider_success(client):
    mock_service = MagicMock()
    mock_service.create_provider.return_value = {"provider_config_id": 1, "params": {}}

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.post(
            "/memory/providers",
            json={
                "provider_name": "test",
                "connection_type": "plugin",
                "params": {"plugin.name": "mem0"},
            },
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200


def test_create_provider_validation_error(client):
    mock_service = MagicMock()
    mock_service.create_provider.side_effect = ValueError("bad input")

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.post(
            "/memory/providers",
            json={
                "provider_name": "test",
                "params": {"plugin.name": "mem0"},
            },
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400


def test_create_provider_duplicate_name(client):
    mock_service = MagicMock()
    mock_service.create_provider.side_effect = ValueError("duplicate")

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.post(
            "/memory/providers",
            json={
                "provider_name": "dup",
                "params": {"plugin.name": "mem0"},
            },
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400


def test_create_provider_unexpected_error(client):
    mock_service = MagicMock()
    mock_service.create_provider.side_effect = RuntimeError("boom")
    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service):
        response = client.post(
            "/memory/providers",
            json={"provider_name": "test", "params": {"plugin.name": "mem0"}},
            headers={"Authorization": "Bearer test"},
        )
    assert response.status_code == 500


def test_list_providers(client):
    mock_service = MagicMock()
    mock_service.list_providers.return_value = [{"provider_config_id": 1}]

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.get(
            "/memory/providers",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1


def test_list_providers_unexpected_error(client):
    mock_service = MagicMock()
    mock_service.list_providers.side_effect = RuntimeError("boom")
    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service):
        response = client.get(
            "/memory/providers", headers={"Authorization": "Bearer test"}
        )
    assert response.status_code == 500


def test_get_provider_found(client):
    mock_service = MagicMock()
    mock_service.get_provider.return_value = {"provider_config_id": 1, "params": {}}

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.get(
            "/memory/providers/1",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200


def test_get_provider_not_found(client):
    mock_service = MagicMock()
    mock_service.get_provider.return_value = None

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.get(
            "/memory/providers/999",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 404


def test_get_provider_unexpected_error(client):
    mock_service = MagicMock()
    mock_service.get_provider.side_effect = RuntimeError("boom")
    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service):
        response = client.get(
            "/memory/providers/1", headers={"Authorization": "Bearer test"}
        )
    assert response.status_code == 500


def test_update_provider_success(client):
    mock_service = MagicMock()
    mock_service.update_provider.return_value = {"provider_config_id": 1, "params": {}}

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.put(
            "/memory/providers/1",
            json={"provider_name": "new-name"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200


def test_update_provider_not_found(client):
    mock_service = MagicMock()
    mock_service.update_provider.return_value = None

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.put(
            "/memory/providers/999",
            json={"provider_name": "x"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 404


def test_update_provider_errors(client):
    mock_service = MagicMock()
    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service):
        mock_service.update_provider.side_effect = ValueError("invalid")
        response = client.put(
            "/memory/providers/1",
            json={"provider_name": "x"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400

        mock_service.update_provider.side_effect = RuntimeError("boom")
        response = client.put(
            "/memory/providers/1",
            json={"provider_name": "x"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 500


def test_delete_provider_success(client):
    mock_service = MagicMock()
    mock_service.delete_provider.return_value = True

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.delete(
            "/memory/providers/1",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200


def test_delete_provider_not_found(client):
    mock_service = MagicMock()
    mock_service.delete_provider.return_value = False

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        response = client.delete(
            "/memory/providers/999",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400


def test_delete_provider_unexpected_error(client):
    mock_service = MagicMock()
    mock_service.delete_provider.side_effect = RuntimeError("boom")
    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service):
        response = client.delete(
            "/memory/providers/1", headers={"Authorization": "Bearer test"}
        )
    assert response.status_code == 500


def test_test_search_success(client):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(return_value=[
        MemorySearchResult(memory_id=1, content="result", score=0.9)
    ])
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service):
        response = client.post(
            "/memory/providers/1/test-search",
            json={"query": "hello", "top_k": 5},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1


def test_test_search_failure_updates_error_code(client):
    mock_provider = MagicMock()
    error = types.SimpleNamespace(code=ProviderErrorCode.UNAUTHORIZED)
    mock_provider.search = AsyncMock(
        side_effect=NonRetryableProviderError("unauthorized", error=error)
    )
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service) as m_db:
        response = client.post(
            "/memory/providers/1/test-search",
            json={"query": "hello"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400
        m_db.update_provider_config.assert_called_once()


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (ValueError("invalid"), 400, "invalid_payload"),
        (RuntimeError("boom"), 500, "unknown"),
    ],
)
def test_test_search_other_errors(client, error, expected_status, expected_code):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(side_effect=error)
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service) as config_db:
        response = client.post(
            "/memory/providers/1/test-search",
            json={"query": "hello"},
            headers={"Authorization": "Bearer test"},
        )
    assert response.status_code == expected_status
    assert config_db.update_provider_config.call_args.args[1]["last_error_code"] == expected_code


def test_test_ingest_success(client):
    mock_provider = MagicMock()
    mock_provider.ingest = AsyncMock(
        return_value=MemoryIngestResult(provider="test", status="ok")
    )
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service):
        response = client.post(
            "/memory/providers/1/test-ingest",
            json={"units": [{"event_id": "e1", "event_type": "test", "unit_type": "agent", "unit_content": "x"}]},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200


def test_test_ingest_failure_updates_error_code(client):
    mock_provider = MagicMock()
    error = types.SimpleNamespace(code=ProviderErrorCode.UNAUTHORIZED)
    mock_provider.ingest = AsyncMock(
        side_effect=NonRetryableProviderError("unauthorized", error=error)
    )
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service) as m_db:
        response = client.post(
            "/memory/providers/1/test-ingest",
            json={"units": [{"event_id": "e1", "event_type": "test", "unit_type": "agent", "unit_content": "x"}]},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 400
        m_db.update_provider_config.assert_called_once()


def test_test_ingest_rejects_invalid_unit(client):
    mock_provider_service = MagicMock()
    with _provider_runtime(mock_provider_service), patch.object(
        memory_provider_app.MemoryIngestUnit, "__init__", side_effect=ValueError("invalid")
    ):
        response = client.post(
            "/memory/providers/1/test-ingest",
            json={"units": [{"unit_content": "x"}]},
            headers={"Authorization": "Bearer test"},
        )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (ValueError("invalid"), 400, "invalid_payload"),
        (RuntimeError("boom"), 500, "unknown"),
    ],
)
def test_test_ingest_other_errors(client, error, expected_status, expected_code):
    mock_provider = MagicMock()
    mock_provider.ingest = AsyncMock(side_effect=error)
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with _provider_runtime(mock_provider_service) as config_db:
        response = client.post(
            "/memory/providers/1/test-ingest",
            json={
                "units": [
                    {
                        "event_id": "e1",
                        "event_type": "test",
                        "unit_type": "agent",
                        "unit_content": "x",
                    }
                ]
            },
            headers={"Authorization": "Bearer test"},
        )
    assert response.status_code == expected_status
    assert config_db.update_provider_config.call_args.args[1]["last_error_code"] == expected_code


def test_list_plugins(client):
    loader = _mock_plugin_loader()
    plugin_info = MagicMock()
    plugin_info.name = "mem0"
    plugin_info.version = "1.0.0"
    plugin_info.description = "Mem0 provider"
    plugin_info.implements = ["searchable", "ingestible"]
    plugin_info.config_schema = [{"key": "api_key", "type": "secret"}]
    loader.list_plugins.return_value = [plugin_info]

    with patch.object(memory_provider_app, "_get_plugin_loader", return_value=loader):
        response = client.get(
            "/memory/provider-plugins",
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["name"] == "mem0"


def test_test_search_provider_not_found(client):
    with patch.object(memory_provider_app, "memory_provider_config_db") as m_db, \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        m_db.get_provider_config.return_value = None

        response = client.post(
            "/memory/providers/999/test-search",
            json={"query": "hello"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 404


def test_test_ingest_provider_not_found(client):
    with patch.object(memory_provider_app, "memory_provider_config_db") as m_db, \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):
        m_db.get_provider_config.return_value = None

        response = client.post(
            "/memory/providers/999/test-ingest",
            json={"units": [{"event_id": "e1", "event_type": "test", "unit_type": "agent", "unit_content": "x"}]},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 404
