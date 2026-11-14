# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Provider paging, malformed catalog and error regression tests."""

from unittest.mock import AsyncMock

import httpx
import pytest
from management.services.model.providers import dashscope_provider, openai_provider


@pytest.fixture
def provider_http(monkeypatch):
    """Install an in-memory HTTP transport, keeping the real response parser."""
    client_class = httpx.AsyncClient

    def install(module, handler):
        requests = []

        def route(request):
            requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(route)
        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kwargs: client_class(transport=transport, **kwargs),
        )
        return requests

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": "invalid"},
        {"data": [None, "invalid", {}, {"id": " "}, {"id": " model "}]},
    ],
)
async def test_openai_filters_invalid_catalog_rows(provider_http, payload):
    requests = provider_http(
        openai_provider, lambda request: httpx.Response(200, json=payload)
    )
    result = await openai_provider.OpenAICompatibleProvider().get_models(
        {"base_url": "https://fixture.test/v1/models", "api_key": "fixture"}
    )
    assert result == (
        [{"id": "model", "model_tag": "chat"}]
        if isinstance(payload["data"], list)
        else []
    )
    assert requests[0].url.path == "/v1/models"
    assert requests[0].headers["Authorization"] == "Bearer fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error", [(401, "authentication_failed"), (403, "access_forbidden")]
)
async def test_openai_http_errors_are_catalog_errors(provider_http, status, error):
    provider_http(
        openai_provider,
        lambda request: httpx.Response(status, json={"error": "denied"}),
    )
    result = await openai_provider.OpenAICompatibleProvider().get_models(
        {"base_url": "https://fixture.test/v1", "api_key": "fixture"}
    )
    assert result[0]["_error"] == error
    assert result[0]["_http_code"] == status


@pytest.mark.asyncio
async def test_openai_connection_failure_is_classified(provider_http):
    def fail(request):
        raise httpx.ConnectError("unavailable", request=request)

    provider_http(openai_provider, fail)
    result = await openai_provider.OpenAICompatibleProvider().get_models(
        {"base_url": "https://fixture.test/v1", "api_key": "fixture"}
    )
    assert result[0]["_error"] == "connection_failed"


@pytest.mark.asyncio
async def test_dashscope_rate_limit_retries_same_page_and_advances(
    provider_http, monkeypatch
):
    calls = []
    models = [
        {
            "model": "qwen-turbo",
            "inference_metadata": {
                "request_modality": ["Text"],
                "response_modality": ["Text"],
            },
        }
        for _ in range(100)
    ]

    def handle(request):
        page = request.url.params["page_no"]
        calls.append(page)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200, json={"output": {"models": models if page == "1" else []}}
        )

    provider_http(dashscope_provider, handle)
    sleep = AsyncMock()
    monkeypatch.setattr(dashscope_provider.asyncio, "sleep", sleep)
    result = await dashscope_provider.DashScopeModelProvider().get_models(
        {"model_type": "llm", "api_key": "fixture"}
    )
    assert calls == ["1", "1", "2"]
    assert len(result) == 100
    assert all(row["model_type"] == "llm" for row in result)
    assert [call.args[0] for call in sleep.await_args_list] == [2, 0.5]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_type,model,expected_type",
    [
        ("embedding", "text-embedding-v2", "embedding"),
        ("rerank", "text-rerank-v2", "rerank"),
        ("unknown", "qwen-turbo", None),
    ],
)
async def test_dashscope_specialized_lists_keep_type(
    provider_http, model_type, model, expected_type
):
    provider_http(
        dashscope_provider,
        lambda request: httpx.Response(
            200, json={"output": {"models": [{"model": model}]}}
        ),
    )
    result = await dashscope_provider.DashScopeModelProvider().get_models(
        {"model_type": model_type, "api_key": "fixture"}
    )
    assert (
        result == []
        if expected_type is None
        else len(result) == 1 and result[0]["model_type"] == expected_type
    )


@pytest.mark.asyncio
async def test_dashscope_authentication_failure_is_classified(provider_http):
    provider_http(dashscope_provider, lambda request: httpx.Response(401))
    result = await dashscope_provider.DashScopeModelProvider().get_models(
        {"model_type": "llm", "api_key": "fixture"}
    )
    assert result[0]["_error"] == "authentication_failed"
    assert result[0]["_http_code"] == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("key,header", [("", None), ("  ", None), (" fixture ", "Bearer fixture")])
async def test_optional_key_model_discovery_does_not_send_empty_bearer(provider_http, key, header):
    """UI-AUTH-11: discovery uses the same optional API key convention."""
    requests = provider_http(openai_provider, lambda request: httpx.Response(200, json={"data": [{"id": "model"}]}))
    result = await openai_provider.OpenAICompatibleProvider().get_models(
        {"base_url": "https://fixture.test/v1", "api_key": key})
    assert result == [{"id": "model", "model_tag": "chat"}]
    assert requests[0].headers.get("Authorization") == header
