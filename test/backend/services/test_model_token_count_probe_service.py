from datetime import datetime, timedelta, timezone
import socket

import httpx
import pytest

from backend.services import model_token_count_probe_service as probe_service
from backend.services.model_token_count_probe_service import (
    PROBE_ADAPTER_VERSION,
    ProbeHTTPRequest,
    ProbeHTTPResponse,
    build_probe_request,
    classify_probe_response,
    endpoint_fingerprint,
    run_token_count_probe,
    should_reuse_probe,
    validate_probe_url,
)


NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)
PUBLIC = lambda _host: ("8.8.8.8",)


@pytest.mark.parametrize(
    ("response", "state", "reason"),
    [
        (ProbeHTTPResponse(200, {"input_tokens": 7}), "supported", "supported"),
        (ProbeHTTPResponse(404), "unsupported", "unsupported_endpoint"),
        (ProbeHTTPResponse(405), "unsupported", "unsupported_endpoint"),
        (ProbeHTTPResponse(401), "authorization_error", "authorization_failed"),
        (ProbeHTTPResponse(403), "authorization_error", "authorization_failed"),
        (ProbeHTTPResponse(429), "temporarily_unavailable", "rate_limited"),
        (ProbeHTTPResponse(503), "temporarily_unavailable", "provider_5xx"),
        (ProbeHTTPResponse(302, redirect_location="https://evil.test"), "temporarily_unavailable", "redirect_rejected"),
        (ProbeHTTPResponse(200, {}), "invalid_response", "invalid_schema"),
        (ProbeHTTPResponse(200, {"input_tokens": 0}), "invalid_response", "invalid_count"),
        (ProbeHTTPResponse(200, {"input_tokens": 100_000_001}), "invalid_response", "invalid_count"),
    ],
)
def test_probe_status_classification(response, state, reason):
    actual_state, actual_reason, _ = classify_probe_response("openai_responses", response)
    assert (actual_state, actual_reason) == (state, reason)


@pytest.mark.asyncio
async def test_known_protocol_probes_only_directed_dialect():
    calls = []

    async def transport(request):
        calls.append(request)
        return ProbeHTTPResponse(200, {"input_tokens": 9})

    result = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="qwen3.7-plus",
        canonical_model_id="dashscope/qwen3.7-plus",
        api_key="secret-marker",
        credential_scope="tenant:model:1",
        fingerprint_salt="test-salt",
        resolver=PUBLIC,
        transport=transport,
        now=NOW,
    )
    assert [item.protocol for item in calls] == ["openai_responses"]
    assert result["status"] == "supported"
    assert result["selected_protocol"] == "openai_responses"
    assert result["capabilities"] == {
        "text": "supported", "tools": "unknown", "media": "unknown"
    }
    assert "secret-marker" not in repr(result)


@pytest.mark.asyncio
async def test_probe_logs_never_contain_credentials_or_raw_payload(caplog):
    async def transport(_request):
        return ProbeHTTPResponse(401, {"error": "secret-marker-response"})

    with caplog.at_level("INFO"):
        result = await run_token_count_probe(
            inference_protocol="openai",
            base_url="https://api.example.test/v1",
            model_name="model",
            canonical_model_id="openai/model",
            api_key="secret-marker-key",
            credential_scope="scope",
            fingerprint_salt="salt",
            resolver=PUBLIC,
            transport=transport,
            now=NOW,
        )
    assert result["reason"] == "authorization_failed"
    assert "secret-marker" not in caplog.text


@pytest.mark.asyncio
async def test_unknown_protocol_tries_dialects_in_order_and_retains_outcomes():
    calls = []

    async def transport(request):
        calls.append(request.protocol)
        if request.protocol == "openai_responses":
            return ProbeHTTPResponse(404)
        if request.protocol == "anthropic_messages":
            return ProbeHTTPResponse(200, {"input_tokens": 11})
        raise AssertionError("must stop after the first supported dialect")

    result = await run_token_count_probe(
        inference_protocol="unknown",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="unknown/model",
        api_key="secret-marker",
        credential_scope="tenant:model:2",
        fingerprint_salt="test-salt",
        resolver=PUBLIC,
        transport=transport,
        now=NOW,
    )
    assert calls == ["openai_responses", "anthropic_messages"]
    assert [item["state"] for item in result["outcomes"]] == ["unsupported", "supported"]


