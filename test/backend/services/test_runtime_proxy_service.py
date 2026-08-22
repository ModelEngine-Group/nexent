"""Tests for northbound-to-runtime HTTP forwarding."""

import json

import httpx
import pytest

from consts.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from consts.model import AgentRequest
from services import runtime_proxy_service as proxy


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


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
async def test_forward_agent_run_streams_body_and_closes_resources(monkeypatch):
    stream = TrackingStream([b"data: one\n\n", b"data: two\n\n"])
    captured = {}

    async def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "cache-control": "no-cache",
                "connection": "keep-alive",
                "x-runtime": "yes",
            },
            stream=stream,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")

    def create_client(**kwargs):
        client.headers.update(kwargs["headers"])
        return client

    monkeypatch.setattr(proxy, "create_httpx_client", create_client)

    response = await proxy.forward_agent_run(
        AgentRequest(
            query="hello",
            conversation_id=123,
            agent_id=7,
            minio_files=[
                {
                    "object_name": "attachments/user-a/report.pdf",
                    "presigned_url": "http://minio/report.pdf",
                }
            ],
        ),
        user_id="user-a",
        tenant_id="tenant-a",
    )
    chunks = [chunk async for chunk in response.body_iterator]

    request = captured["request"]
    assert str(request.url) == (
        "http://runtime:5014/api/agent/internal/northbound/run"
    )
    assert request.headers["authorization"] == "Bearer jwt"
    request_payload = json.loads(request.content)
    assert request_payload["agent_id"] == 7
    assert request_payload["minio_files"] == [
        {
            "object_name": "attachments/user-a/report.pdf",
            "presigned_url": "http://minio/report.pdf",
        }
    ]
    assert chunks == [b"data: one\n\n", b"data: two\n\n"]
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-runtime"] == "yes"
    assert "connection" not in response.headers
    assert stream.closed is True
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_run_maps_timeout(monkeypatch):
    async def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    with pytest.raises(RuntimeServiceTimeoutError):
        await proxy.forward_agent_run(
            AgentRequest(query="hello"),
            user_id="user-a",
            tenant_id="tenant-a",
        )
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_run_maps_request_error(monkeypatch):
    async def handler(request: httpx.Request):
        raise httpx.ConnectError("connection failed", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    with pytest.raises(RuntimeServiceUnavailableError, match="unavailable"):
        await proxy.forward_agent_run(
            AgentRequest(query="hello"),
            user_id="user-a",
            tenant_id="tenant-a",
        )
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_run_closes_client_on_unexpected_error(monkeypatch):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    async def raise_unexpected(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(client, "send", raise_unexpected)

    with pytest.raises(RuntimeError, match="unexpected"):
        await proxy.forward_agent_run(
            AgentRequest(query="hello"),
            user_id="user-a",
            tenant_id="tenant-a",
        )
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_run_preserves_upstream_error(monkeypatch):
    async def handler(request: httpx.Request):
        return httpx.Response(
            422,
            headers={"content-type": "application/json"},
            stream=TrackingStream([b'{"message":"invalid"}']),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    response = await proxy.forward_agent_run(
        AgentRequest(query="hello"),
        user_id="user-a",
        tenant_id="tenant-a",
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert b"".join(chunks) == b'{"message":"invalid"}'
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_run_closes_upstream_when_consumer_stops(monkeypatch):
    stream = TrackingStream([b"data: one\n\n", b"data: two\n\n"])

    async def handler(request: httpx.Request):
        return httpx.Response(200, stream=stream)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)

    response = await proxy.forward_agent_run(
        AgentRequest(query="hello"),
        user_id="user-a",
        tenant_id="tenant-a",
    )
    iterator = response.body_iterator
    assert await anext(iterator) == b"data: one\n\n"
    await iterator.aclose()

    assert stream.closed is True
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_forward_agent_stop_returns_json(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(200, json={"message": "stopped"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy,
        "create_httpx_client",
        lambda **_: httpx.AsyncClient(transport=transport),
    )

    result = await proxy.forward_agent_stop(123, "user-a", "tenant-a")

    assert result == {"message": "stopped"}
    assert str(captured["request"].url) == (
        "http://runtime:5014/api/agent/internal/northbound/stop/123"
    )
    assert captured["request"].method == "POST"


@pytest.mark.asyncio
async def test_forward_agent_stop_preserves_upstream_error(monkeypatch):
    async def handler(request: httpx.Request):
        return httpx.Response(
            403,
            headers={"content-type": "application/json", "connection": "close"},
            content=b'{"message":"forbidden"}',
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy,
        "create_httpx_client",
        lambda **_: httpx.AsyncClient(transport=transport),
    )

    with pytest.raises(RuntimeUpstreamError) as exc_info:
        await proxy.forward_agent_stop(123, "user-a", "tenant-a")

    assert exc_info.value.status_code == 403
    assert exc_info.value.content == b'{"message":"forbidden"}'
    assert exc_info.value.headers["content-type"] == "application/json"
    assert "connection" not in exc_info.value.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "expected_error"),
    [
        (httpx.ReadTimeout("timed out"), RuntimeServiceTimeoutError),
        (httpx.ConnectError("connection failed"), RuntimeServiceUnavailableError),
    ],
)
async def test_forward_agent_stop_maps_transport_errors(
    monkeypatch,
    transport_error,
    expected_error,
):
    async def handler(request: httpx.Request):
        transport_error.request = request
        raise transport_error

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy,
        "create_httpx_client",
        lambda **_: httpx.AsyncClient(transport=transport),
    )

    with pytest.raises(expected_error):
        await proxy.forward_agent_stop(123, "user-a", "tenant-a")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_kwargs", "expected_message"),
    [
        ({"content": b"not-json"}, "not valid JSON"),
        ({"json": ["not", "an", "object"]}, "not a JSON object"),
    ],
)
async def test_forward_agent_stop_rejects_invalid_success_payload(
    monkeypatch,
    response_kwargs,
    expected_message,
):
    async def handler(request: httpx.Request):
        return httpx.Response(200, **response_kwargs)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(
        proxy,
        "create_httpx_client",
        lambda **_: httpx.AsyncClient(transport=transport),
    )

    with pytest.raises(RuntimeServiceUnavailableError, match=expected_message):
        await proxy.forward_agent_stop(123, "user-a", "tenant-a")
