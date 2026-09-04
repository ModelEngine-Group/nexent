import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

database_pkg = types.ModuleType("database")
config_db_mod = types.ModuleType("database.memory_provider_config_db")
config_db_mod.disable_provider_config = MagicMock(name="disable_provider_config")
database_pkg.memory_provider_config_db = config_db_mod
sys.modules["database"] = database_pkg
sys.modules["database.memory_provider_config_db"] = config_db_mod

consts_pkg = types.ModuleType("consts")
consts_mod = types.ModuleType("consts.const")
consts_mod.MEMORY_PROVIDER_PLUGINS_DIR = "/tmp/test-memory-provider-plugins"
consts_pkg.const = consts_mod
sys.modules["consts"] = consts_pkg
sys.modules["consts.const"] = consts_mod

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


class MemoryIngestRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_copy(self, update=None):
        new = MemoryIngestRequest(**self.__dict__)
        if update:
            new.__dict__.update(update)
        return new


class MemoryIngestResult:
    def __init__(self, **kwargs):
        self.provider = kwargs.get("provider", "")
        self.status = kwargs.get("status", "")
        self.message = kwargs.get("message", "")
        self.accepted_count = kwargs.get("accepted_count", 0)
        self.__dict__.update(kwargs)


class _ErrorCode:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        if isinstance(other, _ErrorCode):
            return self.value == other.value
        return self.value == other


class ProviderErrorCode:
    UNAUTHORIZED = _ErrorCode("unauthorized")
    FORBIDDEN = _ErrorCode("forbidden")
    UNSUPPORTED_UNIT_TYPE = _ErrorCode("unsupported_unit_type")
    PARTIAL_ACCEPTANCE = _ErrorCode("partial_acceptance")
    UNKNOWN = _ErrorCode("unknown")
    INVALID_PAYLOAD = _ErrorCode("invalid_payload")


memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_models.MemoryIngestRequest = MemoryIngestRequest
memory_models.MemoryIngestResult = MemoryIngestResult
memory_models.MemoryIngestUnit = MagicMock
memory_models.ProviderErrorCode = ProviderErrorCode
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models

providers_base = types.ModuleType("nexent.memory.providers.base")


class SearchableMemoryProvider:
    pass


class IngestibleMemoryProvider:
    pass


providers_base.SearchableMemoryProvider = SearchableMemoryProvider
providers_base.IngestibleMemoryProvider = IngestibleMemoryProvider
providers_pkg = types.ModuleType("nexent.memory.providers")
providers_pkg.__path__ = []
providers_pkg.base = providers_base
sys.modules["nexent.memory.providers"] = providers_pkg
sys.modules["nexent.memory.providers.base"] = providers_base

retry_mod = types.ModuleType("nexent.memory.providers.retry")


class DegradableProviderError(Exception):
    def __init__(self, msg="", error=None, removable_units=None):
        super().__init__(msg)
        self.error = error
        self.removable_units = removable_units or []


class NonRetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class RetryableProviderError(Exception):
    def __init__(self, msg="", error=None):
        super().__init__(msg)
        self.error = error


class RetryConfig:
    pass


async def execute_with_retry(fn, config, operation_name=""):
    return await fn()


retry_mod.DegradableProviderError = DegradableProviderError
retry_mod.NonRetryableProviderError = NonRetryableProviderError
retry_mod.RetryableProviderError = RetryableProviderError
retry_mod.RetryConfig = RetryConfig
retry_mod.execute_with_retry = execute_with_retry
sys.modules["nexent.memory.providers.retry"] = retry_mod

nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg

services_pkg = types.ModuleType("services")
config_service_mod = types.ModuleType("services.memory_provider_config_service")
plugin_loader_mod = types.ModuleType("services.memory_provider_plugin_loader")
config_service_mod.MemoryProviderConfigService = MagicMock
plugin_loader_mod.PluginLoader = MagicMock
sys.modules["services"] = services_pkg
sys.modules["services.memory_provider_config_service"] = config_service_mod
sys.modules["services.memory_provider_plugin_loader"] = plugin_loader_mod

from backend.services import memory_external_provider_service as service_module  # noqa: E402
from backend.services.memory_external_provider_service import MemoryExternalProviderService  # noqa: E402


@pytest.fixture
def mock_loader():
    loader = MagicMock()
    loader.build_provider = MagicMock()
    return loader


@pytest.fixture
def mock_config_service():
    return MagicMock()


@pytest.fixture
def service(mock_loader, mock_config_service):
    return MemoryExternalProviderService(mock_loader, mock_config_service)


