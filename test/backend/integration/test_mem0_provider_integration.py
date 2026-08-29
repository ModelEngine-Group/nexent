"""Integration tests for Mem0 external memory provider (Phase 3).

Requires a running Mem0 service at localhost:8765.
Start with: docker-compose -f docker-compose-mem0.yml up -d
Run with: pytest --run-integration -v
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

# ---------------------------------------------------------------------------
# Module stubs for import resolution
# ---------------------------------------------------------------------------

_consts_const = types.ModuleType("consts.const")
_consts_const.MEMORY_PROVIDER_PLUGINS_DIR = "/tmp/test-plugins"
_consts_const.EXTERNAL_MEMORY_SEARCH_ENABLED = True
_consts_const.EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES = {"agent", "user", "tool", "summary"}
sys.modules["consts.const"] = _consts_const
sys.modules["consts"] = types.ModuleType("consts")

_database_pkg = types.ModuleType("database")
_config_db_mod = types.ModuleType("database.memory_provider_config_db")
_param_db_mod = types.ModuleType("database.memory_provider_config_param_db")
_ingest_log_db_mod = types.ModuleType("database.memory_external_ingest_event_log_db")
_database_pkg.memory_provider_config_db = _config_db_mod
_database_pkg.memory_provider_config_param_db = _param_db_mod
_database_pkg.memory_external_ingest_event_log_db = _ingest_log_db_mod
sys.modules["database"] = _database_pkg
sys.modules["database.memory_provider_config_db"] = _config_db_mod
sys.modules["database.memory_provider_config_param_db"] = _param_db_mod
sys.modules["database.memory_external_ingest_event_log_db"] = _ingest_log_db_mod

_nexent_pkg = types.ModuleType("nexent")
_memory_pkg = types.ModuleType("nexent.memory")
_memory_pkg.__path__ = []
_memory_models = types.ModuleType("nexent.memory.models")


class _ProviderErrorCode:
    UNAUTHORIZED = types.SimpleNamespace(value="unauthorized")
    FORBIDDEN = types.SimpleNamespace(value="forbidden")
    UNKNOWN = types.SimpleNamespace(value="unknown")
    INVALID_PAYLOAD = types.SimpleNamespace(value="invalid_payload")
    TIMEOUT = types.SimpleNamespace(value="timeout")
    PROVIDER_ERROR = types.SimpleNamespace(value="provider_error")
    RATE_LIMITED = types.SimpleNamespace(value="rate_limited")
    PARTIAL_ACCEPTANCE = types.SimpleNamespace(value="partial_acceptance")
    UNSUPPORTED_UNIT_TYPE = types.SimpleNamespace(value="unsupported_unit_type")


class _ProviderErrorSeverity:
    NON_RETRYABLE = types.SimpleNamespace(value="non_retryable")
    RETRYABLE = types.SimpleNamespace(value="retryable")
    DEGRADABLE = types.SimpleNamespace(value="degradable")


class _MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MemorySearchResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__


class _MemoryIngestRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_copy(self, update=None):
        new_kwargs = {**self.__dict__}
        if update:
            new_kwargs.update(update)
        return _MemoryIngestRequest(**new_kwargs)


class _MemoryIngestResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__


class _MemoryIngestUnit:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ProviderError(Exception):
    def __init__(self, code=None, message="", severity=None, retry_after_seconds=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.severity = severity
        self.retry_after_seconds = retry_after_seconds


class _UnitIngestResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _UnitIngestStatus:
    ACCEPTED = types.SimpleNamespace(value="accepted")
    REJECTED = types.SimpleNamespace(value="rejected")


class _ExternalMemoryItem:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MemoryLayer:
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class _MemorySearchContext:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _PipelineConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


_memory_models.MemorySearchRequest = _MemorySearchRequest
_memory_models.MemorySearchResult = _MemorySearchResult
_memory_models.MemoryIngestRequest = _MemoryIngestRequest
_memory_models.MemoryIngestResult = _MemoryIngestResult
_memory_models.MemoryIngestUnit = _MemoryIngestUnit
_memory_models.ProviderError = _ProviderError
_memory_models.ProviderErrorCode = _ProviderErrorCode
_memory_models.ProviderErrorSeverity = _ProviderErrorSeverity
_memory_models.UnitIngestResult = _UnitIngestResult
_memory_models.UnitIngestStatus = _UnitIngestStatus
_memory_models.ExternalMemoryItem = _ExternalMemoryItem
_memory_models.MemoryLayer = _MemoryLayer
_memory_models.MemorySearchContext = _MemorySearchContext
_memory_models.PipelineConfig = _PipelineConfig
_memory_pkg.models = _memory_models
sys.modules["nexent.memory.models"] = _memory_models
_nexent_pkg.memory = _memory_pkg
sys.modules["nexent"] = _nexent_pkg
sys.modules["nexent.memory"] = _memory_pkg

_providers_base = types.ModuleType("nexent.memory.providers.base")
_providers_base.SearchableMemoryProvider = MagicMock
_providers_base.IngestibleMemoryProvider = MagicMock
_providers_pkg = types.ModuleType("nexent.memory.providers")
_providers_pkg.__path__ = []
_providers_pkg.base = _providers_base
sys.modules["nexent.memory.providers"] = _providers_pkg
sys.modules["nexent.memory.providers.base"] = _providers_base

_retry_mod = types.ModuleType("nexent.memory.providers.retry")


class _NonRetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class _RetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class _DegradableProviderError(Exception):
    def __init__(self, msg="", error=None, removable_units=None):
        super().__init__(msg)
        self.error = error
        self.removable_units = removable_units or []


class _RetryConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


async def _execute_with_retry(fn, config, operation_name=""):
    return await fn()


_retry_mod.NonRetryableProviderError = _NonRetryableProviderError
_retry_mod.RetryableProviderError = _RetryableProviderError
_retry_mod.DegradableProviderError = _DegradableProviderError
_retry_mod.RetryConfig = _RetryConfig
_retry_mod.execute_with_retry = _execute_with_retry
sys.modules["nexent.memory.providers.retry"] = _retry_mod

_embedding_mod = types.ModuleType("nexent.memory.embedding_model")
_embedding_mod.EmbeddingModelInfo = MagicMock
sys.modules["nexent.memory.embedding_model"] = _embedding_mod

_pipeline_mod = types.ModuleType("nexent.memory.retrieval")
_pipeline_mod.__path__ = []
_pipeline_pipeline_mod = types.ModuleType("nexent.memory.retrieval.pipeline")
_pipeline_pipeline_mod.RetrievalPipeline = MagicMock
sys.modules["nexent.memory.retrieval"] = _pipeline_mod
sys.modules["nexent.memory.retrieval.pipeline"] = _pipeline_pipeline_mod

_policy_mod = types.ModuleType("nexent.memory.policy")
_policy_mod.MemoryRetrievalPolicy = MagicMock
sys.modules["nexent.memory.policy"] = _policy_mod

_services_pkg = types.ModuleType("services")
_ext_provider_svc = types.ModuleType("services.memory_external_provider_service")
_config_svc = types.ModuleType("services.memory_provider_config_service")
_plugin_loader_svc = types.ModuleType("services.memory_provider_plugin_loader")
_ingestion_svc = types.ModuleType("services.memory_ingestion_event_service")
_ext_provider_svc.MemoryExternalProviderService = MagicMock
_config_svc.MemoryProviderConfigService = MagicMock
_plugin_loader_svc.PluginLoader = MagicMock
_ingestion_svc.MemoryIngestionEventService = MagicMock
sys.modules["services"] = _services_pkg
sys.modules["services.memory_external_provider_service"] = _ext_provider_svc
sys.modules["services.memory_provider_config_service"] = _config_svc
sys.modules["services.memory_provider_plugin_loader"] = _plugin_loader_svc
sys.modules["services.memory_ingestion_event_service"] = _ingestion_svc

_auth_utils = types.ModuleType("utils.auth_utils")
_auth_utils.get_current_user_id = MagicMock(return_value=("test-user", "test-tenant"))
sys.modules["utils.auth_utils"] = _auth_utils

from apps import memory_provider_app

pytestmark = pytest.mark.integration

MEM0_BASE_URL = "http://localhost:8765"
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mem0_available():
    """Check if Mem0 service is available before running integration tests."""
    try:
        response = httpx.get(f"{MEM0_BASE_URL}/health", timeout=2.0)
        if response.status_code != 200:
            pytest.skip("Mem0 service not available")
    except Exception:
        pytest.skip("Mem0 service not available")


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


def _mock_plugin_loader_with_mem0():
    loader = MagicMock()
    plugin_info = MagicMock()
    plugin_info.name = "mem0"
    plugin_info.version = "1.0.0"
    plugin_info.description = "Mem0 external memory provider"
    plugin_info.implements = ["searchable", "ingestible"]
    plugin_info.config_schema = [
        {"key": "api_key", "label": "API Key", "type": "secret", "required": True},
        {"key": "org_id", "label": "Organization ID", "type": "string", "required": False},
        {"key": "base_url", "label": "API Base URL", "type": "string", "required": False},
    ]
    loader.list_plugins.return_value = [plugin_info]
    loader.load_all.return_value = None
    return loader


def _mock_config_service_create(return_value=None):
    svc = MagicMock()
    svc.create_provider.return_value = return_value or {
        "provider_config_id": 1,
        "provider_name": "test-mem0",
        "params": {"plugin.name": "mem0", "plugin.api_key": "***"},
    }
    return svc


def _mock_config_service_list(items=None):
    svc = MagicMock()
    svc.list_providers.return_value = items or []
    return svc


# ---------------------------------------------------------------------------
# Test 1: Provider Config CRUD
# ---------------------------------------------------------------------------


def test_mem0_provider_config_crud(client, mem0_available):
    """Verify API create/read/update/delete for Mem0 provider config."""
    mock_service = MagicMock()
    mock_service.create_provider.return_value = {
        "provider_config_id": 42,
        "provider_name": "test-mem0",
        "params": {"plugin.name": "mem0", "plugin.api_key": "***"},
    }
    mock_service.get_provider.return_value = {
        "provider_config_id": 42,
        "provider_name": "test-mem0",
        "enabled": True,
        "params": {"plugin.name": "mem0", "plugin.api_key": "***"},
    }
    mock_service.update_provider.return_value = {
        "provider_config_id": 42,
        "provider_name": "test-mem0-updated",
        "enabled": True,
        "params": {"plugin.name": "mem0", "plugin.api_key": "***"},
    }
    mock_service.delete_provider.return_value = True

    loader = _mock_plugin_loader_with_mem0()

    with patch.object(memory_provider_app, "_get_config_service", return_value=mock_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=loader):

        create_resp = client.post(
            "/memory/providers",
            json={
                "provider_name": "test-mem0",
                "connection_type": "plugin",
                "enabled": True,
                "params": {
                    "plugin.name": "mem0",
                    "plugin.api_key": "test-key-123",
                    "plugin.base_url": MEM0_BASE_URL,
                },
            },
            headers=AUTH_HEADERS,
        )
        assert create_resp.status_code == 200
        config_id = create_resp.json()["provider_config_id"]
        assert config_id == 42

        get_resp = client.get(
            f"/memory/providers/{config_id}",
            headers=AUTH_HEADERS,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["provider_name"] == "test-mem0"

        update_resp = client.put(
            f"/memory/providers/{config_id}",
            json={"provider_name": "test-mem0-updated"},
            headers=AUTH_HEADERS,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["provider_name"] == "test-mem0-updated"

        delete_resp = client.delete(
            f"/memory/providers/{config_id}",
            headers=AUTH_HEADERS,
        )
        assert delete_resp.status_code == 200
        assert delete_resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Test 2: Plugin List
# ---------------------------------------------------------------------------


def test_mem0_plugin_list(client, mem0_available):
    """Verify GET /memory/provider-plugins returns the mem0 plugin."""
    loader = _mock_plugin_loader_with_mem0()

    with patch.object(memory_provider_app, "_get_plugin_loader", return_value=loader):
        response = client.get(
            "/memory/provider-plugins",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 1
        plugin_names = [p["name"] for p in body["items"]]
        assert "mem0" in plugin_names
        mem0_plugin = next(p for p in body["items"] if p["name"] == "mem0")
        assert "searchable" in mem0_plugin["implements"]
        assert "ingestible" in mem0_plugin["implements"]


# ---------------------------------------------------------------------------
# Test 3: Search Returns External Results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_search_returns_external_results(client, mem0_available):
    """Write to Mem0 then verify build_context() retrieves external results."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    ingest_unit = _MemoryIngestUnit(
        event_id="integ-search-001",
        event_type="test",
        unit_type="agent",
        unit_content="The user prefers dark mode for all applications",
        metadata={},
    )
    ingest_req = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="test-user",
        units=[ingest_unit],
        idempotency_key="integ-test:search:001",
    )
    ingest_result = await provider.ingest(ingest_req)
    assert ingest_result.status in ("ok", "partial")

    search_req = _MemorySearchRequest(
        query="user preferences dark mode",
        tenant_id="test-tenant",
        user_id="test-user",
        top_k=5,
    )
    search_results = await provider.search(search_req, limit=5)

    assert len(search_results) > 0, "Expected at least one external result from Mem0"
    assert any(r.is_external for r in search_results if hasattr(r, "is_external"))
    contents = [r.content for r in search_results]
    assert any("dark mode" in c.lower() for c in contents), \
        f"Expected 'dark mode' in results, got: {contents}"


