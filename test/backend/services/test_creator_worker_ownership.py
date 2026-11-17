# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Worker admission, cancellation and finalization retain one execution owner."""

import asyncio
import json
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.conversation import creator_runtime as runtime


@pytest.fixture
def worker(monkeypatch):
    state = SimpleNamespace(
        enabled=False,
        creator_lease_async=AsyncMock(return_value=True),
        is_cancelled_async=AsyncMock(return_value=False),
        mark_stream_completed_async=AsyncMock(),
    )
    channel = SimpleNamespace(
        generation=None, publish=AsyncMock(), complete=MagicMock(),
        subscribe_with_history=MagicMock(return_value="subscription"),
    )
    channels = SimpleNamespace(
        get_channel=MagicMock(return_value=None),
        get_or_create_channel=AsyncMock(return_value=channel),
        remove_channel=AsyncMock(),
    )
    manager = MagicMock()
    monkeypatch.setattr(runtime, "runtime_state_service", state)
    monkeypatch.setattr(runtime, "streaming_channel_manager", channels)
    monkeypatch.setattr(runtime, "agent_run_manager", manager)
    return SimpleNamespace(state=state, channel=channel, channels=channels, manager=manager)


def source(events=(), *, failure=None, close_error=None, idle=False):
    async def iterate():
        if idle:
            await asyncio.Event().wait()
        for event in events:
            yield event
        if failure:
            raise failure

    return SimpleNamespace(
        __aiter__=iterate,
        aclose=AsyncMock(side_effect=close_error),
    )


class Stream:
    def __init__(self, **kwargs):
        self.parts = source(**kwargs)
        self.aclose = self.parts.aclose

    def __aiter__(self):
        return self.parts.__aiter__()


async def launch(stream, control=None):
    control = control or runtime.CreatorControl()
    result = await runtime.launch_creator(
        stream, control=control, conversation_id=91, user_id="owner", reservation="reserved",
    )
    assert result == "subscription"
    await asyncio.wait_for(asyncio.gather(*runtime._producers), timeout=2)
    return control


@pytest.mark.asyncio
async def test_control_admits_the_configured_scope_and_cancels_its_managed_worker(monkeypatch):
    execution = SimpleNamespace(execution_id="worker", future=Future())
    manager = SimpleNamespace(
        submit=MagicMock(return_value=execution), wait_until_started=AsyncMock(), cancel=MagicMock(),
    )
    monkeypatch.setattr(runtime, "runtime_thread_manager", manager)
    control = runtime.CreatorControl()
    info = SimpleNamespace()
    control.configure(info)
    await control.admit()
    assert control.execution is execution and control.registered_info() is info
    assert info.stop_event is control.stop_event and info.cancellation_scope is control.scope
    assert info.__dict__["_automation_runtime_generation"] == control.generation
    assert manager.submit.call_args.args[1].run_id == control.generation
    manager.wait_until_started.assert_awaited_once_with(execution)
    control.cancel()
    assert control.stop_event.is_set()
    manager.cancel.assert_called_once_with(
        "worker", reason="creator execution cancelled", wait_timeout=0, mark_stuck_on_timeout=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [False, True])
async def test_idempotency_claim_release_and_expiry_are_owner_scoped(monkeypatch, remote):
    state = SimpleNamespace(
        enabled=remote, acquire_idempotency_async=AsyncMock(return_value=True),
        release_idempotency_async=AsyncMock(),
    )
    monkeypatch.setattr(runtime, "runtime_state_service", state)
    monkeypatch.setattr(runtime, "_request_claims", {"expired": 1, "other-owner": 100})
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 10)
    assert await runtime.claim_request("request", 5)
    if remote:
        state.acquire_idempotency_async.assert_awaited_once_with("request", 5)
    else:
        assert "expired" not in runtime._request_claims
        assert not await runtime.claim_request("request", 5)
        assert not await runtime.claim_request("other-owner", 5)
    await runtime.release_request("request")
    if remote:
        state.release_idempotency_async.assert_awaited_once_with("request")
    else:
        assert await runtime.claim_request("request", 5)
        assert runtime._request_claims["other-owner"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("lease_error", [False, True])
async def test_preparation_heartbeat_cancels_the_owner_on_lease_failure(worker, lease_error):
    worker.state.enabled = True
    worker.state.creator_lease_async.side_effect = RuntimeError("lease unavailable") if lease_error else None
    worker.state.creator_lease_async.return_value = False
    control = runtime.CreatorControl()

    async def prepare():
        guard = control.guard_preparation(91, "owner")
        try:
            await asyncio.Event().wait()
        finally:
            await guard

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.create_task(prepare()), timeout=2)
    assert control.stop_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("claim unavailable")])
