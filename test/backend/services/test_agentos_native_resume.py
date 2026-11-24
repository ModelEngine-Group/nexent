# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cursor replay must reconstruct Native mapper state from authorized raw history."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from .test_agentos_native_projection import REQUEST, RUN, chain, collect, observer, response, terminal

from management.services.agent import runtime_client


@pytest.fixture(autouse=True)
def native_runtime(mocker):
    mocker.patch.object(runtime_client, "NEXENT_AGENT_CORE", "jiuwen")


def cursor(index):
    return REQUEST.model_copy(update={"after_event_id": f"{RUN}:{index}"})


@pytest.mark.parametrize("after", [1, 2, 3, 4, 5, 6])
async def test_native_cursor_replays_only_suffix_with_original_pairing(mocker, after):
    closed = []
    frames = [observer(index, value) for index, value in enumerate(chain(), 1)] + [terminal(6)]
    async def suffix_source():
        try:
            for frame in frames[after:]:
                yield frame
        finally:
            closed.append("suffix")

    suffix = StreamingResponse(suffix_source())
    async def prefix_source():
        try:
            for frame in frames:
                yield frame
        finally:
            closed.append("prefix")

    prefix = StreamingResponse(prefix_source(), background=BackgroundTask(lambda: closed.append("prefix-owner")))
    resume = AsyncMock(side_effect=[suffix, prefix])
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(resume=resume))
    request = cursor(after)
    result = await runtime_client.forward_conversation_resume(request, "owner", "tenant")
    wire, rows = await collect(result)
    assert closed == (["prefix", "prefix-owner", "suffix"] if after < 6 else ["suffix"])
    expected_calls = [(request, "owner", "tenant")]
    if after < 6:
        expected_calls.append((REQUEST, "owner", "tenant"))
    assert [call.args for call in resume.await_args_list] == expected_calls
    assert not any(value.get("runtime_mode") for _, value in rows)
    assert not any(value.get("type") == "error" for _, value in rows)
    assert all(int(event_id.rsplit(":", 1)[1]) > after for event_id, _ in rows if event_id)
    if after < 3:
        output = next(value for _, value in rows if value.get("type") == "execution_logs")
        assert output["content"] == "EXACT_RESULT" and output["provider_call_id"] == "provider-" + "z" * 260
        assert output["tool_call_id"] == '["root","","local"]'
    else:
        assert not any(value.get("type") == "execution_logs" for _, value in rows)
    if after == 6:
        assert wire == b""
    else:
        assert [value["content"] for _, value in rows if value.get("type") == "final_answer"] == ["Answer"]


@pytest.mark.parametrize("status", [403, 409, 410])
async def test_original_cursor_rejection_does_not_open_a_prefix(mocker, status):
    rejected = response(b"Original scoped rejection", status_code=status)
    resume = AsyncMock(return_value=rejected)
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(resume=resume))
    request = cursor(2)
    assert await runtime_client.forward_conversation_resume(request, "owner", "tenant") is rejected
    resume.assert_awaited_once_with(request, "owner", "tenant")


async def test_missing_prefix_emits_error_and_closes_both_responses(mocker):
    closed = []

    async def suffix_source():
        try:
            yield observer(3, chain()[2])
        finally:
            closed.append("suffix")

    suffix = StreamingResponse(suffix_source())
    expired = response(b"Original missing-start error", status_code=410,
                       background=BackgroundTask(lambda: closed.append("prefix")))
    resume = AsyncMock(side_effect=[suffix, expired])
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(resume=resume))
    result = await runtime_client.forward_conversation_resume(cursor(2), "owner", "tenant")
    _, rows = await collect(result)
    assert [row[1]["type"] for row in rows] == ["error"]
    assert closed == ["prefix", "suffix"] and resume.await_count == 2


async def test_cancelling_prefix_warmup_closes_both_owned_transports(mocker):
    closed, waiting = [], asyncio.Event()

    async def source():
        try:
            yield observer(1, chain()[0])
            waiting.set()
            await asyncio.Event().wait()
        finally:
            closed.append("prefix-body")

    async def suffix_source():
        try:
            yield observer(3, chain()[2])
        finally:
            closed.append("suffix-body")

    suffix = StreamingResponse(suffix_source())
    prefix = StreamingResponse(source(), background=BackgroundTask(lambda: closed.append("prefix")))
    resume = AsyncMock(side_effect=[suffix, prefix])
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(resume=resume))
    output = await runtime_client.forward_conversation_resume(cursor(2), "owner", "tenant")
    task = asyncio.create_task(anext(output.body_iterator))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == ["prefix-body", "prefix", "suffix-body"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await output.body_iterator.aclose()


@pytest.mark.parametrize("mode", ["disconnect", "cancel"])
async def test_suffix_disconnect_or_cancellation_releases_both_streams(mocker, mode):
    closed, waiting = [], asyncio.Event()

    async def prefix_source():
        try:
            yield observer(1, chain()[0])
        finally:
            closed.append("prefix-body")

    async def suffix_source():
        try:
            yield observer(2, chain()[1])
            waiting.set()
            await asyncio.Event().wait()
        finally:
            closed.append("suffix-body")

    prefix = StreamingResponse(prefix_source(), background=BackgroundTask(lambda: closed.append("prefix-owner")))
    suffix = StreamingResponse(suffix_source())
    resume = AsyncMock(side_effect=[suffix, prefix])
    client = SimpleNamespace(resume=resume, run=AsyncMock())
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    output = await runtime_client.forward_conversation_resume(cursor(1), "owner", "tenant")
    first = await anext(output.body_iterator)
    assert b'"type": "tool"' in first and b"Step" not in first
    if mode == "cancel":
        task = asyncio.create_task(anext(output.body_iterator))
        try:
            await asyncio.wait_for(waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    await output.body_iterator.aclose()
    assert closed == ["prefix-body", "prefix-owner", "suffix-body"]
    client.run.assert_not_awaited()
    assert resume.await_count == 2


@pytest.mark.parametrize("fault", ["eof", "outer_before_ack", "gap", "runtime_error"])
@pytest.mark.parametrize("controls", [False, True])
async def test_prefix_failure_before_ack_is_not_a_silent_success(mocker, fault, controls):
    from management.services.agent import agentos_events

    frames = [observer(1, chain()[0])]
    if fault == "outer_before_ack":
        frames.append(terminal(2))
    elif fault == "gap":
        frames.append(observer(3, chain()[2]))
    elif fault == "runtime_error":
        frames.append(b'event: agentos_error\ndata: {"code":"AGENTOS_EVENT_STORE_UNAVAILABLE"}\n\n')
    present = agentos_events.present_public_resume

    def configured(*args, **kwargs):
        return present(*args, **kwargs, include_journal_controls=controls)

    mocker.patch.object(runtime_client, "present_public_resume", side_effect=configured)
    resume = AsyncMock(side_effect=[response(terminal(6)), response(*frames)])
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(resume=resume))
    result = await runtime_client.forward_conversation_resume(cursor(4), "owner", "tenant")
    wire, rows = await collect(result)
    assert wire and not any(value.get("type") == "final_answer" for _, value in rows)
    assert not any(value.get("type") == "step_count" for _, value in rows)
    assert len(rows) == 1 and rows[0][1]["type"] == "error"