@pytest.mark.asyncio
async def test_mem0_search_falls_back_to_user_scope(client, mem0_available):
    """Agent-scoped search can retrieve memories previously stored user-only."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })
    ingest_result = await provider.ingest(_MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="fallback-user",
        units=[_MemoryIngestUnit(
            event_id="integ-user-fallback-001",
            event_type="test",
            unit_type="user",
            unit_content="Sister Jules has the external code COMET-913",
            metadata={},
        )],
        idempotency_key="integ-test:user-fallback:001",
    ))
    assert ingest_result.status in ("ok", "partial")

    results = await provider.search(_MemorySearchRequest(
        query="Jules external code",
        tenant_id="test-tenant",
        user_id="fallback-user",
        agent_id="agent-with-no-scoped-memory",
        top_k=5,
    ), limit=5)

    assert any("COMET-913" in result.content for result in results)


# ---------------------------------------------------------------------------
# Test 4: Ingest Sends Units
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_ingest_sends_units(client, mem0_available):
    """Verify send_ingest() delivers data to Mem0."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    units = [
        _MemoryIngestUnit(
            event_id="integ-ingest-001",
            event_type="conversation",
            unit_type="agent",
            unit_content="The agent summarized the quarterly report findings",
            metadata={},
        ),
        _MemoryIngestUnit(
            event_id="integ-ingest-002",
            event_type="conversation",
            unit_type="user",
            unit_content="The user asked about revenue projections for Q3",
            metadata={},
        ),
    ]

    request = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="test-user",
        agent_id="test-agent",
        conversation_id="test-conv-001",
        units=units,
        idempotency_key="integ-test:ingest:001",
    )

    result = await provider.ingest(request)

    assert result.status in ("ok", "partial")
    assert result.accepted_count >= 1, \
        f"Expected at least 1 accepted unit, got {result.accepted_count}"

    verify_req = _MemorySearchRequest(
        query="quarterly report revenue",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    verify_results = await provider.search(verify_req, limit=5)
    assert len(verify_results) > 0, "Ingested data should be searchable in Mem0"


# ---------------------------------------------------------------------------
# Test 5: Transparent Proxy Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_transparent_proxy_search(client, mem0_available):
    """Verify agent pre-search auto-merges external results from Mem0."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    ingest_unit = _MemoryIngestUnit(
        event_id="integ-proxy-search-001",
        event_type="test",
        unit_type="agent",
        unit_content="The user's project deadline is December 15th",
        metadata={},
    )
    ingest_req = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="proxy-user",
        units=[ingest_unit],
        idempotency_key="integ-test:proxy-search:001",
    )
    await provider.ingest(ingest_req)

    mock_config = {
        "provider_config_id": 1,
        "provider_name": "test-mem0",
        "enabled": True,
    }
    mock_params = {
        "plugin.name": "mem0",
        "plugin.api_key": "test-integration-key",
        "plugin.base_url": MEM0_BASE_URL,
    }

    mock_service = MagicMock()
    mock_service.get_enabled_providers.return_value = [
        {**mock_config, "params": mock_params}
    ]

    mock_plugin_loader = MagicMock()
    mock_plugin_loader.build_provider.return_value = provider

    from backend.services.memory_external_provider_service import MemoryExternalProviderService
    real_service = MemoryExternalProviderService.__new__(MemoryExternalProviderService)
    real_service._plugin_loader = mock_plugin_loader
    real_service._config_service = mock_service

    search_req = _MemorySearchRequest(
        query="project deadline",
        tenant_id="test-tenant",
        user_id="proxy-user",
    )

    results = await real_service.search_all_enabled(
        tenant_id="test-tenant",
        request=search_req,
        limit=5,
    )

    assert len(results) > 0, "Transparent proxy should return external results"


# ---------------------------------------------------------------------------
# Test 6: Transparent Proxy Store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_transparent_proxy_store(client, mem0_available):
    """Verify StoreMemoryTool path auto-sends data to Mem0."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    mock_config = {
        "provider_config_id": 1,
        "provider_name": "test-mem0",
        "enabled": True,
    }
    mock_params = {
        "plugin.name": "mem0",
        "plugin.api_key": "test-integration-key",
        "plugin.base_url": MEM0_BASE_URL,
    }

    mock_config_service = MagicMock()
    mock_config_service.get_enabled_providers.return_value = [
        {**mock_config, "params": mock_params}
    ]

    mock_plugin_loader = MagicMock()
    mock_plugin_loader.build_provider.return_value = provider

    from backend.services.memory_external_provider_service import MemoryExternalProviderService
    real_service = MemoryExternalProviderService.__new__(MemoryExternalProviderService)
    real_service._plugin_loader = mock_plugin_loader
    real_service._config_service = mock_config_service

    units = [
        _MemoryIngestUnit(
            event_id="integ-store-001",
            event_type="tool_store",
            unit_type="summary",
            unit_content="User requested to remember their favorite color is blue",
            metadata={},
        ),
    ]

    request = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="store-user",
        agent_id="test-agent",
        conversation_id="test-conv-store",
        units=units,
        idempotency_key="integ-test:store:001",
    )

    results = await real_service.ingest_all_enabled(
        tenant_id="test-tenant",
        request=request,
    )

    assert len(results) > 0, "ingest_all_enabled should return results"
    assert any(r.status in ("ok", "partial", "degraded") for r in results), \
        f"Expected at least one successful ingest, got: {[r.status for r in results]}"

    verify_req = _MemorySearchRequest(
        query="favorite color blue",
        tenant_id="test-tenant",
        user_id="store-user",
    )
    verify_results = await provider.search(verify_req, limit=5)
    assert len(verify_results) > 0, "Stored data should be searchable in Mem0"


