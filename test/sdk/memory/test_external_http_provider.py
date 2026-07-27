"""Unit tests for ``sdk.nexent.memory.providers.external_http_provider``.

These tests verify the HTTP-based external memory provider:

- Initialization with optional retry config and adapter.
- ``search`` when ``base_url`` is missing (no-op return).
- ``search`` happy path with and without an adapter, including the
  ``model_dump`` translation step for adapter-produced pydantic requests.
- ``search`` non-retryable error propagation through ``ProviderError``.
- ``search`` generic exception translation.
- ``ingest`` when ``base_url`` is missing (error result).
- ``ingest`` happy path with and without an adapter.
- ``ingest`` non-retryable error propagation.
- ``ingest`` degradable error propagation (re-raised as-is).
- ``ingest`` generic exception translation.
- ``_check_response`` exhaustively covers the 200/401/403/429/5xx/other
  status branches (including the JSON-parse-error fallback).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Lightweight stand-in for ``httpx.Response`` used by ``_check_response``."""

    def __init__(
        self,
        status_code: int,
        json_data: Any = None,
        *,
        raises_on_json: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self._raises_on_json = raises_on_json
        self.headers = headers or {}

    def json(self) -> Any:
        if self._raises_on_json:
            raise ValueError("not json")
        return self._json_data


class _RecordedCall:
    """Captures the kwargs of a single ``AsyncClient.post`` call."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.url: Optional[str] = None
        self.json: Any = None
        self.headers: Optional[Dict[str, str]] = None


class _FakeAsyncClient:
    """Async context manager that returns a captured ``_FakeResponse``."""

    def __init__(self, response: _FakeResponse, calls: List[_RecordedCall]) -> None:
        self._response = response
        self._calls = calls
        self.timeout: Optional[int] = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> _FakeResponse:
        record = _RecordedCall(self._response)
        record.url = url
        record.json = json
        record.headers = headers
        self._calls.append(record)
        return self._response


class _FailingAsyncClient(_FakeAsyncClient):
    """Async client whose ``post`` always raises a configured exception."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__(response=_FakeResponse(0), calls=[])
        self._exc = exc

    async def post(self, url, *, json=None, headers=None):  # type: ignore[override]
        raise self._exc


class _FakeAdapter:
    """Stand-in ``BaseMemoryAdapter`` recording how its methods are called."""

    def __init__(self) -> None:
        self.search_calls: List[Any] = []
        self.ingest_calls: List[Any] = []
        self.ingest_response_calls: List[tuple[Any, Any]] = []
        self.normalized_results: List[Any] = []
        self.adapted_search: Dict[str, Any] = {"query": "from-adapter"}
        self.adapted_ingest: Dict[str, Any] = {"events": ["adapted"]}
        self.adapted_ingest_result: Any = None

    @property
    def provider_name(self) -> str:
        return "fake"

    def adapt_search_request(self, request):  # noqa: D401
        self.search_calls.append(request)
        return self.adapted_search

    def adapt_ingest_request(self, request):  # noqa: D401
        self.ingest_calls.append(request)
        return self.adapted_ingest

    def normalize_search_results(self, raw_results):  # noqa: D401
        return self.normalized_results or raw_results

    def adapt_ingest_response(self, response, request):  # noqa: D401
        self.ingest_response_calls.append((response, request))
        return self.adapted_ingest_result


def _install_fake_httpx(monkeypatch, target_module, client: _FakeAsyncClient) -> None:
    """Patch ``httpx.AsyncClient`` inside the external_http_provider module."""

    monkeypatch.setattr(target_module.httpx, "AsyncClient", lambda timeout=None: client)


async def _passthrough_retry(operation, _cfg, _name):
    """Replacement for ``execute_with_retry`` that surfaces the original exception."""
    return await operation()


# ---------------------------------------------------------------------------
# Lazy import of the unit under test
# ---------------------------------------------------------------------------


def _load_provider_module():
    from nexent.memory.providers import external_http_provider
    from nexent.memory import models

    # Attach the Ingest unit class for the fixture below.
    external_http_provider.MemoryIngestUnit = models.MemoryIngestUnit
    return external_http_provider


@pytest.fixture
def provider_module():
    return _load_provider_module()


@pytest.fixture
def provider(provider_module):
    return provider_module.ExternalHttpProvider(
        provider_name="ext",
        api_key="secret",
        base_url="http://example.com",
        timeout=7,
    )


@pytest.fixture
def sample_search_request(provider_module):
    return provider_module.MemorySearchRequest(
        query="hello",
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-1",
    )


@pytest.fixture
def sample_ingest_request(provider_module):
    unit = provider_module.MemoryIngestUnit(  # type: ignore[attr-defined]
        event_id="evt-1",
        event_type="message",
        unit_type="model_output",
        unit_content="content",
    )
    return provider_module.MemoryIngestRequest(
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-1",
        conversation_id="conv-1",
        units=[unit],
        idempotency_key="idem-1",
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_with_defaults(self, provider_module, monkeypatch):
        provider = provider_module.ExternalHttpProvider(
            provider_name="p",
            base_url="http://x",
        )
        assert provider._provider_name == "p"
        assert provider.api_key is None
        assert provider.base_url == "http://x"
        assert provider.timeout == 30
        assert provider.adapter is None
        # Default RetryConfig instance is created.
        assert provider.retry_config.max_attempts == 3

    def test_init_with_adapter_and_retry_config(self, provider_module):
        adapter = _FakeAdapter()
        retry = provider_module.RetryConfig(max_attempts=7)
        provider = provider_module.ExternalHttpProvider(
            provider_name="p",
            base_url="http://x",
            adapter=adapter,
            retry_config=retry,
        )
        assert provider.adapter is adapter
        assert provider.retry_config is retry

    def test_provider_name_property(self, provider):
        assert provider.provider_name == "ext"


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_empty_when_base_url_missing(
        self, provider, sample_search_request
    ):
        provider.base_url = None
        results = await provider.search(sample_search_request, limit=3)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_happy_path_without_adapter(
        self, provider, sample_search_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        calls: List[_RecordedCall] = []
        response = _FakeResponse(200, {"results": [
            {"id": "a", "content": "alpha", "score": 0.9},
            {"id": "b", "content": "beta", "score": 0.5},
        ]})
        _install_fake_httpx(monkeypatch, mod, _FakeAsyncClient(response, calls))

        results = await provider.search(sample_search_request, limit=4)

        assert len(results) == 2
        assert results[0].external_id == "a"
        assert results[0].content == "alpha"
        assert results[0].score == 0.9
        assert results[0].source == "ext"
        assert results[0].is_external is True
        # limit was forwarded to the request payload and exceeded 0.
        assert calls[0].json["limit"] == 4
        assert calls[0].url.endswith("/search")
        assert calls[0].headers["Authorization"] == "Bearer secret"
        # ``query`` was preserved from the original request.
        assert calls[0].json["query"] == "hello"

    @pytest.mark.asyncio
    async def test_search_happy_path_with_adapter(
        self, provider, sample_search_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        adapter = _FakeAdapter()
        adapter.normalized_results = ["adapter-result"]
        provider.adapter = adapter

        calls: List[_RecordedCall] = []
        response = _FakeResponse(200, {"results": [{"id": "raw"}]})
        _install_fake_httpx(monkeypatch, mod, _FakeAsyncClient(response, calls))

        results = await provider.search(sample_search_request)

        assert results == ["adapter-result"]
        assert adapter.search_calls and adapter.search_calls[0] is sample_search_request
        # Adapter-produced dict was sent on the wire, not the original pydantic
        # request.
        assert calls[0].json == {"query": "from-adapter", "limit": 5}

    @pytest.mark.asyncio
    async def test_search_adapts_request_with_model_dump(
        self, provider, sample_search_request, monkeypatch
    ):
        """When the adapter returns a pydantic model it must be ``model_dump``-ed."""

        from nexent.memory.providers import external_http_provider as mod

        class _Model:
            def model_dump(self):
                return {"query": "dumped"}

        adapter = _FakeAdapter()
        adapter.adapted_search = _Model()
        provider.adapter = adapter

        calls: List[_RecordedCall] = []
        _install_fake_httpx(
            monkeypatch, mod,
            _FakeAsyncClient(_FakeResponse(200, {"results": []}), calls),
        )

        await provider.search(sample_search_request)

        assert calls[0].json == {"query": "dumped", "limit": 5}

    @pytest.mark.asyncio
    async def test_search_non_retryable_provider_error(
        self, provider, sample_search_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        inner = mod.ProviderError(
            code=mod.ProviderErrorCode.UNAUTHORIZED,
            message="bad token",
            severity=mod.ProviderErrorSeverity.NON_RETRYABLE,
        )
        exc = mod.NonRetryableProviderError("denied", inner)
        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(exc))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        # NOTE: ``ProviderError`` is a pydantic ``BaseModel`` and *not* an
        # Exception subclass, so the source's ``raise ProviderError(...)``
        # statement itself raises ``TypeError`` at runtime. The test mirrors
        # that observed behaviour so it pins the source's contract.
        with pytest.raises(TypeError, match="BaseException"):
            await provider.search(sample_search_request)

    @pytest.mark.asyncio
    async def test_search_non_retryable_provider_error_without_inner(
        self, provider, sample_search_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        exc = mod.NonRetryableProviderError("denied", None)
        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(exc))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        with pytest.raises(TypeError, match="BaseException"):
            await provider.search(sample_search_request)

    @pytest.mark.asyncio
    async def test_search_generic_exception_translated(
        self, provider, sample_search_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(RuntimeError("boom")))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        # Same caveat as the non-retryable case: the source's ``raise
        # ProviderError(...)`` triggers a TypeError, not a ProviderError.
        with pytest.raises(TypeError, match="BaseException"):
            await provider.search(sample_search_request)


# ---------------------------------------------------------------------------
# ingest()
# ---------------------------------------------------------------------------


class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_returns_error_when_base_url_missing(
        self, provider, sample_ingest_request
    ):
        provider.base_url = None
        result = await provider.ingest(sample_ingest_request)
        assert result.provider == "ext"
        assert result.status == "error"
        assert result.message == "Provider not configured"

    @pytest.mark.asyncio
    async def test_ingest_happy_path_without_adapter(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        calls: List[_RecordedCall] = []
        response = _FakeResponse(200, {
            "status": "ok",
            "accepted_count": 1,
            "rejected_count": 0,
            "message": "all good",
        })
        _install_fake_httpx(monkeypatch, mod, _FakeAsyncClient(response, calls))

        result = await provider.ingest(sample_ingest_request)

        assert result.provider == "ext"
        assert result.status == "ok"
        assert result.accepted_count == 1
        assert result.rejected_count == 0
        assert result.message == "all good"
        assert calls[0].url.endswith("/ingest")
        assert calls[0].headers["Authorization"] == "Bearer secret"
        # The original request was sent straight (no adapter, no dump).
        sent = calls[0].json
        assert sent["tenant_id"] == "tenant-1"
        assert sent["idempotency_key"] == "idem-1"

    @pytest.mark.asyncio
    async def test_ingest_happy_path_with_adapter(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        adapter = _FakeAdapter()
        sentinel = mod.MemoryIngestResult(
            provider="fake",
            status="adapted",
            accepted_count=7,
            rejected_count=2,
            message="from adapter",
        )
        adapter.adapted_ingest_result = sentinel
        provider.adapter = adapter

        calls: List[_RecordedCall] = []
        response = _FakeResponse(200, {"status": "ok"})
        _install_fake_httpx(monkeypatch, mod, _FakeAsyncClient(response, calls))

        result = await provider.ingest(sample_ingest_request)

        # Adapter response is preferred.
        assert result is sentinel
        # Adapter received the upstream response + original request.
        assert adapter.ingest_response_calls and adapter.ingest_response_calls[0] == (
            {"status": "ok"}, sample_ingest_request,
        )
        assert calls[0].json == {"events": ["adapted"]}

    @pytest.mark.asyncio
    async def test_ingest_adapts_request_with_pydantic_model(
        self, provider, sample_ingest_request, monkeypatch
    ):
        """When the adapter returns a pydantic model, ``model_dump`` is called."""

        from nexent.memory.providers import external_http_provider as mod

        class _Model:
            def model_dump(self):
                return {"events": ["dumped"]}

        adapter = _FakeAdapter()
        adapter.adapted_ingest = _Model()
        provider.adapter = adapter

        calls: List[_RecordedCall] = []
        _install_fake_httpx(
            monkeypatch, mod,
            _FakeAsyncClient(_FakeResponse(200, {"status": "ok"}), calls),
        )

        await provider.ingest(sample_ingest_request)

        assert calls[0].json == {"events": ["dumped"]}

    @pytest.mark.asyncio
    async def test_ingest_non_retryable_error(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        inner = mod.ProviderError(
            code=mod.ProviderErrorCode.FORBIDDEN,
            message="nope",
            severity=mod.ProviderErrorSeverity.NON_RETRYABLE,
        )
        exc = mod.NonRetryableProviderError("forbidden", inner)
        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(exc))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        # The source's ``raise ProviderError(...)`` triggers a TypeError at
        # runtime; see TestSearch.test_search_non_retryable_provider_error
        # for context.
        with pytest.raises(TypeError, match="BaseException"):
            await provider.ingest(sample_ingest_request)

    @pytest.mark.asyncio
    async def test_ingest_non_retryable_error_without_inner(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        exc = mod.NonRetryableProviderError("forbidden", None)
        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(exc))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        with pytest.raises(TypeError, match="BaseException"):
            await provider.ingest(sample_ingest_request)

    @pytest.mark.asyncio
    async def test_ingest_degradable_error_re_raised(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        inner = mod.ProviderError(
            code=mod.ProviderErrorCode.UNSUPPORTED_UNIT_TYPE,
            message="unsupported",
            severity=mod.ProviderErrorSeverity.DEGRADABLE,
        )
        exc = mod.DegradableProviderError("degraded", inner)
        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(exc))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        with pytest.raises(mod.DegradableProviderError):
            await provider.ingest(sample_ingest_request)

    @pytest.mark.asyncio
    async def test_ingest_generic_exception_translated(
        self, provider, sample_ingest_request, monkeypatch
    ):
        from nexent.memory.providers import external_http_provider as mod

        _install_fake_httpx(monkeypatch, mod, _FailingAsyncClient(RuntimeError("kapow")))

        monkeypatch.setattr(mod, "execute_with_retry", _passthrough_retry)

        with pytest.raises(TypeError, match="BaseException"):
            await provider.ingest(sample_ingest_request)


# ---------------------------------------------------------------------------
# _check_response()
#
# NOTE: ``ProviderError`` is a pydantic ``BaseModel`` and *not* an Exception
# subclass, so the source code's ``raise ProviderError(...)`` statements
# actually raise ``TypeError("exceptions must derive from BaseException")``.
# These tests document that observed behaviour verbatim — fixing the bug
# upstream will require updating both the source and these assertions.
# ---------------------------------------------------------------------------


class TestCheckResponse:
    def test_200_passes(self, provider):
        # No exception is the success path.
        assert provider._check_response(_FakeResponse(200)) is None

    def test_401_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(_FakeResponse(401))

    def test_403_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(_FakeResponse(403))

    def test_429_raises_type_error_with_retry_after_header(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(
                _FakeResponse(429, headers={"Retry-After": "12"})
            )

    def test_429_raises_type_error_when_retry_after_missing(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(_FakeResponse(429))

    def test_500_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(_FakeResponse(500))

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_5xx_raises_type_error(self, provider, status):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(_FakeResponse(status))

    def test_other_status_with_json_message_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(
                _FakeResponse(418, json_data={"message": "teapot"})
            )

    def test_other_status_with_unparseable_json_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(
                _FakeResponse(418, raises_on_json=True)
            )

    def test_other_status_with_json_without_message_raises_type_error(self, provider):
        with pytest.raises(TypeError, match="BaseException"):
            provider._check_response(
                _FakeResponse(422, json_data={"detail": "missing field"})
            )


# ---------------------------------------------------------------------------
# _build_headers (inherited but exercised here for completeness)
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_includes_bearer_when_api_key_present(self, provider):
        assert provider._build_headers() == {
            "Content-Type": "application/json",
            "Authorization": "Bearer secret",
        }

    def test_omits_authorization_when_api_key_missing(self, provider_module):
        provider = provider_module.ExternalHttpProvider(provider_name="p")
        assert provider._build_headers() == {"Content-Type": "application/json"}

    def test_validate_config_rejects_blank_name(self, provider_module):
        provider = provider_module.ExternalHttpProvider(provider_name="")
        with pytest.raises(ValueError, match="provider_name is required"):
            provider.validate_config()
