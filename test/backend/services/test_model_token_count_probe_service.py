from datetime import datetime, timedelta, timezone

import pytest

from backend.services.model_token_count_probe_service import (
    PROBE_ADAPTER_VERSION,
    ProbeHTTPResponse,
    classify_probe_response,
    endpoint_fingerprint,
    run_token_count_probe,
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
