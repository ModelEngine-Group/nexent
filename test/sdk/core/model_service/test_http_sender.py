# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated transport branches; actual network collaboration is a formal D3."""

import asyncio
import json
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    PreparedHttpRequest,
)
from nexent.core.model_service.http_sender import HttpRequestSender
from nexent.core.model_service.profiles.resolved_profile import CredentialReference
from nexent.core.model_service.sse import SSEEvent


def request(**changes):
    values = {
        "request_id": "r1",
        "method": "POST",
        "base_url": "https://example.test/v1?api-version=1",
        "relative_path": "chat/completions",
        "headers": {},
        "json_body": {"model": "exact", "temperature": 0},
        "timeout_seconds": 10,
        "ssl_verify": False,
        "credential_ref": CredentialReference(kind="model_record", model_id=3),
    }
    return PreparedHttpRequest(**(values | changes))


def test_frozen_credentials_resolve_once_and_keep_detached_headers():
    headers = {"Authorization": "Bearer dummy-original"}
    calls = []

    def credentials(reference):
        calls.append(reference)
        return headers

    wire = request()
    frozen = HttpRequestSender(credentials).freeze_credentials(wire)
    headers["Authorization"] = "Bearer dummy-changed"
    assert frozen._headers(wire)["authorization"] == "Bearer dummy-original"
    assert frozen._headers(wire)["authorization"] == "Bearer dummy-original"
    assert len(calls) == 1


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize(
    "event", ["connection.connect_tcp.complete", "connection.start_tls.complete"]
)
def test_sync_cancel_shuts_down_owned_or_late_network_socket(clients, late, event):
    scope = RunCancellationScope()
    connection = Mock(spec=socket.socket)
    stream = SimpleNamespace(get_extra_info=lambda _: connection, close=Mock())

    def handler(wire):
        if late:
            scope.cancel()
        wire.extensions["trace"](event, {"return_value": stream})
        scope.cancel()
        return httpx.Response(200, json={"unused": True})

    owned = clients(handler)
    with pytest.raises(RunTerminated):
        HttpRequestSender(lambda _: {}).invoke(request(), scope=scope)
    connection.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    assert stream.close.call_count == int(late)
    assert len(owned) == 1 and owned[0].is_closed


@pytest.fixture
def clients(monkeypatch):
    original_sync, original_async = httpx.Client, httpx.AsyncClient
    captured = []

    def install(handler):
        transport = httpx.MockTransport(handler)

        def sync(**kwargs):
            assert kwargs == {"verify": False, "timeout": 10, "trust_env": False}
            client = original_sync(transport=transport, **kwargs)
            captured.append(client)
            return client

        def asynchronous(**kwargs):
            assert kwargs == {"verify": False, "timeout": 10, "trust_env": False}
            client = original_async(transport=transport, **kwargs)
            captured.append(client)
            return client

        monkeypatch.setattr(httpx, "Client", sync)
        monkeypatch.setattr(httpx, "AsyncClient", asynchronous)
        return captured

    return install


@pytest.mark.asyncio
async def test_sync_async_exact_request_auth_and_owned_close(clients):
    seen = []

    def handler(req):
        seen.append(req)
        assert str(req.url) == "https://example.test/v1/chat/completions?api-version=1"
        assert req.headers["authorization"] == "Bearer dummy-private"
        assert req.headers["content-type"] == "application/json"
        assert json.loads(req.content) == {"model": "exact", "temperature": 0}
        return httpx.Response(200, json={"choices": []})

    owned = clients(handler)
    sender = HttpRequestSender(
        lambda ref: (
            {"Authorization": "Bearer dummy-private"} if ref.model_id == 3 else {}
        )
    )
    assert sender.invoke(request()).body == b'{"choices":[]}'
    assert (await sender.ainvoke(request())).status_code == 200
    assert len(seen) == 2
    assert all(client.is_closed for client in owned)


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500])
@pytest.mark.asyncio
async def test_http_status_exposes_body_only_to_adapter_and_never_retries(
    clients, status
):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(
            status, text="dummy-private", headers={"Location": "https://other.test"}
        )

    owned = clients(handler)
    sender = HttpRequestSender(lambda ref: {})
    for asynchronous in [False, True]:
        with pytest.raises(ModelTransportError, match="^HTTP_STATUS_ERROR$") as caught:
            if asynchronous:
                await sender.ainvoke(request())
            else:
                sender.invoke(request())
        assert caught.value.response.status_code == status
        assert caught.value.response.body == b"dummy-private"
        assert "dummy-private" not in repr(caught.value.response)
        assert "dummy-private" not in repr(caught.value)
    assert len(seen) == 2
    assert all(client.is_closed for client in owned)


