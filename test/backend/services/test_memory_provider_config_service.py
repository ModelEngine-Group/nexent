import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

database_pkg = types.ModuleType("database")
config_db_mod = types.ModuleType("database.memory_provider_config_db")
config_db_mod.insert_provider_config = MagicMock(name="insert_provider_config")
config_db_mod.get_provider_config = MagicMock(name="get_provider_config")
config_db_mod.list_provider_configs = MagicMock(name="list_provider_configs")
config_db_mod.update_provider_config = MagicMock(name="update_provider_config")
config_db_mod.soft_delete_provider_config = MagicMock(name="soft_delete_provider_config")
param_db_mod = types.ModuleType("database.memory_provider_config_param_db")
param_db_mod.get_params = MagicMock(name="get_params")
param_db_mod.upsert_params = MagicMock(name="upsert_params")
param_db_mod.delete_params = MagicMock(name="delete_params")
database_pkg.memory_provider_config_db = config_db_mod
database_pkg.memory_provider_config_param_db = param_db_mod
sys.modules["database"] = database_pkg
sys.modules["database.memory_provider_config_db"] = config_db_mod
sys.modules["database.memory_provider_config_param_db"] = param_db_mod

services_pkg = types.ModuleType("services")
sys.modules["services"] = services_pkg

plugin_loader_mod = types.ModuleType("services.memory_provider_plugin_loader")


class FakePluginInfo:
    def __init__(self, name="test-plugin", config_schema=None):
        self.name = name
        self.version = "1.0.0"
        self.description = "test"
        self.implements = ["searchable"]
        self.config_schema = config_schema or []
        self.plugin_dir = "/tmp"
        self.entry_module = None
        self.provider_class = MagicMock()


class FakePluginLoader:
    def __init__(self, plugins=None):
        self._plugins = {p.name: p for p in (plugins or [])}

    def get_plugin(self, name):
        return self._plugins.get(name)

    def list_plugins(self):
        return list(self._plugins.values())

    def build_provider(self, name, config):
        p = self._plugins.get(name)
        if p is None:
            raise ValueError(f"not found: {name}")
        return p.provider_class(config)


plugin_loader_mod.PluginLoader = FakePluginLoader
sys.modules["services.memory_provider_plugin_loader"] = plugin_loader_mod

from backend.services.memory_provider_config_service import (
    MemoryProviderConfigService,
    _mask_value,
)


@pytest.fixture
def plugin_info():
    return FakePluginInfo(
        name="mem0",
        config_schema=[
            {"key": "api_key", "type": "secret", "required": True},
            {"key": "base_url", "type": "string", "required": False},
        ],
    )


@pytest.fixture
def service(plugin_info):
    loader = FakePluginLoader(plugins=[plugin_info])
    return MemoryProviderConfigService(loader)


def test_create_provider_success(service):
    with patch.object(config_db_mod, "insert_provider_config", return_value=1) as m_insert, \
         patch.object(param_db_mod, "upsert_params", return_value=True), \
         patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}):
        result = service.create_provider(
            tenant_id="t1",
            provider_name="my-mem0",
            connection_type="plugin",
            params={"plugin.name": "mem0", "plugin.api_key": "sk-123456789"},
            created_by="u1",
        )
        assert result["params"]["plugin.api_key"] != "sk-123456789"
        m_insert.assert_called_once()


def test_create_provider_invalid_connection_type(service):
    with pytest.raises(ValueError, match="Unsupported connection_type"):
        service.create_provider(
            tenant_id="t1", provider_name="x",
            connection_type="http", params={},
        )


def test_create_provider_plugin_not_found(service):
    with pytest.raises(ValueError, match="not installed"):
        service.create_provider(
            tenant_id="t1", provider_name="x",
            connection_type="plugin",
            params={"plugin.name": "nonexistent"},
        )


def test_create_provider_missing_plugin_name(service):
    with pytest.raises(ValueError, match="plugin.name"):
        service.create_provider(
            tenant_id="t1", provider_name="x",
            connection_type="plugin", params={},
        )


def test_create_provider_missing_required_param(service):
    with pytest.raises(ValueError, match="Required parameter"):
        service.create_provider(
            tenant_id="t1", provider_name="x",
            connection_type="plugin",
            params={"plugin.name": "mem0"},
        )


def test_create_provider_duplicate_name(service):
    with patch.object(config_db_mod, "insert_provider_config", return_value=None):
        with pytest.raises(ValueError, match="Failed to insert"):
            service.create_provider(
                tenant_id="t1", provider_name="dup",
                connection_type="plugin",
                params={"plugin.name": "mem0", "plugin.api_key": "sk-123456789"},
            )


def test_get_provider_success(service):
    with patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0", "plugin.api_key": "sk-123456789"}):
        result = service.get_provider(1)
        assert result is not None
        assert result["params"]["plugin.api_key"] != "sk-123456789"


def test_get_provider_not_found(service):
    with patch.object(config_db_mod, "get_provider_config", return_value=None):
        assert service.get_provider(999) is None


def test_get_provider_secret_masking(service):
    with patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0", "plugin.api_key": "short"}):
        result = service.get_provider(1)
        assert result["params"]["plugin.api_key"] == "***"