@pytest.mark.asyncio
async def test_all_unknown_dialects_unsupported_gets_negative_ttl():
    async def transport(_request):
        return ProbeHTTPResponse(405)

    result = await run_token_count_probe(
        inference_protocol="unknown",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="unknown/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        transport=transport,
        now=NOW,
    )
    assert len(result["outcomes"]) == 3
    assert result["status"] == "unsupported"
    assert result["stale_at"] == "2026-08-25T00:00:00Z"


@pytest.mark.asyncio
async def test_timeout_is_temporary_and_not_negative_capability():
    async def transport(_request):
        raise TimeoutError

    result = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        transport=transport,
        now=NOW,
    )
    assert result["status"] == "temporarily_unavailable"
    assert result["reason"] == "timeout"
    assert result["retry_at"] == "2026-08-24T00:15:00Z"


@pytest.mark.asyncio
async def test_valid_cached_evidence_is_reused_without_transport_call():
    calls = 0

    async def transport(_request):
        nonlocal calls
        calls += 1
        return ProbeHTTPResponse(500)

    initial = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        transport=lambda request: _supported(request),
        now=NOW,
    )
    reused = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="changed-secret-does-not-enter-fingerprint",
        credential_scope="scope",
        fingerprint_salt="salt",
        existing=initial,
        resolver=PUBLIC,
        transport=transport,
        now=NOW + timedelta(hours=1),
    )
    assert reused == initial
    assert calls == 0


async def _supported(_request):
    return ProbeHTTPResponse(200, {"input_tokens": 5})


@pytest.mark.asyncio
async def test_model_or_endpoint_fingerprint_change_invalidates_cache():
    calls = 0

    async def transport(_request):
        nonlocal calls
        calls += 1
        return ProbeHTTPResponse(200, {"input_tokens": 5})

    existing = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        transport=transport,
        now=NOW,
    )
    calls = 0
    changed = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v2",
        model_name="model2",
        canonical_model_id="openai/model2",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        existing=existing,
        resolver=PUBLIC,
        transport=transport,
        now=NOW + timedelta(hours=1),
    )
    assert calls == 1
    assert changed["fingerprint"] != existing["fingerprint"]


def test_ssrf_and_credential_bearing_urls_are_rejected():
    with pytest.raises(ValueError, match="ssrf_rejected"):
        validate_probe_url("http://127.0.0.1/v1", resolver=lambda _host: ("127.0.0.1",))
    with pytest.raises(ValueError, match="ssrf_rejected"):
        validate_probe_url("https://user:pass@example.test/v1", resolver=PUBLIC)
    with pytest.raises(ValueError, match="ssrf_rejected"):
        validate_probe_url("https://example.test/v1?api_key=secret", resolver=PUBLIC)


def test_endpoint_fingerprint_omits_userinfo_query_and_fragment():
    fingerprint = endpoint_fingerprint("https://user:secret@example.test/v1?q=secret#fragment")
    assert len(fingerprint) == 24
    assert "secret" not in fingerprint
    assert PROBE_ADAPTER_VERSION == "1.0.0"


def test_time_parsing_and_cache_reuse_reject_invalid_evidence():
    assert probe_service._parse_time(None) is None
    assert probe_service._parse_time("not-a-time") is None
    assert not should_reuse_probe(
        {"fingerprint": "current", "status": "temporarily_unavailable"},
        current_fingerprint="current",
        now=NOW,
        force=False,
    )


def test_default_resolver_collects_unique_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        ],
    )
    assert probe_service._default_resolver("example.test") == {"8.8.8.8"}


@pytest.mark.parametrize("url", ["ftp://example.test/v1", "https:///missing-host"])
def test_probe_url_rejects_unsupported_or_missing_origin(url):
    with pytest.raises(ValueError, match="ssrf_rejected"):
        validate_probe_url(url, resolver=PUBLIC)