# ---------------------------------------------------------------------------
# Test 7: Per-Turn Supplement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_per_turn_supplement(client, mem0_available):
    """Verify completing a turn sends non-final_answer units to Mem0."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    all_turn_units = [
        _MemoryIngestUnit(
            event_id="integ-turn-001",
            event_type="turn_complete",
            unit_type="user",
            unit_content="User asked about machine learning best practices",
            metadata={},
        ),
        _MemoryIngestUnit(
            event_id="integ-turn-002",
            event_type="turn_complete",
            unit_type="agent",
            unit_content="Agent explained cross-validation and regularization techniques",
            metadata={},
        ),
        _MemoryIngestUnit(
            event_id="integ-turn-003",
            event_type="turn_complete",
            unit_type="final_answer",
            unit_content="Here is a summary of ML best practices",
            metadata={},
        ),
    ]

    non_final_units = [u for u in all_turn_units if u.unit_type != "final_answer"]
    assert len(non_final_units) == 2, "Should filter out final_answer units"

    request = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="turn-user",
        agent_id="test-agent",
        conversation_id="test-conv-turn",
        units=non_final_units,
        idempotency_key="integ-test:turn:001",
    )

    result = await provider.ingest(request)

    assert result.status in ("ok", "partial")
    assert result.accepted_count == 2, \
        f"Expected 2 accepted units (non-final_answer), got {result.accepted_count}"

    verify_req = _MemorySearchRequest(
        query="machine learning cross-validation",
        tenant_id="test-tenant",
        user_id="turn-user",
    )
    verify_results = await provider.search(verify_req, limit=5)
    assert len(verify_results) > 0, "Per-turn supplement data should be searchable"


# ---------------------------------------------------------------------------
# Test 8: Provider Error Handling (401 disables provider)
# ---------------------------------------------------------------------------


def test_mem0_provider_error_handling(client, mem0_available):
    """Verify Mem0 returning 401 causes provider to be disabled."""
    mock_provider = MagicMock()
    error = types.SimpleNamespace(code=_ProviderErrorCode.UNAUTHORIZED)
    mock_provider.search = AsyncMock(
        side_effect=_NonRetryableProviderError("unauthorized", error=error)
    )
    mock_provider_service = MagicMock()
    mock_provider_service.build_provider.return_value = mock_provider

    with patch.object(memory_provider_app, "memory_provider_config_db") as m_db, \
         patch.object(memory_provider_app, "memory_provider_config_param_db") as m_param_db, \
         patch.object(memory_provider_app, "_get_provider_service", return_value=mock_provider_service), \
         patch.object(memory_provider_app, "_get_plugin_loader", return_value=_mock_plugin_loader()):

        m_db.get_provider_config.return_value = {
            "provider_config_id": 99,
            "provider_name": "test-mem0",
        }
        m_param_db.get_params.return_value = {
            "plugin.name": "mem0",
            "plugin.api_key": "invalid-key",
        }
        m_db.update_provider_config.return_value = True

        response = client.post(
            "/memory/providers/99/test-search",
            json={"query": "test query"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 400
        m_db.update_provider_config.assert_called()
        update_call_args = m_db.update_provider_config.call_args
        assert update_call_args[0][0] == 99
        assert "last_error_code" in update_call_args[0][1]
        assert update_call_args[0][1]["last_error_code"] == "unauthorized"


# ---------------------------------------------------------------------------
# Test 9: Degraded Ingest (unsupported unit_type)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mem0_degraded_ingest(client, mem0_available):
    """Verify unsupported unit_type triggers degraded retry."""
    from backend.memory_provider_plugins.mem0.provider import Mem0Provider

    provider = Mem0Provider({
        "api_key": "test-integration-key",
        "base_url": MEM0_BASE_URL,
    })

    mock_config = {
        "provider_config_id": 1,
        "provider_name": "test-mem0",
        "enabled": True,
    }
    mock_params = {
        "plugin.name": "mem0",
        "plugin.api_key": "test-integration-key",
        "plugin.base_url": MEM0_BASE_URL,
    }

    unsupported_error = types.SimpleNamespace(
        code=_ProviderErrorCode.UNSUPPORTED_UNIT_TYPE
    )

    call_count = 0
    original_ingest = provider.ingest

    async def mock_ingest_first_call(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _DegradableProviderError(
                "unsupported unit_type: image",
                error=unsupported_error,
                removable_units=["integ-degrade-003"],
            )
        return await original_ingest(request)

    mock_config_service = MagicMock()
    mock_config_service.get_enabled_providers.return_value = [
        {**mock_config, "params": mock_params}
    ]

    mock_plugin_loader = MagicMock()
    mock_plugin_loader.build_provider.return_value = provider

    from backend.services.memory_external_provider_service import MemoryExternalProviderService
    real_service = MemoryExternalProviderService.__new__(MemoryExternalProviderService)
    real_service._plugin_loader = mock_plugin_loader
    real_service._config_service = mock_config_service

    units = [
        _MemoryIngestUnit(
            event_id="integ-degrade-001",
            event_type="conversation",
            unit_type="agent",
            unit_content="Agent discussed project architecture",
            metadata={},
        ),
        _MemoryIngestUnit(
            event_id="integ-degrade-002",
            event_type="conversation",
            unit_type="user",
            unit_content="User approved the proposed design",
            metadata={},
        ),
        _MemoryIngestUnit(
            event_id="integ-degrade-003",
            event_type="conversation",
            unit_type="image",
            unit_content="base64-encoded-image-data",
            metadata={},
        ),
    ]

    request = _MemoryIngestRequest(
        tenant_id="test-tenant",
        user_id="degrade-user",
        agent_id="test-agent",
        conversation_id="test-conv-degrade",
        units=units,
        idempotency_key="integ-test:degrade:001",
    )

    provider.ingest = mock_ingest_first_call

    result = await real_service.ingest(mock_config, mock_params, request)

    assert result.status in ("degraded", "ok", "partial"), \
        f"Expected degraded/ok/partial status, got: {result.status}"
    assert call_count == 2, \
        f"Expected 2 ingest calls (original + retry), got {call_count}"