async def test_rejected_shared_claim_releases_its_local_reservation(worker, failure):
    worker.manager.reserve_agent_run.return_value = "reserved"
    worker.state.claim_creator_run_async = AsyncMock(return_value=False, side_effect=failure)
    with pytest.raises(RuntimeError if failure else runtime.AgentRunAlreadyActiveError):
        await runtime.claim_creator(91, "owner", "run")
    worker.manager.release_agent_run_reservation.assert_called_once_with(91, "owner", "reserved")
    worker.manager.register_agent_run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["lease", "remote-stop", "heartbeat-error", "event-lease", "local-stop"])
async def test_cancelled_worker_never_reports_success_or_publishes_unowned_output(worker, reason):
    control = runtime.CreatorControl()
    idle = reason not in {"event-lease", "local-stop"}
    if reason in {"lease", "event-lease"}:
        worker.state.creator_lease_async.return_value = False
    elif reason == "remote-stop":
        worker.state.is_cancelled_async.return_value = True
    elif reason == "heartbeat-error":
        worker.state.creator_lease_async.side_effect = RuntimeError("lease unavailable")
    else:
        control.stop_event.set()
    stream = Stream(events=['data: {"type":"parse","content":"not-owned"}\n\n'], idle=idle)
    await launch(stream, control)
    worker.channel.publish.assert_not_awaited()
    worker.channel.complete.assert_called_once_with("stopped")
    assert worker.manager.unregister_agent_run.call_args.args == (91, "owner", "stopped")
    stream.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_replacing_a_channel_and_stream_failure_keep_generation_fenced_cleanup(worker):
    previous = object()
    worker.channels.get_channel.return_value = previous
    stream = Stream(events=[": keepalive\n\n"], failure=RuntimeError("private provider detail"))
    control = await launch(stream)
    assert worker.channels.remove_channel.await_args_list[0].kwargs["expected_channel"] is previous
    assert worker.channels.remove_channel.await_args_list[-1].kwargs["expected_channel"] is worker.channel
    error = json.loads(worker.channel.publish.await_args_list[-1].args[0][6:])
    assert error == {"type": "error", "content": "Creator execution failed."}
    worker.channel.complete.assert_called_once_with("failed")
    assert worker.channel.generation == control.generation


@pytest.mark.asyncio
async def test_stream_cleanup_failure_is_failed_and_releases_only_after_worker_exit(worker):
    future = Future()
    control = runtime.CreatorControl()
    control.execution = SimpleNamespace(future=future)
    stream = Stream(close_error=RuntimeError("cleanup failed"))
    await launch(stream, control)
    worker.channel.complete.assert_called_once_with("failed")
    worker.manager.unregister_agent_run.assert_not_called()
    future.set_result(None)
    worker.manager.unregister_agent_run.assert_called_once_with(
        91, "owner", "failed", agent_run_info=worker.manager.register_agent_run.call_args.args[1],
    )


@pytest.mark.asyncio
async def test_finalization_error_still_removes_channel_and_releases_owner(worker, caplog):
    worker.state.mark_stream_completed_async.side_effect = RuntimeError("state unavailable")
    stream = Stream()
    control = runtime.CreatorControl()
    await runtime.launch_creator(stream, control=control, conversation_id=91, user_id="owner", reservation="r")
    tasks = list(runtime._producers)
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)
    worker.channels.remove_channel.assert_awaited_once()
    worker.manager.unregister_agent_run.assert_called_once()
    assert "Creator finalization failed" in caplog.text


@pytest.mark.asyncio
async def test_live_worker_renews_ownership_until_shutdown(worker):
    stream = Stream(idle=True)
    await runtime.launch_creator(
        stream, control=runtime.CreatorControl(), conversation_id=91, user_id="owner", reservation="r",
    )
    await asyncio.sleep(0)
    worker.state.creator_lease_async.assert_awaited()
    worker.state.is_cancelled_async.assert_awaited()
    assert await runtime.shutdown_creator_streams(2) == 0
    worker.channel.complete.assert_called_once_with("stopped")
    worker.manager.unregister_agent_run.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_error_ends_as_failed_without_cancelling_the_finished_worker(worker):
    stream = Stream(events=['data: {"type":"error","content":"service unavailable"}\n\n'])
    control = await launch(stream)
    worker.channel.complete.assert_called_once_with("failed")
    assert not control.stop_event.is_set()
    assert worker.manager.unregister_agent_run.call_args.args == (91, "owner", "failed")


@pytest.mark.asyncio
async def test_idle_shutdown_does_not_reserve_or_cancel_a_worker(worker, monkeypatch):
    monkeypatch.setattr(runtime, "_producers", set())
    assert await runtime.shutdown_creator_streams(0) == 0
    worker.manager.register_agent_run.assert_not_called()
    worker.manager.unregister_agent_run.assert_not_called()

