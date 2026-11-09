# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for northbound-to-runtime HTTP forwarding."""

import json

import httpx
import pytest

from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.services.agent import runtime_client as proxy


def test_dispatch_agent_evaluation_run_posts_internal_runtime_request(monkeypatch):
    captured = {}

    def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(202, json={"accepted": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    def create_client(**kwargs):
        client.headers.update(kwargs["headers"])
        return client

    monkeypatch.setattr(proxy.httpx, "Client", create_client)

    result = proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")

    assert result == {"accepted": True}
    request = captured["request"]
    assert str(request.url) == "http://runtime:5014/api/agent-evaluations/internal/run"
    assert request.headers["authorization"] == "Bearer jwt"
    assert json.loads(request.content) == {"agent_evaluation_id": 17}


def test_dispatch_agent_evaluation_run_maps_upstream_error(monkeypatch):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(409, content=b'{"detail":"already running"}')
        )
    )
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy.httpx, "Client", lambda **_: client)

    with pytest.raises(RuntimeUpstreamError) as exc_info:
        proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")

    assert exc_info.value.status_code == 409
    assert exc_info.value.content == b'{"detail":"already running"}'


class FailingSyncClient:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        raise self.error


def test_dispatch_agent_evaluation_run_maps_timeout(monkeypatch):
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy.httpx,
        "Client",
        lambda **_: FailingSyncClient(httpx.ReadTimeout("timed out")),
    )

    with pytest.raises(RuntimeServiceTimeoutError):
        proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")


def test_dispatch_agent_evaluation_run_maps_unavailable(monkeypatch):
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy.httpx,
        "Client",
        lambda **_: FailingSyncClient(httpx.ConnectError("down")),
    )

    with pytest.raises(RuntimeServiceUnavailableError, match="unavailable"):
        proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")


def test_dispatch_agent_evaluation_run_rejects_invalid_json(monkeypatch):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not json"))
    )
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy.httpx, "Client", lambda **_: client)

    with pytest.raises(RuntimeServiceUnavailableError, match="not valid JSON"):
        proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")


def test_dispatch_agent_evaluation_run_rejects_non_object_json(monkeypatch):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=["accepted"]))
    )
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy.httpx, "Client", lambda **_: client)

    with pytest.raises(RuntimeServiceUnavailableError, match="not a JSON object"):
        proxy.dispatch_agent_evaluation_run(17, "user-a", "tenant-a")


def test_authorization_headers_maps_missing_jwt_configuration(monkeypatch):
    monkeypatch.setattr(
        proxy,
        "generate_internal_runtime_jwt",
        lambda *_: (_ for _ in ()).throw(ValueError("missing secret")),
    )

    with pytest.raises(
        RuntimeServiceUnavailableError,
        match="Internal runtime authentication is not configured",
    ):
        proxy._authorization_headers("user-a", "tenant-a")


@pytest.mark.asyncio
async def test_forward_agent_evaluation_trial_run_posts_runtime_request(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(200, json={"answer": "ok", "scores": {"judge": 1.0}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")

    def create_client(**kwargs):
        client.headers.update(kwargs["headers"])
        return client

    monkeypatch.setattr(proxy, "create_httpx_client", create_client)

    result = await proxy.forward_agent_evaluation_trial_run(
        agent_id=7,
        agent_version_no=3,
        query="hello",
        judge_model_id=99,
        evaluator_ids=[5],
        language="zh",
        user_id="user-a",
        tenant_id="tenant-a",
    )

    assert result == {"answer": "ok", "scores": {"judge": 1.0}}
    request = captured["request"]
    assert str(request.url) == "http://runtime:5014/api/agent-evaluations/internal/trial-run"
    assert request.headers["authorization"] == "Bearer jwt"
    assert json.loads(request.content) == {
        "agent_id": 7,
        "agent_version_no": 3,
        "query": "hello",
        "judge_model_id": 99,
        "evaluator_ids": [5],
        "language": "zh",
    }
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_evaluation_trial_run_maps_upstream_error(monkeypatch):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(500, content=b'{"detail":"failed"}')
        )
    )
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    with pytest.raises(RuntimeUpstreamError) as exc_info:
        await proxy.forward_agent_evaluation_trial_run(
            agent_id=7,
            agent_version_no=3,
            query="hello",
            judge_model_id=99,
            evaluator_ids=None,
            language="zh",
            user_id="user-a",
            tenant_id="tenant-a",
        )

    assert exc_info.value.status_code == 500
    assert client.is_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "expected_error"),
    [
        (httpx.ReadTimeout("timed out"), RuntimeServiceTimeoutError),
        (httpx.ConnectError("connection failed"), RuntimeServiceUnavailableError),
    ],
)
async def test_forward_agent_evaluation_trial_run_maps_transport_errors(
    monkeypatch, transport_error, expected_error,
):
    async def handler(request: httpx.Request):
        transport_error.request = request
        raise transport_error

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    with pytest.raises(expected_error):
        await proxy.forward_agent_evaluation_trial_run(
            agent_id=7,
            agent_version_no=3,
            query="hello",
            judge_model_id=99,
            evaluator_ids=None,
            language="zh",
            user_id="user-a",
            tenant_id="tenant-a",
        )

    assert client.is_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not-json", b"[]"])
async def test_forward_agent_evaluation_trial_run_rejects_invalid_success_payload(monkeypatch, content):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    )
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    with pytest.raises(RuntimeServiceUnavailableError):
        await proxy.forward_agent_evaluation_trial_run(
            agent_id=7,
            agent_version_no=3,
            query="hello",
            judge_model_id=99,
            evaluator_ids=None,
            language="zh",
            user_id="user-a",
            tenant_id="tenant-a",
        )

    assert client.is_closed is True