@pytest.mark.parametrize(
    "error,category",
    [(httpx.ReadTimeout, "HTTP_TIMEOUT"), (httpx.ConnectError, "HTTP_NETWORK_ERROR")],
)
@pytest.mark.asyncio
async def test_transport_errors_are_safe_and_close_owned_clients(
    clients, error, category
):
    def handler(req):
        raise error("dummy-private", request=req)

    owned = clients(handler)
    sender = HttpRequestSender(lambda ref: {})
    for asynchronous in [False, True]:
        with pytest.raises(ModelTransportError, match=f"^{category}$") as caught:
            if asynchronous:
                await sender.ainvoke(request())
            else:
                sender.invoke(request())
        assert caught.value.__suppress_context__
    assert all(client.is_closed for client in owned)


@pytest.mark.asyncio
async def test_sync_async_stream_frames_and_early_close(clients):
    owned = clients(
        lambda req: httpx.Response(
            200,
            text="data: first\n\ndata: second\n\n",
            headers={"Content-Type": "text/event-stream; charset=utf-8"},
        )
    )
    sender = HttpRequestSender(lambda ref: {})
    with sender.stream(request(stream_protocol="sse")) as events:
        assert next(events) == SSEEvent("first")
    async with sender.astream(request(stream_protocol="sse")) as events:
        assert [event async for event in events] == [
            SSEEvent("first"),
            SSEEvent("second"),
        ]
    assert all(client.is_closed for client in owned)


