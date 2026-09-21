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


@pytest.mark.asyncio
@pytest.mark.parametrize("path,result", [("capabilities", {"enabled": True}), ("conversation/7", None)])
async def test_human_interaction_forwards_internal_identity_and_nullable_snapshot(monkeypatch, path, result):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, content=json.dumps(result), headers={"content-type": "application/json"})

    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda user, tenant: f"{user}:{tenant}")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=kwargs["headers"],
    ))
    assert await proxy.forward_human_interaction("GET", path, "owner", "tenant-a") == result
    assert captured[0].url.path == f"/api/agent/internal/northbound/human-interactions/{path}"
    assert captured[0].headers["authorization"] == "Bearer owner:tenant-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 409, 410, 422, 503])
async def test_human_interaction_preserves_decision_errors(monkeypatch, status):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(status, content=b'{"message":"rejected"}', headers={"connection": "close"})

    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeUpstreamError) as error:
        await proxy.forward_human_interaction(
            "POST", "run/requests/card/decisions", "owner", "tenant", payload={"decision": "answer"},
        )
    assert json.loads(captured[0].content) == {"decision": "answer"}
    assert error.value.status_code == status
    assert error.value.content == b'{"message":"rejected"}'
    assert "connection" not in error.value.headers


@pytest.mark.asyncio
async def test_human_events_streams_without_buffering_and_closes_on_disconnect(monkeypatch):
    stream = TrackingStream([b'id: 1\ndata: {"type":"human_interaction"}\n\n', b"id: 2\ndata: {}\n\n"])
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream", "run_id": "run"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: client)
    response = await proxy.forward_human_interaction_events("run", "owner", "tenant", after_event=7)
    first = await anext(response.body_iterator)
    assert first.startswith(b"id: 1\n")
    assert not stream.closed
    await response.body_iterator.aclose()
    assert stream.closed and client.is_closed
    assert captured[0].method == "GET"
    assert captured[0].url.params["after_event"] == "7"
    assert response.headers["run_id"] == "run"


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [
    (httpx.ReadTimeout("timeout"), RuntimeServiceTimeoutError),
    (httpx.ConnectError("unreachable"), RuntimeServiceUnavailableError),
])
async def test_human_interaction_maps_transport_errors(monkeypatch, error, expected):
    def handler(request):
        error.request = request
        raise error

    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(expected):
        await proxy.forward_human_interaction("GET", "capabilities", "owner", "tenant")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not-json", b"[]", b"null"])
async def test_human_interaction_rejects_invalid_runtime_payload(monkeypatch, content):
    monkeypatch.setattr(proxy, "generate_internal_runtime_jwt", lambda *_: "jwt")
    monkeypatch.setattr(proxy, "create_httpx_client", lambda **_: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content)),
    ))
    with pytest.raises(RuntimeServiceUnavailableError):
        await proxy.forward_human_interaction("GET", "capabilities", "owner", "tenant")
