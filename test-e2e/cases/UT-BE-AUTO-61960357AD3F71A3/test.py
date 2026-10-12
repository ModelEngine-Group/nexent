from __future__ import annotations

import asyncio

import pytest

import services.memory_external_provider_service as svc
from services.memory_external_provider_service import MemoryExternalProviderService
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryIngestUnit,
    MemorySearchRequest,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
)
from nexent.memory.providers.retry import (
    DegradableProviderError,
    NonRetryableProviderError,
    RetryableProviderError,
)

CASE_ID = 'UT-BE-AUTO-61960357AD3F71A3'

RETRY_MAX_ATTEMPTS = 3


def _provider_error(code, severity):
    return ProviderError(code=code, message=code.value, severity=severity)


def _retryable(code):
    err = _provider_error(code, ProviderErrorSeverity.RETRYABLE)
    return RetryableProviderError(err.message, err)


def _non_retryable(code):
    err = _provider_error(code, ProviderErrorSeverity.NON_RETRYABLE)
    return NonRetryableProviderError(err.message, err)


def _degradable(code, removable_units=None):
    err = _provider_error(code, ProviderErrorSeverity.DEGRADABLE)
    return DegradableProviderError(err.message, err, removable_units)


class FakeProvider:
    def __init__(self):
        self.search_responses = []
        self.ingest_responses = []
        self.search_calls = 0
        self.ingest_calls = 0
        self.search_requests = []
        self.ingest_requests = []

    @property
    def provider_name(self):
        return 'fake'

    async def search(self, request, limit=5):
        self.search_calls += 1
        self.search_requests.append(request)
        resp = self.search_responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def ingest(self, request):
        self.ingest_calls += 1
        self.ingest_requests.append(request)
        resp = self.ingest_responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakePluginLoader:
    def __init__(self, provider):
        self._provider = provider

    def get_plugin(self, name):
        return None

    def build_provider(self, name, config):
        return self._provider


def _make_ingest_request(event_ids):
    units = [
        MemoryIngestUnit(
            event_id=eid,
            event_type='agent',
            unit_type='model_output',
            unit_content='content-' + eid,
        )
        for eid in event_ids
    ]
    return MemoryIngestRequest(
        tenant_id='tenant-a',
        user_id='user-a',
        units=units,
        idempotency_key='idem-1',
    )


def _make_search_request():
    return MemorySearchRequest(query='hello', tenant_id='tenant-a', user_id='user-a')


def _config(provider_config_id):
    cfg = {'provider_name': 'fake-provider'}
    if provider_config_id is not None:
        cfg['provider_config_id'] = provider_config_id
    return cfg