def test_build_provider_success(service, mock_loader):
    mock_loader.build_provider.return_value = MagicMock()
    mock_loader.get_plugin.return_value = MagicMock(
        config_schema=[{"key": "api_key"}, {"key": "org_id"}]
    )
    config = {"provider_config_id": 1, "timeout_seconds": 17}
    params = {
        "plugin.name": "mem0",
        "plugin.api_key": "sk-123",
        "plugin.org_id": "org-1",
        "unrelated": "ignored",
    }

    provider = service.build_provider(config, params)
    mock_loader.build_provider.assert_called_once_with(
        "mem0",
        {"api_key": "sk-123", "org_id": "org-1", "timeout_seconds": 17},
    )
    assert provider is not None


def test_build_provider_supports_legacy_unprefixed_schema_params(service, mock_loader):
    mock_loader.build_provider.return_value = MagicMock()
    mock_loader.get_plugin.return_value = MagicMock(
        config_schema=[{"key": "api_key"}, {"key": "org_id"}]
    )

    service.build_provider(
        {"provider_config_id": 1, "timeout_seconds": 30},
        {
            "plugin.name": "mem0",
            "api_key": "legacy-key",
            "org_id": "legacy-org",
            "unrelated": "ignored",
        },
    )

    mock_loader.build_provider.assert_called_once_with(
        "mem0",
        {
            "api_key": "legacy-key",
            "org_id": "legacy-org",
            "timeout_seconds": 30,
        },
    )


def test_build_provider_plugin_not_found(service, mock_loader):
    mock_loader.build_provider.side_effect = ValueError("not found")
    with pytest.raises(ValueError):
        service.build_provider({}, {"plugin.name": "mem0"})


def test_build_provider_missing_plugin_name(service):
    with pytest.raises(ValueError, match="plugin.name"):
        service.build_provider({}, {})


def test_runtime_factory_loads_plugins_and_caches_service(monkeypatch):
    monkeypatch.setattr(
        sys.modules["consts.const"],
        "MEMORY_PROVIDER_PLUGINS_DIR",
        "/tmp/test-memory-provider-plugins",
        raising=False,
    )
    loader = MagicMock()
    loader_cls = MagicMock(return_value=loader)
    config_service = MagicMock()
    config_cls = MagicMock(return_value=config_service)
    monkeypatch.setattr(service_module, "PluginLoader", loader_cls)
    monkeypatch.setattr(service_module, "MemoryProviderConfigService", config_cls)
    monkeypatch.setattr(service_module, "_provider_service", None)

    first = service_module.get_memory_external_provider_service()
    second = service_module.get_memory_external_provider_service()

    loader_cls.assert_called_once()
    loader.load_all.assert_called_once_with()
    config_cls.assert_called_once_with(loader)
    assert first is second
    assert first._plugin_loader is loader
    assert first._config_service is config_service


class _SpanContext:
    def __init__(self, span):
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, exc_type, exc, traceback):
        return False


def _mock_telemetry(monkeypatch):
    span = MagicMock()
    tracer = MagicMock()
    tracer.start_as_current_span.return_value = _SpanContext(span)
    instruments = {
        "requests": MagicMock(),
        "duration": MagicMock(),
        "results": MagicMock(),
        "accepted": MagicMock(),
        "rejected": MagicMock(),
    }
    monkeypatch.setattr(service_module, "_tracer", tracer)
    monkeypatch.setattr(service_module, "_provider_requests_total", instruments["requests"])
    monkeypatch.setattr(service_module, "_provider_duration", instruments["duration"])
    monkeypatch.setattr(service_module, "_provider_search_results", instruments["results"])
    monkeypatch.setattr(service_module, "_provider_ingest_accepted", instruments["accepted"])
    monkeypatch.setattr(service_module, "_provider_ingest_rejected", instruments["rejected"])
    return tracer, span, instruments


@pytest.mark.asyncio
async def test_ac_p3_23_search_records_low_cardinality_otel(service, mock_loader, monkeypatch):
    tracer, span, instruments = _mock_telemetry(monkeypatch)
    provider = MagicMock()
    provider.search = AsyncMock(return_value=[MemorySearchResult(memory_id=1)])
    mock_loader.build_provider.return_value = provider

    results = await service.search(
        {"provider_name": "mem0-primary", "provider_config_id": 8},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="secret query", user_id="user-secret"),
    )

    assert len(results) == 1
    span_attributes = tracer.start_as_current_span.call_args.kwargs["attributes"]
    assert span_attributes == {
        "memory.operation": "search",
        "memory.provider.name": "mem0-primary",
        "memory.provider.config_id": 8,
    }
    metric_attributes = instruments["requests"].add.call_args.args[1]
    assert metric_attributes == {
        "operation": "search",
        "provider": "mem0-primary",
        "outcome": "success",
        "error_code": "none",
    }
    assert "secret" not in str(metric_attributes)
    instruments["results"].record.assert_called_once()
    span.set_attribute.assert_any_call("memory.result.count", 1)