@pytest.mark.parametrize(
    "body,content_type,category",
    [
        ("data: truncated", "text/event-stream", "SSE_INCOMPLETE_EVENT"),
        ("data: " + "x" * 30, "text/event-stream", "SSE_EVENT_TOO_LARGE"),
        ("data: wrong\n\n", "application/json", "HTTP_STREAM_FORMAT_INVALID"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_streams_fail_explicitly_and_close(
    clients, body, content_type, category
):
    owned = clients(
        lambda req: httpx.Response(
            200, text=body, headers={"content-type": content_type}
        )
    )
    sender = HttpRequestSender(lambda ref: {}, max_event_bytes=20)
    with (
        pytest.raises(ModelTransportError, match=f"^{category}$"),
        sender.stream(request(stream_protocol="sse")) as events,
    ):
        list(events)
    with pytest.raises(ModelTransportError, match=f"^{category}$"):
        async with sender.astream(request(stream_protocol="sse")) as events:
            [event async for event in events]
    assert all(client.is_closed for client in owned)


@pytest.mark.asyncio
async def test_whole_response_limits_are_not_silent_truncation(clients):
    owned = clients(lambda req: httpx.Response(200, content=b"12345"))
    sender = HttpRequestSender(lambda ref: {}, max_response_bytes=4)
    with pytest.raises(ModelTransportError, match="^HTTP_RESPONSE_TOO_LARGE$"):
        sender.invoke(request())
    with pytest.raises(ModelTransportError, match="^HTTP_RESPONSE_TOO_LARGE$"):
        await sender.ainvoke(request())
    assert all(client.is_closed for client in owned)


def test_pre_cancelled_scope_does_not_resolve_credentials_or_send():
    scope = RunCancellationScope()
    scope.cancel()
    sender = HttpRequestSender(
        lambda ref: pytest.fail("Credential resolution should not occur")
    )
    with pytest.raises(RunTerminated):
        sender.invoke(request(), scope=scope)


def test_bad_credential_callback_is_sanitized_before_creating_client():
    def resolver(ref):
        raise ValueError("dummy-private")

    with pytest.raises(ModelTransportError, match="^CREDENTIAL_RESOLUTION_FAILED$"):
        HttpRequestSender(resolver).invoke(request())
    with pytest.raises(ModelTransportError, match="^CREDENTIAL_HEADER_CONFLICT$"):
        HttpRequestSender(lambda ref: {"Accept": "private"}).invoke(
            request(headers={"Accept": "application/json"})
        )


@pytest.mark.asyncio
async def test_scope_cancellation_interrupts_blocked_async_stream_and_closes(clients):
    entered = asyncio.Event()

    class Blocked(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            self.closed = True

    stream = Blocked()
    owned = clients(
        lambda req: httpx.Response(
            200, stream=stream, headers={"content-type": "text/event-stream"}
        )
    )
    scope = RunCancellationScope()
    sender = HttpRequestSender(lambda ref: {})

    async def run():
        async with sender.astream(
            request(stream_protocol="sse"), scope=scope
        ) as events:
            return [event async for event in events]

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 2)
    scope.cancel()
    with pytest.raises(RunTerminated):
        await asyncio.wait_for(task, 2)
    assert stream.closed
    assert all(client.is_closed for client in owned)
    assert scope._closers == {}


@pytest.mark.parametrize(
    "changes",
    [{"max_response_bytes": 0}, {"max_error_bytes": True}, {"max_event_bytes": -1}],
)
def test_sender_limits_require_positive_integers(changes):
    with pytest.raises(ValueError, match="positive integers"):
        HttpRequestSender(lambda ref: {}, **changes)


@pytest.mark.asyncio
async def test_closed_stream_iterators_cannot_emit_buffered_events(clients):
    owned = clients(
        lambda req: httpx.Response(
            200,
            content=b"data: one\n\ndata: two\n\n",
            headers={"content-type": "text/event-stream"},
        )
    )
    sender = HttpRequestSender(lambda ref: {})
    with sender.stream(request(stream_protocol="sse")) as sync_events:
        assert next(sync_events) == SSEEvent("one")
    assert list(sync_events) == []
    async with sender.astream(request(stream_protocol="sse")) as async_events:
        assert await anext(async_events) == SSEEvent("one")
    assert [event async for event in async_events] == []
    assert all(client.is_closed for client in owned)


def test_scope_cancel_stops_even_already_buffered_sync_events(clients):
    owned = clients(
        lambda req: httpx.Response(
            200,
            content=b"data: one\n\ndata: two\n\n",
            headers={"content-type": "text/event-stream"},
        )
    )
    sender = HttpRequestSender(lambda ref: {})
    scope = RunCancellationScope()
    with (
        pytest.raises(RunTerminated),
        sender.stream(request(stream_protocol="sse"), scope=scope) as events,
    ):
        assert next(events) == SSEEvent("one")
        scope.cancel()
        next(events)
    assert all(client.is_closed for client in owned)
    assert scope._closers == {}


@pytest.mark.asyncio
async def test_error_streams_preserve_status_and_private_body_without_replay(clients):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429, text="dummy-private")

    owned = clients(handler)
    sender = HttpRequestSender(lambda ref: {})
    with (
        pytest.raises(ModelTransportError, match="^HTTP_STATUS_ERROR$") as sync_error,
        sender.stream(request(stream_protocol="sse")),
    ):
        pytest.fail("Status error must precede iteration")
    with pytest.raises(ModelTransportError, match="^HTTP_STATUS_ERROR$") as async_error:
        async with sender.astream(request(stream_protocol="sse")):
            pytest.fail("Status error must precede iteration")
    assert (
        sync_error.value.response.body
        == async_error.value.response.body
        == b"dummy-private"
    )
    assert len(calls) == 2
    assert all(client.is_closed for client in owned)


@pytest.mark.asyncio
async def test_tls_cause_is_classified_without_message_matching_or_reducing_verification(
    clients,
):
    import ssl

    def handler(req):
        try:
            raise ssl.SSLCertVerificationError("dummy-private")
        except ssl.SSLError as cause:
            raise httpx.ConnectError("dummy-private", request=req) from cause

    owned = clients(handler)
    sender = HttpRequestSender(lambda ref: {})
    with pytest.raises(ModelTransportError, match="^HTTP_TLS_ERROR$"):
        sender.invoke(request())
    with pytest.raises(ModelTransportError, match="^HTTP_TLS_ERROR$"):
        await sender.ainvoke(request())
    assert all(client.is_closed for client in owned)


def test_sync_cancel_wakes_reader_but_owner_thread_closes_client(clients):
    """Keep the socket descriptor valid until its blocking reader has unwound."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    ready, release, shutdown = Event(), Event(), Event()
    scope = RunCancellationScope()
    connection = Mock(spec=socket.socket)
    connection.shutdown.side_effect = lambda _: shutdown.set()
    stream = SimpleNamespace(get_extra_info=lambda _: connection, close=Mock())

    class BlockingBody(httpx.SyncByteStream):
        def __iter__(self):
            ready.set()
            assert release.wait(3)
            yield b'{}'

    def handler(wire):
        wire.extensions['trace']('connection.connect_tcp.complete', {'return_value': stream})
        return httpx.Response(200, stream=BlockingBody())

    owned = clients(handler)

    def invoke():
        try:
            HttpRequestSender(lambda _: {}).invoke(request(), scope=scope)
        except RunTerminated:
            return 'cancelled'

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke)
        assert ready.wait(3)
        try:
            scope.cancel()
            assert shutdown.is_set()
            assert not owned[0].is_closed
        finally:
            release.set()
            assert future.result(timeout=3) == 'cancelled'
    assert owned[0].is_closed
    connection.shutdown.assert_called_once_with(socket.SHUT_RDWR)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.asyncio
async def test_http_error_details_are_shared_and_redact_request_credentials(clients, asynchronous, streaming, structured):
    from nexent.core.model_service.errors import normalize_model_error

    reason = "invalid top_p 1; expected 0.95; secret-key; header-secret"
    def handler(wire):
        if structured:
            return httpx.Response(400, json={"error": {"message": reason, "param": "top_p"}})
        return httpx.Response(400, text=reason)

    clients(handler)
    sender = HttpRequestSender(lambda _: {"authorization": "Bearer secret-key"})
    wire = request(headers={"x-private": "header-secret"}, stream_protocol="sse" if streaming else None)
    with pytest.raises(ModelTransportError) as caught:
        if asynchronous:
            if streaming:
                async with sender.astream(wire):
                    pytest.fail("HTTP failure must raise before yielding")
            else:
                await sender.ainvoke(wire)
        elif streaming:
            with sender.stream(wire):
                pytest.fail("HTTP failure must raise before yielding")
        else:
            sender.invoke(wire)
    error = normalize_model_error(caught.value, request_id="r1")
    assert error.safe_message.startswith("(400) invalid top_p 1; expected 0.95;")
    assert "secret-key" not in error.safe_message and "header-secret" not in error.safe_message
    assert error.category == "MODEL_REQUEST_INVALID" and not error.retryable


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_stream_error_frame_retains_credential_redaction_context(clients, asynchronous, openai_profile):
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter, ModelAdapterError
    from nexent.core.model_service.errors import normalize_model_error

    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    stream_request = ModelRequest(request_id="r1", outlet_id=openai_profile.outlet_id,
                                  config_revision=openai_profile.config_revision, stream=True, messages=[ModelMessage(semantic_role="user")])
    payload = b'data: {"error":{"message":"invalid header-secret"}}\n\n'
    clients(lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload))
    sender = HttpRequestSender(lambda _: {"x-api-key": "header-secret"})
    wire = request(stream_protocol="sse")
    adapter = OpenAIChatAdapter()
    with pytest.raises(ModelAdapterError) as caught:
        if asynchronous:
            async with sender.astream(wire) as frames:
                async for _ in adapter.adecode_stream(frames, stream_request, openai_profile):
                    pass
        else:
            with sender.stream(wire) as frames:
                list(adapter.decode_stream(frames, stream_request, openai_profile))
    assert normalize_model_error(caught.value, request_id="r1").safe_message == "invalid [redacted]"