@pytest.mark.asyncio
@pytest.mark.stage('D1')
@pytest.mark.case_id(CASE_ID)
async def test_external_provider_error_matrix(monkeypatch):
    disable_calls = []

    async def _noop_sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, 'sleep', _noop_sleep)

    def _fake_disable(provider_config_id):
        disable_calls.append(provider_config_id)
        return True

    monkeypatch.setattr(svc.memory_provider_config_db, 'disable_provider_config', _fake_disable)

    params = {'plugin.name': 'fake-plugin'}
    search_req = _make_search_request()

    # 1. Retryable errors (timeout / rate_limited / provider_error):
    #    retry exhausts RetryConfig, then degrade to []/error without disabling.
    for code in (
        ProviderErrorCode.TIMEOUT,
        ProviderErrorCode.RATE_LIMITED,
        ProviderErrorCode.PROVIDER_ERROR,
    ):
        provider = FakeProvider()
        provider.search_responses = [_retryable(code)] * RETRY_MAX_ATTEMPTS
        provider.ingest_responses = [_retryable(code)] * RETRY_MAX_ATTEMPTS
        service = MemoryExternalProviderService(
            plugin_loader=FakePluginLoader(provider), config_service=None
        )

        results = await service.search(_config(10), params, search_req)
        assert results == []
        assert provider.search_calls == RETRY_MAX_ATTEMPTS

        disable_calls.clear()
        ingest_req = _make_ingest_request(['e1'])
        result = await service.ingest(_config(10), params, ingest_req)
        assert result.status == 'error'
        assert provider.ingest_calls == RETRY_MAX_ATTEMPTS
        assert disable_calls == []

    # 2. Non-retryable errors (unauthorized / forbidden): no retry, disable once.
    for code in (ProviderErrorCode.UNAUTHORIZED, ProviderErrorCode.FORBIDDEN):
        provider = FakeProvider()
        provider.search_responses = [_non_retryable(code)]
        provider.ingest_responses = [_non_retryable(code)]
        service = MemoryExternalProviderService(
            plugin_loader=FakePluginLoader(provider), config_service=None
        )

        disable_calls.clear()
        results = await service.search(_config(42), params, search_req)
        assert results == []
        assert provider.search_calls == 1
        assert disable_calls == [42]

        disable_calls.clear()
        ingest_req = _make_ingest_request(['e1'])
        result = await service.ingest(_config(42), params, ingest_req)
        assert result.status == 'error'
        assert provider.ingest_calls == 1
        assert disable_calls == [42]

    # 3a. unsupported_unit_type with partial removable_units: remove then retry once.
    provider = FakeProvider()
    provider.ingest_responses = [
        _degradable(ProviderErrorCode.UNSUPPORTED_UNIT_TYPE, removable_units=['e2']),
        MemoryIngestResult(provider='fake', status='ok', accepted_count=2),
    ]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    ingest_req = _make_ingest_request(['e1', 'e2', 'e3'])
    result = await service.ingest(_config(7), params, ingest_req)
    assert result.status == 'degraded'
    assert result.accepted_count == 2
    assert provider.ingest_calls == 2
    retried_ids = [u.event_id for u in provider.ingest_requests[-1].units]
    assert retried_ids == ['e1', 'e3']

    # 3b. all units removed: no retry, accepted_count=0, message 'All units rejected'.
    provider = FakeProvider()
    provider.ingest_responses = [
        _degradable(ProviderErrorCode.UNSUPPORTED_UNIT_TYPE, removable_units=['e1', 'e2']),
    ]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    ingest_req = _make_ingest_request(['e1', 'e2'])
    result = await service.ingest(_config(7), params, ingest_req)
    assert result.status == 'degraded'
    assert result.accepted_count == 0
    assert result.message == 'All units rejected'
    assert provider.ingest_calls == 1

    # 3c. empty removable_units: no retry.
    provider = FakeProvider()
    provider.ingest_responses = [
        _degradable(ProviderErrorCode.UNSUPPORTED_UNIT_TYPE, removable_units=[]),
    ]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    ingest_req = _make_ingest_request(['e1'])
    result = await service.ingest(_config(7), params, ingest_req)
    assert result.status == 'degraded'
    assert provider.ingest_calls == 1

    # 3d. retry after degradation still fails -> error.
    provider = FakeProvider()
    provider.ingest_responses = [
        _degradable(ProviderErrorCode.UNSUPPORTED_UNIT_TYPE, removable_units=['e2']),
        _retryable(ProviderErrorCode.PROVIDER_ERROR),
    ]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    ingest_req = _make_ingest_request(['e1', 'e2'])
    result = await service.ingest(_config(7), params, ingest_req)
    assert result.status == 'error'
    assert result.message == 'Retry after degradation failed'
    assert provider.ingest_calls == 2

    # 4. partial_acceptance: degraded, no removal and no retry.
    provider = FakeProvider()
    provider.ingest_responses = [
        _degradable(ProviderErrorCode.PARTIAL_ACCEPTANCE, removable_units=None),
    ]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    ingest_req = _make_ingest_request(['e1', 'e2'])
    result = await service.ingest(_config(7), params, ingest_req)
    assert result.status == 'degraded'
    assert result.message == 'Partial acceptance'
    assert provider.ingest_calls == 1

    # 5. missing plugin.name: ValueError captured, no external call.
    provider = FakeProvider()
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    results = await service.search(_config(7), {}, search_req)
    assert results == []
    assert provider.search_calls == 0
    ingest_req = _make_ingest_request(['e1'])
    result = await service.ingest(_config(7), {}, ingest_req)
    assert result.status == 'error'
    assert result.message == 'Invalid provider configuration'
    assert provider.ingest_calls == 0

    # 6. provider_config_id None: non-retryable error only logs, never disables.
    provider = FakeProvider()
    provider.search_responses = [_non_retryable(ProviderErrorCode.UNAUTHORIZED)]
    provider.ingest_responses = [_non_retryable(ProviderErrorCode.UNAUTHORIZED)]
    service = MemoryExternalProviderService(
        plugin_loader=FakePluginLoader(provider), config_service=None
    )
    disable_calls.clear()
    results = await service.search(_config(None), params, search_req)
    assert results == []
    assert disable_calls == []

    disable_calls.clear()
    ingest_req = _make_ingest_request(['e1'])
    result = await service.ingest(_config(None), params, ingest_req)
    assert result.status == 'error'
    assert disable_calls == []
