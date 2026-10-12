from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import MagicMock

from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryIngestUnit,
    MemorySearchRequest,
    MemorySearchResult,
)
from services.memory_external_provider_service import MemoryExternalProviderService

CASE_ID = "UT-BE-AUTO-DEEA64C99389DF98"


class FakeProvider:
    """Deterministic in-memory provider standing in for an external plugin."""

    def __init__(
        self,
        name: str,
        search_results: Optional[List[MemorySearchResult]] = None,
        search_error: Optional[Exception] = None,
        ingest_result: Optional[MemoryIngestResult] = None,
        ingest_error: Optional[Exception] = None,
    ) -> None:
        self.provider_name = name
        self._search_results = list(search_results or [])
        self._search_error = search_error
        self._ingest_result = ingest_result
        self._ingest_error = ingest_error
        self.search_calls: List[tuple] = []
        self.ingest_calls: List[object] = []

    async def search(self, request, limit=5, filters=None):
        self.search_calls.append((request, limit))
        if self._search_error is not None:
            raise self._search_error
        return list(self._search_results)

    async def ingest(self, request):
        self.ingest_calls.append(request)
        if self._ingest_error is not None:
            raise self._ingest_error
        return self._ingest_result


class FakePluginLoader:
    """PluginLoader substitute that returns pre-built fake providers."""

    def __init__(self, providers: Dict[str, FakeProvider]) -> None:
        self._providers = providers
        self.built_configs: Dict[str, Dict[str, Any]] = {}

    def get_plugin(self, name: str):
        return None

    def build_provider(self, name: str, config: Dict[str, Any]) -> FakeProvider:
        self.built_configs[name] = dict(config)
        return self._providers[name]


def _search_result(content: str, score: float) -> MemorySearchResult:
    return MemorySearchResult(content=content, score=score, is_external=True)


def _provider_config(
    name: str,
    config_id: int,
    extra_params: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    params = {"plugin.name": name}
    if extra_params:
        params.update(extra_params)
    return {
        "provider_name": name,
        "provider_config_id": config_id,
        "params": params,
    }


def _search_request() -> MemorySearchRequest:
    return MemorySearchRequest(query="hello", tenant_id="tenant-a", user_id="user-1")


def _ingest_request() -> MemoryIngestRequest:
    return MemoryIngestRequest(
        tenant_id="tenant-a",
        user_id="user-1",
        units=[
            MemoryIngestUnit(
                event_id="e1",
                event_type="message",
                unit_type="text",
                unit_content="hi",
            )
        ],
        idempotency_key="idem-1",
    )


def _make_service(providers: Dict[str, FakeProvider]):
    config_service = MagicMock()
    loader = FakePluginLoader(providers)
    service = MemoryExternalProviderService(
        plugin_loader=loader,
        config_service=config_service,
    )
    return service, config_service, loader


async def _passthrough_retry(operation, config, operation_name: str = "operation"):
    return await operation()


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
async def test_external_provider_fanout_and_fault_isolation(monkeypatch, caplog):
    import services.memory_external_provider_service as provider_module

    monkeypatch.setattr(provider_module, "execute_with_retry", _passthrough_retry)
    caplog.set_level(logging.WARNING, logger="memory_external_provider_service")

    r1a = _search_result("p1-a", 0.9)
    r1b = _search_result("p1-b", 0.8)
    r2a = _search_result("p2-a", 0.7)

    p1 = FakeProvider("p1", search_results=[r1a, r1b])
    p2 = FakeProvider("p2", search_results=[r2a])
    service, config_service, _loader = _make_service({"p1": p1, "p2": p2})
    config_service.get_enabled_providers.return_value = [
        _provider_config("p1", 1),
        _provider_config("p2", 2),
    ]

    results = await service.search_all_enabled("tenant-a", _search_request(), limit=5)

    config_service.get_enabled_providers.assert_called_once_with("tenant-a")
    assert len(p1.search_calls) == 1
    assert len(p2.search_calls) == 1
    assert [r.content for r in results] == ["p1-a", "p1-b", "p2-a"]
    assert len(results) == 3

    failing = FakeProvider("p1", search_error=RuntimeError("provider down"))
    ok = FakeProvider("p2", search_results=[r2a])
    service, config_service, _loader = _make_service({"p1": failing, "p2": ok})
    config_service.get_enabled_providers.return_value = [
        _provider_config("p1", 1),
        _provider_config("p2", 2),
    ]

    results = await service.search_all_enabled("tenant-a", _search_request(), limit=5)

    assert [r.content for r in results] == ["p2-a"]
    assert len(failing.search_calls) == 1
    assert len(ok.search_calls) == 1

    service, config_service, _loader = _make_service({})
    config_service.get_enabled_providers.return_value = []

    assert await service.search_all_enabled("tenant-a", _search_request(), limit=5) == []

    normal_result = MemoryIngestResult(
        provider="p1", status="accepted", accepted_count=1
    )
    good = FakeProvider("p1", ingest_result=normal_result)
    bad = FakeProvider("p2", ingest_error=RuntimeError("ingest failed"))
    service, config_service, _loader = _make_service({"p1": good, "p2": bad})
    config_service.get_enabled_providers.return_value = [
        _provider_config("p1", 1),
        _provider_config("p2", 2),
    ]

    results = await service.ingest_all_enabled("tenant-a", _ingest_request())

    assert len(results) == 2
    assert results[0].provider == "p1"
    assert results[0].status == "accepted"
    assert results[1].provider == "p2"
    assert results[1].status == "error"
    assert len(good.ingest_calls) == 1
    assert len(bad.ingest_calls) == 1

    service, config_service, _loader = _make_service(
        {"p1": FakeProvider("p1", ingest_result=normal_result)}
    )
    config_service.get_enabled_providers.return_value = [_provider_config("p1", 1)]
    service.ingest = MagicMock(side_effect=RuntimeError("uncaught ingest failure"))

    results = await service.ingest_all_enabled("tenant-a", _ingest_request())

    assert len(results) == 1
    assert results[0].status == "error"

    service, config_service, _loader = _make_service({})
    config_service.get_enabled_providers.return_value = []

    assert await service.ingest_all_enabled("tenant-a", _ingest_request()) == []

    secret = "sk-7f1e0d2c4b6a8f9e"
    caplog.clear()
    leaking = FakeProvider("p1", search_error=RuntimeError("provider error"))
    service, config_service, loader = _make_service({"p1": leaking})
    config_service.get_enabled_providers.return_value = [
        _provider_config("p1", 1, extra_params={"plugin.api_key": secret}),
    ]

    await service.search_all_enabled("tenant-a", _search_request(), limit=5)

    assert loader.built_configs.get("p1", {}).get("api_key") == secret
    assert secret not in caplog.text
    assert "Unexpected error" in caplog.text