def test_probe_url_reports_dns_failure_and_empty_dns_result():
    def failed_resolver(_host):
        raise socket.gaierror("dns unavailable")

    with pytest.raises(ValueError, match="connection_failed"):
        validate_probe_url("https://example.test/v1", resolver=failed_resolver)
    with pytest.raises(ValueError, match="connection_failed"):
        validate_probe_url("https://example.test/v1", resolver=lambda _host: ())


def test_probe_url_normalizes_ipv6_and_explicit_port():
    result = validate_probe_url(
        "HTTPS://[2001:4860:4860::8888]:8443/v1/",
        allow_private=True,
        resolver=lambda _host: ("2001:4860:4860::8888",),
    )
    assert result == "https://[2001:4860:4860::8888]:8443/v1"


def test_gemini_request_and_response_schema():
    request = build_probe_request(
        "gemini",
        base_url="https://api.example.test/v1",
        model_name="gemini-test",
        api_key="secret",
    )
    assert request.url.endswith("/models/gemini-test:countTokens")
    assert classify_probe_response(
        "gemini", ProbeHTTPResponse(200, {"totalTokens": 12})
    ) == ("supported", "supported", 12)
    assert classify_probe_response("gemini", ProbeHTTPResponse(200, None)) == (
        "invalid_response",
        "invalid_schema",
        None,
    )
    assert classify_probe_response("gemini", ProbeHTTPResponse(418)) == (
        "temporarily_unavailable",
        "connection_failed",
        None,
    )
    with pytest.raises(ValueError, match="unsupported_protocol"):
        build_probe_request(
            "unknown",
            base_url="https://api.example.test/v1",
            model_name="model",
            api_key="secret",
        )


class _FakeAsyncClient:
    response = None
    error = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def _request():
    return ProbeHTTPRequest("openai_responses", "https://api.example.test", {}, {})


@pytest.mark.asyncio
async def test_http_transport_handles_redirect_oversize_and_invalid_json(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    redirect = httpx.Response(302, headers={"location": "https://other.test"})
    _FakeAsyncClient.response = redirect
    result = await probe_service._httpx_transport(_request())
    assert result.redirect_location == "https://other.test"

    oversized = httpx.Response(200, content=b"x" * (probe_service.MAX_RESPONSE_BYTES + 1))
    _FakeAsyncClient.response = oversized
    result = await probe_service._httpx_transport(_request())
    assert result.payload is None

    invalid_json = httpx.Response(200, content=b"not-json")
    _FakeAsyncClient.response = invalid_json
    result = await probe_service._httpx_transport(_request())
    assert result.payload is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("slow"), TimeoutError),
        (httpx.ConnectError("offline"), ConnectionError),
    ],
)
async def test_http_transport_maps_httpx_errors(monkeypatch, error, expected):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.error = error
    try:
        with pytest.raises(expected):
            await probe_service._httpx_transport(_request())
    finally:
        _FakeAsyncClient.error = None


@pytest.mark.asyncio
async def test_probe_rejects_cross_origin_target_and_maps_connection_error(monkeypatch):
    original_builder = probe_service.build_probe_request

    def cross_origin(*_args, **_kwargs):
        return ProbeHTTPRequest(
            "openai_responses", "https://other.example.test/input_tokens", {}, {}
        )

    monkeypatch.setattr(probe_service, "build_probe_request", cross_origin)
    rejected = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        now=NOW,
    )
    assert rejected["reason"] == "redirect_rejected"

    monkeypatch.setattr(probe_service, "build_probe_request", original_builder)

    async def disconnected(_request):
        raise ConnectionError

    failed = await run_token_count_probe(
        inference_protocol="openai",
        base_url="https://api.example.test/v1",
        model_name="model",
        canonical_model_id="openai/model",
        api_key="key",
        credential_scope="scope",
        fingerprint_salt="salt",
        resolver=PUBLIC,
        transport=disconnected,
        now=NOW,
    )
    assert failed["reason"] == "connection_failed"