@pytest.mark.asyncio
async def test_ac_p3_23_telemetry_failure_does_not_change_result(
    service, mock_loader, monkeypatch
):
    _, _, instruments = _mock_telemetry(monkeypatch)
    instruments["requests"].add.side_effect = RuntimeError("collector unavailable")
    provider = MagicMock()
    provider.search = AsyncMock(return_value=[MemorySearchResult(memory_id=1)])
    mock_loader.build_provider.return_value = provider

    results = await service.search(
        {"provider_name": "mem0", "provider_config_id": 8},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_ac_p3_23_span_creation_failure_does_not_change_result(
    service, mock_loader, monkeypatch
):
    tracer, _, _ = _mock_telemetry(monkeypatch)
    tracer.start_as_current_span.side_effect = RuntimeError("tracer unavailable")
    provider = MagicMock()
    provider.search = AsyncMock(return_value=[MemorySearchResult(memory_id=1)])
    mock_loader.build_provider.return_value = provider

    results = await service.search(
        {"provider_name": "mem0", "provider_config_id": 8},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_ac_p3_23_ingest_records_accepted_and_rejected_units(
    service, mock_loader, monkeypatch
):
    _, span, instruments = _mock_telemetry(monkeypatch)
    provider = MagicMock()
    provider.ingest = AsyncMock(return_value=MemoryIngestResult(
        provider="mem0",
        status="partial",
        accepted_count=2,
        rejected_count=1,
    ))
    mock_loader.build_provider.return_value = provider

    result = await service.ingest(
        {"provider_name": "mem0", "provider_config_id": 8},
        {"plugin.name": "mem0"},
        MemoryIngestRequest(units=[]),
    )

    assert result.status == "partial"
    instruments["accepted"].add.assert_called_once()
    assert instruments["accepted"].add.call_args.args[0] == 2
    instruments["rejected"].add.assert_called_once()
    assert instruments["rejected"].add.call_args.args[0] == 1
    span.set_attribute.assert_any_call("memory.unit.accepted_count", 2)
    span.set_attribute.assert_any_call("memory.unit.rejected_count", 1)


@pytest.mark.asyncio
async def test_ac_p3_23_provider_build_failure_is_observed(
    service, mock_loader, monkeypatch
):
    _, span, instruments = _mock_telemetry(monkeypatch)
    mock_loader.build_provider.side_effect = ValueError("plugin unavailable")

    results = await service.search(
        {"provider_name": "missing-plugin", "provider_config_id": 9},
        {"plugin.name": "missing"},
        MemorySearchRequest(query="hello"),
    )

    assert results == []
    attributes = instruments["requests"].add.call_args.args[1]
    assert attributes["outcome"] == "error"
    assert attributes["error_code"] == "configuration"
    span.set_attribute.assert_any_call("memory.error.code", "configuration")


@pytest.mark.asyncio
async def test_search_success(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(return_value=[MemorySearchResult(memory_id=1)])
    mock_loader.build_provider.return_value = mock_provider

    results = await service.search(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_non_retryable_disables_provider(service, mock_loader):
    mock_provider = MagicMock()
    error = types.SimpleNamespace(code=ProviderErrorCode.UNAUTHORIZED)
    mock_provider.search = AsyncMock(
        side_effect=NonRetryableProviderError("unauthorized", error=error)
    )
    mock_loader.build_provider.return_value = mock_provider

    with patch.object(config_db_mod, "disable_provider_config") as m_disable:
        results = await service.search(
            {"provider_name": "test", "provider_config_id": 1},
            {"plugin.name": "mem0"},
            MemorySearchRequest(query="hello"),
        )
        assert results == []
        m_disable.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_search_degradable_error_returns_empty(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(
        side_effect=DegradableProviderError("timeout")
    )
    mock_loader.build_provider.return_value = mock_provider

    results = await service.search(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_retryable_error_returns_empty(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(
        side_effect=RetryableProviderError("rate limited")
    )
    mock_loader.build_provider.return_value = mock_provider

    results = await service.search(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_unexpected_error_returns_empty(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.search = AsyncMock(side_effect=RuntimeError("boom"))
    mock_loader.build_provider.return_value = mock_provider

    results = await service.search(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemorySearchRequest(query="hello"),
    )
    assert results == []


@pytest.mark.asyncio
async def test_ingest_success(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.ingest = AsyncMock(
        return_value=MemoryIngestResult(provider="test", status="ok")
    )
    mock_loader.build_provider.return_value = mock_provider

    result = await service.ingest(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemoryIngestRequest(units=[]),
    )
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_ingest_non_retryable_disables(service, mock_loader):
    mock_provider = MagicMock()
    error = types.SimpleNamespace(code=ProviderErrorCode.UNAUTHORIZED)
    mock_provider.ingest = AsyncMock(
        side_effect=NonRetryableProviderError("unauthorized", error=error)
    )
    mock_loader.build_provider.return_value = mock_provider

    with patch.object(config_db_mod, "disable_provider_config") as m_disable:
        result = await service.ingest(
            {"provider_name": "test", "provider_config_id": 1},
            {"plugin.name": "mem0"},
            MemoryIngestRequest(units=[]),
        )
        assert result.status == "error"
        m_disable.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_ingest_degradable_unsupported_unit_type_retries(service, mock_loader):
    mock_provider = MagicMock()
    unit1 = MagicMock(event_id="u1")
    unit2 = MagicMock(event_id="u2")
    error = types.SimpleNamespace(code=ProviderErrorCode.UNSUPPORTED_UNIT_TYPE)
    mock_provider.ingest = AsyncMock(
        side_effect=[
            DegradableProviderError("unsupported", error=error, removable_units=["u1"]),
            MemoryIngestResult(provider="test", status="ok", accepted_count=1),
        ]
    )
    mock_loader.build_provider.return_value = mock_provider

    request = MemoryIngestRequest(units=[unit1, unit2])
    result = await service.ingest(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        request,
    )
    assert result.status == "degraded"


@pytest.mark.asyncio
async def test_ingest_unexpected_error(service, mock_loader):
    mock_provider = MagicMock()
    mock_provider.ingest = AsyncMock(side_effect=RuntimeError("boom"))
    mock_loader.build_provider.return_value = mock_provider

    result = await service.ingest(
        {"provider_name": "test", "provider_config_id": 1},
        {"plugin.name": "mem0"},
        MemoryIngestRequest(units=[]),
    )
    assert result.status == "error"


@pytest.mark.asyncio
async def test_search_all_enabled_concat_results(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = [
        {"provider_name": "p1", "provider_config_id": 1, "params": {"plugin.name": "mem0"}},
        {"provider_name": "p2", "provider_config_id": 2, "params": {"plugin.name": "mem0"}},
    ]

    r1 = [MemorySearchResult(memory_id=1)]
    r2 = [MemorySearchResult(memory_id=2)]

    with patch.object(service, "search", new_callable=AsyncMock, side_effect=[r1, r2]):
        results = await service.search_all_enabled("t1", MemorySearchRequest(query="hi"))
        assert len(results) == 2


@pytest.mark.asyncio
async def test_search_all_enabled_provider_failure_isolation(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = [
        {"provider_name": "p1", "provider_config_id": 1, "params": {"plugin.name": "mem0"}},
        {"provider_name": "p2", "provider_config_id": 2, "params": {"plugin.name": "mem0"}},
    ]

    r2 = [MemorySearchResult(memory_id=2)]

    with patch.object(service, "search", new_callable=AsyncMock, side_effect=[Exception("fail"), r2]):
        results = await service.search_all_enabled("t1", MemorySearchRequest(query="hi"))
        assert len(results) == 1


@pytest.mark.asyncio
async def test_search_all_enabled_empty(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = []
    results = await service.search_all_enabled("t1", MemorySearchRequest(query="hi"))
    assert results == []


@pytest.mark.asyncio
async def test_ingest_all_enabled(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = [
        {"provider_name": "p1", "provider_config_id": 1, "params": {"plugin.name": "mem0"}},
    ]

    with patch.object(
        service, "ingest", new_callable=AsyncMock,
        return_value=MemoryIngestResult(provider="p1", status="ok"),
    ):
        results = await service.ingest_all_enabled("t1", MemoryIngestRequest(units=[]))
        assert len(results) == 1


@pytest.mark.asyncio
async def test_ingest_all_enabled_provider_failure_isolation(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = [
        {"provider_name": "p1", "provider_config_id": 1, "params": {"plugin.name": "mem0"}},
        {"provider_name": "p2", "provider_config_id": 2, "params": {"plugin.name": "mem0"}},
    ]

    ok_result = MemoryIngestResult(provider="p2", status="ok")

    with patch.object(service, "ingest", new_callable=AsyncMock, side_effect=[Exception("fail"), ok_result]):
        results = await service.ingest_all_enabled("t1", MemoryIngestRequest(units=[]))
        assert len(results) == 2
        assert results[0].status == "error"
        assert results[1].status == "ok"


@pytest.mark.asyncio
async def test_ingest_all_enabled_empty(service, mock_config_service):
    mock_config_service.get_enabled_providers.return_value = []
    results = await service.ingest_all_enabled("t1", MemoryIngestRequest(units=[]))
    assert results == []