def test_list_providers_empty(service):
    with patch.object(config_db_mod, "list_provider_configs", return_value=[]):
        assert service.list_providers("t1") == []


def test_list_providers_with_providers(service):
    configs = [{"provider_config_id": 1}, {"provider_config_id": 2}]
    with patch.object(config_db_mod, "list_provider_configs", return_value=configs), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0", "plugin.api_key": "sk-123456789"}):
        results = service.list_providers("t1")
        assert len(results) == 2


def test_list_providers_secret_masking(service):
    configs = [{"provider_config_id": 1}]
    with patch.object(config_db_mod, "list_provider_configs", return_value=configs), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0", "plugin.api_key": "sk-123456789"}):
        results = service.list_providers("t1")
        assert results[0]["params"]["plugin.api_key"] != "sk-123456789"


def test_update_provider_success(service):
    with patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}), \
         patch.object(config_db_mod, "update_provider_config", return_value=True), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0"}):
        result = service.update_provider(1, {"provider_name": "new-name"}, "u1")
        assert result is not None


def test_update_provider_partial_update(service):
    with patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}), \
         patch.object(config_db_mod, "update_provider_config", return_value=True), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0"}):
        result = service.update_provider(1, {"enabled": True}, "u1")
        assert result is not None


def test_update_provider_params_replace(service):
    with patch.object(config_db_mod, "get_provider_config", return_value={"provider_config_id": 1}), \
         patch.object(config_db_mod, "update_provider_config", return_value=True), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0"}), \
         patch.object(param_db_mod, "upsert_params", return_value=True) as m_upsert:
        result = service.update_provider(
            1, {"params": {"plugin.name": "mem0", "plugin.api_key": "new-key-123456789"}}, "u1"
        )
        assert result is not None
        m_upsert.assert_called_once()


def test_update_provider_not_found(service):
    with patch.object(config_db_mod, "get_provider_config", return_value=None):
        assert service.update_provider(999, {}, "u1") is None


def test_delete_provider_success(service):
    with patch.object(config_db_mod, "soft_delete_provider_config", return_value=True), \
         patch.object(param_db_mod, "delete_params", return_value=True):
        assert service.delete_provider(1, "u1") is True


def test_delete_provider_failure(service):
    with patch.object(config_db_mod, "soft_delete_provider_config", return_value=False):
        assert service.delete_provider(1, "u1") is False


def test_get_enabled_providers_returns_unmasked(service):
    configs = [{"provider_config_id": 1, "enabled": True}]
    with patch.object(config_db_mod, "list_provider_configs", return_value=configs), \
         patch.object(param_db_mod, "get_params", return_value={"plugin.name": "mem0", "plugin.api_key": "sk-123"}):
        results = service.get_enabled_providers("t1")
        assert len(results) == 1
        assert results[0]["params"]["plugin.api_key"] == "sk-123"


def test_get_enabled_providers_only_enabled(service):
    with patch.object(config_db_mod, "list_provider_configs", return_value=[]) as m_list:
        service.get_enabled_providers("t1")
        m_list.assert_called_once_with("t1", enabled_only=True)


def test_mask_params_short_key():
    schema = [{"key": "api_key", "type": "secret"}]
    result = MemoryProviderConfigService._mask_params(
        {"plugin.api_key": "short"}, schema
    )
    assert result["plugin.api_key"] == "***"


def test_mask_params_long_key():
    schema = [{"key": "api_key", "type": "secret"}]
    result = MemoryProviderConfigService._mask_params(
        {"plugin.api_key": "sk-1234567890abcdef"}, schema
    )
    assert result["plugin.api_key"] == "sk-***cdef"


def test_mask_params_secret_type():
    schema = [{"key": "token", "type": "secret"}]
    result = MemoryProviderConfigService._mask_params(
        {"plugin.token": "my-secret-token"}, schema
    )
    assert result["plugin.token"] == "my-***oken"


def test_mask_params_non_secret():
    schema = [{"key": "base_url", "type": "string"}]
    result = MemoryProviderConfigService._mask_params(
        {"plugin.base_url": "https://api.example.com"}, schema
    )
    assert result["plugin.base_url"] == "https://api.example.com"


def test_mask_params_api_key_suffix():
    result = MemoryProviderConfigService._mask_params(
        {"custom_api_key": "my-secret-value"}, []
    )
    assert result["custom_api_key"] == "my-***alue"


def test_mask_value_short():
    assert _mask_value("short") == "***"


def test_mask_value_long():
    assert _mask_value("sk-1234567890") == "sk-***7890"


def test_mask_value_empty():
    assert _mask_value("") == ""


def test_validate_params_valid(service):
    service._validate_params(
        {"plugin.name": "mem0", "plugin.api_key": "sk-123"}, "mem0"
    )


def test_validate_params_missing_required(service):
    with pytest.raises(ValueError, match="Required parameter"):
        service._validate_params({"plugin.name": "mem0"}, "mem0")


def test_validate_params_unknown_plugin(service):
    with pytest.raises(ValueError, match="not installed"):
        service._validate_params({}, "nonexistent")
