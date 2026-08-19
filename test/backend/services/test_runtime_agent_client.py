"""Tests for the Northbound-to-Runtime HTTP client."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from apps.internal_agent_app import router as internal_agent_router
from consts.model import AgentRequest
from services import runtime_agent_client as runtime_agent_client_module
from services.runtime_agent_client import (
    RuntimeAgentClient,
    RuntimeServiceError,
    runtime_service_error_response,
)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


def _agent_request():
    return AgentRequest(query="hello", conversation_id=42, agent_id=7, history=[])


@pytest.mark.asyncio
async def test_run_agent_integrates_with_runtime_internal_asgi_route(mocker):
    runtime_app = FastAPI()
    runtime_app.include_router(internal_agent_router)

    async def runtime_stream():
        yield b'data: {"type":"text","content":"hello"}\n\n'
        yield b'data: {"type":"final_answer","content":"done"}\n\n'

    run_agent = mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        return_value=StreamingResponse(runtime_stream(), media_type="text/event-stream"),
    )
    runtime_client = RuntimeAgentClient("http://runtime.test")
    runtime_client._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app),
        base_url="http://runtime.test",
    )

    response = await runtime_client.run_agent(
        _agent_request(),
        user_id="user-1",
        tenant_id="tenant-1",
        request_id="req-integration",
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert b"final_answer" in body
    assert run_agent.await_args.kwargs["user_id"] == "user-1"
    assert run_agent.await_args.kwargs["tenant_id"] == "tenant-1"
    await runtime_client.close()


@pytest.mark.asyncio
async def test_run_agent_forwards_payload_request_id_and_stream_bytes():
    seen = []
    stream = ChunkStream([
        b'data: {"type":"text",',
        b'"content":"a"}\n\ndata: {"type":"final_answer","content":"b"}\n\n',
    ])

    async def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "conversation_id": "42"},
            stream=stream,
        )

    runtime_client = RuntimeAgentClient("http://runtime:5014/")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    response = await runtime_client.run_agent(
        agent_request=_agent_request(),
        user_id="user-1",
        tenant_id="tenant-1",
        request_id="req-1",
        runtime_scope_id="a2a:task-1",
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert b"".join(chunks) == b"".join(stream.chunks)
    assert stream.closed is True
    assert response.headers["conversation_id"] == "42"
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == "http://runtime:5014/internal/agent/run"
    assert request.headers["X-Request-Id"] == "req-1"
    assert "authorization" not in request.headers
    payload = json.loads(request.content)
    assert payload["agent_request"]["conversation_id"] == 42
    assert payload["user_id"] == "user-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["runtime_scope_id"] == "a2a:task-1"
    await runtime_client.close()


@pytest.mark.asyncio
async def test_run_agent_closes_upstream_when_downstream_stops_consuming():
    stream = ChunkStream([
        b'data: {"type":"text","content":"partial"}\n\n',
        b'data: {"type":"final_answer","content":"done"}\n\n',
    ])

    async def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await runtime_client.run_agent(_agent_request(), "user-1", "tenant-1", "req-disconnect")

    await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert stream.closed is True
    await runtime_client.close()


@pytest.mark.asyncio
async def test_run_agent_skips_empty_upstream_chunks():
    payload = b'data: {"type":"final_answer","content":"done"}\n\n'

    class EmptyChunkUpstream:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        def __init__(self):
            self.closed = False

        async def aiter_raw(self):
            yield b""
            yield payload

        async def aclose(self):
            self.closed = True

    upstream = EmptyChunkUpstream()
    managed_client = MagicMock(is_closed=False)
    managed_client.build_request.return_value = httpx.Request(
        "POST", "http://runtime:5014/internal/agent/run"
    )
    managed_client.send = AsyncMock(return_value=upstream)
    managed_client.aclose = AsyncMock()
    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = managed_client

    response = await runtime_client.run_agent(
        _agent_request(), "user-1", "tenant-1", "req-empty"
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [payload]
    assert upstream.closed is True
    await runtime_client.close()


@pytest.mark.asyncio
async def test_client_start_and_close_manage_reusable_client(mocker):
    managed_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    create_client = mocker.patch.object(
        runtime_agent_client_module,
        "create_httpx_client",
        return_value=managed_client,
    )
    runtime_client = RuntimeAgentClient("http://runtime:5014")

    await runtime_client.start()
    await runtime_client.start()

    assert runtime_client._client is managed_client
    create_client.assert_called_once_with(follow_redirects=False)
    await runtime_client.close()
    assert managed_client.is_closed is True
    await runtime_client.close()


@pytest.mark.asyncio
async def test_ensure_client_reuses_client_created_while_waiting_for_lock(mocker):
    managed_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200))
    )
    create_client = mocker.patch.object(runtime_agent_client_module, "create_httpx_client")
    runtime_client = RuntimeAgentClient("http://runtime:5014")

    await runtime_client._client_lock.acquire()
    ensure_task = asyncio.create_task(runtime_client._ensure_client())
    await asyncio.sleep(0)
    runtime_client._client = managed_client
    runtime_client._client_lock.release()

    assert await ensure_task is managed_client
    create_client.assert_not_called()
    await runtime_client.close()


@pytest.mark.asyncio
async def test_run_agent_emits_interruption_and_closes_upstream_on_read_failure():
    request = httpx.Request("POST", "http://runtime:5014/internal/agent/run")
    stream = ChunkStream(
        [b'data: {"type":"text","content":"partial"}\n\n'],
        error=httpx.ReadError("stream lost", request=request),
    )

    async def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    response = await runtime_client.run_agent(_agent_request(), "user-1", "tenant-1", "req-2")
    content = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")

    assert "partial" in content
    assert '"status": "run_interrupted"' in content
    assert stream.closed is True
    await runtime_client.close()


def test_runtime_service_error_response_preserves_body_and_content_type():
    response = runtime_service_error_response(
        RuntimeServiceError(409, b'{"code":"conflict"}', "application/problem+json; charset=utf-8")
    )

    assert response.status_code == 409
    assert response.body == b'{"code":"conflict"}'
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_status,expected_status,expected_body",
    [
        (403, 403, b'{"code":"forbidden"}'),
        (500, 502, b'{"message": "Runtime service returned an invalid response"}'),
    ],
)
async def test_run_agent_maps_upstream_errors(upstream_status, expected_status, expected_body):
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            upstream_status,
            content=b'{"code":"forbidden"}' if upstream_status == 403 else b"private failure",
            headers={"content-type": "application/problem+json"},
        )

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeServiceError) as exc_info:
        await runtime_client.run_agent(_agent_request(), "user-1", "tenant-1", "req-error")

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.content == expected_body
    assert calls == 1
    await runtime_client.close()


@pytest.mark.asyncio
async def test_run_agent_maps_connection_failure_to_503_without_retry():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("unavailable", request=request)

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeServiceError) as exc_info:
        await runtime_client.run_agent(_agent_request(), "user-1", "tenant-1", "req-down")

    assert exc_info.value.status_code == 503
    assert calls == 1
    await runtime_client.close()


@pytest.mark.asyncio
async def test_stop_agent_forwards_string_scope_and_maps_response():
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "success", "message": "stopped"})

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await runtime_client.stop_agent("a2a:task-1", "user-1", "req-stop")

    assert result["message"] == "stopped"
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {
        "conversation_id": "a2a:task-1",
        "user_id": "user-1",
    }
    assert seen[0].headers["X-Request-Id"] == "req-stop"
    await runtime_client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_status,expected_status,expected_body",
    [
        (422, 422, b'{"code":"invalid_scope"}'),
        (503, 502, b'{"message": "Runtime service returned an invalid response"}'),
    ],
)
async def test_stop_agent_maps_upstream_errors(upstream_status, expected_status, expected_body):
    async def handler(_request):
        return httpx.Response(
            upstream_status,
            content=b'{"code":"invalid_scope"}' if upstream_status == 422 else b"private failure",
            headers={"content-type": "application/problem+json"},
        )

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeServiceError) as exc_info:
        await runtime_client.stop_agent("a2a:task-1", "user-1", "req-stop-error")

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.content == expected_body
    await runtime_client.close()


@pytest.mark.asyncio
async def test_stop_agent_maps_connection_failure_to_503_without_retry():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("unavailable", request=request)

    runtime_client = RuntimeAgentClient("http://runtime:5014")
    runtime_client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeServiceError) as exc_info:
        await runtime_client.stop_agent(42, "user-1", "req-stop-down")

    assert exc_info.value.status_code == 503
    assert calls == 1
    await runtime_client.close()
