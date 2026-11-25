# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native A2A preserves the configured transport, result, and cancellation ownership."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from a2a.client.errors import A2AClientTimeoutError
from a2a.types import StreamResponse
from google.protobuf.json_format import ParseDict

from nexent.core.agents.cores.jiuwen import a2a
from nexent.core.agents.resources.a2a import A2AAgentInfo
from nexent.core.concurrency import RunCancellationScope


@pytest.fixture
def invoke():
    scope = RunCancellationScope()

    async def run(info, *, timeout=2):
        result = await a2a.invoke_native_a2a(
            info, "Find the document", scope=scope,
            runtime_metadata={"trace": "run-trace", "user_context": {"user": "stale"}},
            user_context={"user": "authorized"}, timeout=timeout, close_timeout=0.1,
        )
        return result

    return run, scope


@pytest.fixture
def transport(mocker):
    def bind(handler):
        return mocker.patch.object(
            a2a.httpx, "AsyncClient",
            side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )

    client_type = httpx.AsyncClient
    return bind


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,endpoint", [
    ("JSONRPC", "/remote"), ("HTTP+JSON", "/remote/message:send"), ("HTTP+JSON", "/remote/message:stream"),
])
async def test_native_a2a_stream_uses_configured_endpoint_and_joins_chunks(invoke, transport, protocol, endpoint):
    run, scope = invoke

    def respond(request):
        body = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.path == ("/remote" if protocol == "JSONRPC" else "/remote/message:stream")
        assert request.headers["authorization"] == "Bearer test-remote"
        assert request.headers["x-bound"] == "profile"
        assert request.headers["a2a-version"] == "1.0"
        if protocol == "JSONRPC":
            assert body["method"] == "SendStreamingMessage"
        message = body.get("params", body)["message"]
        assert message["metadata"] == {"trace": "run-trace", "user_context": {"user": "authorized"}}
        assert message["parts"] == [{"text": "Find the document"}]
        events = [
            {"artifactUpdate": {
                "taskId": "remote-task", "contextId": "remote-context",
                "artifact": {"artifactId": "text", "parts": [{"text": "first"}]},
            }},
            {"artifactUpdate": {
                "taskId": "remote-task", "contextId": "remote-context", "append": True,
                "artifact": {"artifactId": "text", "parts": [{"text": " second"}]},
            }},
            {"statusUpdate": {
                "taskId": "remote-task", "contextId": "remote-context", "status": {"state": "TASK_STATE_COMPLETED"},
            }},
        ]
        if protocol == "JSONRPC":
            events = [{"jsonrpc": "2.0", "id": body["id"], "result": event} for event in events]
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"},
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    factory = transport(respond)
    remote = A2AAgentInfo(
        "external", "Remote", f"https://a2a.example{endpoint}", api_key="test-remote",
        protocol_type=protocol, raw_card={"capabilities": {"streaming": True}}, custom_headers={"X-Bound": "profile"},
    )
    assert await run(remote) == "first second"
    assert factory.call_args.kwargs["verify"] is True
    assert not scope._closers


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_kind,expected", [
    ("artifact", "polled result"), ("status", "task status text"), ("empty", "No response received"),
    ("message", "immediate reply"),
])
async def test_native_a2a_returns_final_snapshot_or_immediate_reply(invoke, transport, answer_kind, expected):
    run, scope = invoke
    methods = []

    def respond(request):
        body = json.loads(request.content)
        method = body["method"]
        methods.append(method)
        if method == "SendMessage":
            if answer_kind == "message":
                value = {"message": {"role": "ROLE_AGENT", "messageId": "reply", "parts": [{"text": expected}]}}
            else:
                value = {"task": {
                    "id": "owned", "contextId": "context", "status": {"state": "TASK_STATE_WORKING"},
                    "artifacts": [{"artifactId": "text", "parts": [{"text": "provisional text"}]}]
                    if answer_kind == "artifact" else [],
                }}
        else:
            assert method == "GetTask"
            assert body["params"]["id"] == "owned"
            value = {"id": "owned", "contextId": "context", "status": {"state": "TASK_STATE_COMPLETED"}}
            if answer_kind == "artifact":
                value["artifacts"] = [{"artifactId": "text", "parts": [{"text": expected}]}]
            if answer_kind == "status":
                value["status"]["message"] = {"parts": [{"text": expected}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": value})

    transport(respond)
    remote = A2AAgentInfo("external", "Remote", "https://a2a.example/remote", transport_type="http")
    assert await run(remote) == expected
    assert methods == (["SendMessage"] if answer_kind == "message" else ["SendMessage", "GetTask"])
    assert not scope._closers


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider_timeout", "unknown_task", "remote_cancel_error", "local_cancel"])
async def test_native_a2a_cancels_only_a_known_active_task(invoke, mocker, caplog, failure):
    run, scope = invoke
    ready, closed = asyncio.Event(), asyncio.Event()

    async def events(_request):
        try:
            if failure != "unknown_task":
                yield ParseDict({"statusUpdate": {"taskId": "owned", "status": {"state": "TASK_STATE_WORKING"}}},
                                StreamResponse())
            if failure == "local_cancel":
                ready.set()
                await asyncio.Future()
            raise A2AClientTimeoutError("private provider payload")
        finally:
            closed.set()

    cancel = AsyncMock(side_effect=RuntimeError("private remote body") if failure == "remote_cancel_error" else None)
    mocker.patch.object(a2a, "_ConfiguredA2AClient", return_value=SimpleNamespace(events=events, cancel_task=cancel))
    remote = A2AAgentInfo("external", "Remote", "https://a2a.example/remote")
    task = asyncio.create_task(run(remote))
    if failure == "local_cancel":
        await asyncio.wait_for(ready.wait(), timeout=1)
        scope.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(TimeoutError, match="^A2A request timed out$"):
            await task
        assert "event=a2a_request_timeout" in caplog.text
    if failure == "unknown_task":
        cancel.assert_not_awaited()
    else:
        cancel.assert_awaited_once_with("owned")
    assert ("event=a2a_remote_cancel_failed" in caplog.text) is (failure == "remote_cancel_error")
    assert "private" not in caplog.text
    assert closed.is_set() and not scope._closers


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unsupported", "cancelled", "expired"])
async def test_native_a2a_rejects_dispatch_without_its_transport_or_run_budget(invoke, mocker, state):
    run, scope = invoke
    remote = A2AAgentInfo("external", "Remote", "https://a2a.example/remote")
    client = mocker.patch.object(a2a, "_ConfiguredA2AClient")
    if state == "unsupported":
        remote.protocol_type = "GRPC"
        with pytest.raises(ValueError, match="Unsupported"):
            await run(remote)
        client.assert_not_called()
    elif state == "cancelled":
        scope.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run(remote)
        client.assert_not_called()
    else:
        with pytest.raises(TimeoutError, match="before dispatch"):
            await run(remote, timeout=0)
        client.return_value.events.assert_not_called()
    assert not scope._closers
