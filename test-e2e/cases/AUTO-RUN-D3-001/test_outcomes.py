# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual automation runner -> streaming projection -> PostgreSQL outcomes."""

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import redis
from fastapi import FastAPI
import pytest_asyncio

from shared.automation_run_fixture import run_store
from shared.factories.redis_target import deployed_redis_urls
from management.api.automation import agent_automation as api
from management.db.automation import repository as runs
from management.db.models import ConversationMessage, ConversationMessageUnit
from management.services.agent import execution, lifecycle, run, run_state
from management.services.automation import runner
from management.services.automation.service import AgentAutomationFacade
from nexent.core.concurrency import LanePolicy, ThreadManager

pytestmark = [pytest.mark.case_id("AUTO-RUN-D3-001"), pytest.mark.stage("D3")]
cancel_poll = run._cancel_task_on_runtime_signal
stop_poll = execution._poll_runtime_cancel_signal


@pytest_asyncio.fixture
async def runtime(monkeypatch, run_store):
    info = SimpleNamespace(agent_config=SimpleNamespace(pre_run_tool_events=()), cancellation_scope=None,
                           stop_event=asyncio.Event(), attempt_outcome=None, human_interaction=None, thread_future=None)
    state = SimpleNamespace(info=info, mode="completed", entered=asyncio.Event(), preparations=0)
    manager = ThreadManager("automation-outcome-test", {"control-io": LanePolicy(
        name="control-io", max_workers=2, max_queue_size=8,
    )})
    manager.start()
    monkeypatch.setattr(execution, "runtime_thread_manager", manager)

    async def idle(*args, **kwargs):
        await asyncio.Event().wait()

    async def prepare(**kwargs):
        state.preparations += 1
        info.stop_event = asyncio.Event()
        info.attempt_outcome = None
        if state.mode == "preparation_failed":
            raise RuntimeError("controlled preparation failure")
        if state.mode == "before_assistant":
            state.entered.set()
            await asyncio.Event().wait()
        if state.mode == "fallback" and state.preparations == 1:
            raise RuntimeError("controlled memory preparation failure")
        return info, None

    async def producer(*args, **kwargs):
        if state.mode in {"retry", "fallback"}:
            yield json.dumps({"type": "error", "content": "transient error", "retryable": True})
        yield json.dumps({"type": "final_answer", "content": "saved partial answer"})
        if state.mode == "during_artifacts":
            yield json.dumps({"type": "skill_artifact", "content": {
                "artifacts": [{"absolute_path": "/fixture/report.txt"}],
            }})
        state.entered.set()
        if state.mode == "during_output":
            await asyncio.Event().wait()
        if state.mode == "raised":
            raise RuntimeError("controlled generation failure")
        info.attempt_outcome = None if state.mode == "missing" else "failed" if state.mode == "failed" else "completed"
        if state.mode == "failed":
            yield json.dumps({"type": "error", "content": "terminal model failure", "retryable": False})

    monkeypatch.setattr(runner, "validate_bindings_available", AsyncMock(return_value={"available": True}))
    monkeypatch.setattr(runner, "is_agent_running", lambda *a: False)
    monkeypatch.setattr(runner, "stop_agent_tasks", lambda *a, **k: info.stop_event.set())
    monkeypatch.setattr(run, "build_agent_run_context", lambda *a, **k: SimpleNamespace(
        metadata={}, enable_memory=state.mode == "fallback"))
    monkeypatch.setattr(run, "build_memory_context", lambda *a: SimpleNamespace(
        user_config=SimpleNamespace(memory_switch=True)))
    monkeypatch.setattr(run, "agent_monitoring_context", lambda *a: nullcontext())
    monkeypatch.setattr(run, "prepare_agent_run", prepare)
    monkeypatch.setattr(run, "_cancel_task_on_runtime_signal", idle)
    monkeypatch.setattr(execution, "_poll_runtime_cancel_signal", idle)
    monkeypatch.setattr(execution, "agent_run", producer)
    async def upload(**kwargs):
        state.entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(execution, "_process_skill_file_uploads", upload)
    for module in (run, execution):
        monkeypatch.setattr(module, "_unregister_agent_run_after_execution", lambda *a, **k: None)
    monkeypatch.setattr(run.agent_run_manager, "stop_agent_run", lambda *a: None)
    channel = SimpleNamespace(publish=AsyncMock())
    monkeypatch.setattr(execution.streaming_channel_manager, "get_or_create_channel", AsyncMock(return_value=channel))
    monkeypatch.setattr(execution.streaming_channel_manager, "complete_channel", AsyncMock())
    monkeypatch.setattr(execution, "_cleanup_channel_later", AsyncMock())
    try:
        yield state
    finally:
        await manager.shutdown(timeout=5)


def assert_identity(store, result, *, assistant=True):
    messages = store.rows(ConversationMessage)
    own = {row["message_id"]: row for row in messages if row["message_source"] == "AUTOMATION"}
    assert result["user_message_id"] in own
    assert own[result["user_message_id"]]["message_role"] == "user"
    if assistant:
        assert result["assistant_message_id"] in own
        assert own[result["assistant_message_id"]]["message_role"] == "assistant"
    else:
        assert result["assistant_message_id"] is None
    assert set(own) == {result["user_message_id"], result["assistant_message_id"]} - {None}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("completed", "SUCCEEDED"), ("failed", "FAILED"), ("raised", "FAILED"),
    ("preparation_failed", "FAILED"), ("missing", "FAILED"), ("retry", "SUCCEEDED"), ("fallback", "SUCCEEDED"),
])
async def test_stream_result_and_own_message_identity(run_store, runtime, mode, expected):
    runtime.mode = mode
    # A previous saved assistant must never be used if preparation now fails.
    from management.db.conversation.repository import create_conversation_message
    previous = create_conversation_message(dict(conversation_id=1, message_idx=1,
                                                role="assistant", content="previous"), "owner")
    result = await runner.AgentAutomationRunner().execute_task(run_store.task)
    assert result["status"] == expected
    assert result["assistant_message_id"] != previous
    assert_identity(run_store, result, assistant=mode != "preparation_failed")
    task = runs.get_task(run_store.task["task_id"], "tenant", "owner")
    assert task["consecutive_failures"] == (0 if expected == "SUCCEEDED" else 1)
    assert task["last_run_status"] == expected
    if mode != "preparation_failed":
        message = next(row for row in run_store.rows(ConversationMessage) if row["message_id"] == result["assistant_message_id"])
        assert message["status"] == ("completed" if expected == "SUCCEEDED" else "failed")
        assert message["message_content"] == "saved partial answer"
    if mode == "fallback":
        assert runtime.preparations == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_assistant", "during_output", "during_artifacts"])
@pytest.mark.parametrize("terminal", ["TIMEOUT", "CANCELED"])
async def test_timeout_and_cancel_preserve_links_and_settle_output(run_store, runtime, phase, terminal):
    runtime.mode = phase
    worker = asyncio.create_task(runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL"))
    await asyncio.wait_for(runtime.entered.wait(), 3)
    if terminal == "CANCELED":
        current = runs.list_runs(run_store.task["task_id"], "tenant", "owner")[0]
        assert AgentAutomationFacade().cancel_run(current["run_id"], "tenant", "owner")["status"] == "CANCELED"
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(worker, 5)
    else:
        assert (await asyncio.wait_for(worker, 5))["status"] == "TIMEOUT"
    result = runs.list_runs(run_store.task["task_id"], "tenant", "owner")[0]
    assert result["status"] == terminal
    assert_identity(run_store, result, assistant=phase != "before_assistant")
    if phase != "before_assistant":
        assistant = next(row for row in run_store.rows(ConversationMessage) if row["message_id"] == result["assistant_message_id"])
        assert assistant["status"] == "stopped"
        assert assistant["message_content"] == "saved partial answer"
        assert any(row["message_id"] == assistant["message_id"] for row in run_store.rows(ConversationMessageUnit))
    assert not runs.has_active_run_for_conversation(1)


@pytest.mark.asyncio
async def test_failed_commit_cannot_be_reported_as_success(run_store, runtime, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("controlled persistence failure")

    monkeypatch.setattr(execution, "persist_assistant_run_batch", fail)
    result = await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL")
    assert result["status"] == "FAILED"
    assert result["error_code"] == "AUTOMATION_PERSISTENCE_FAILED"
    assert_identity(run_store, result)
    assistant = next(row for row in run_store.rows(ConversationMessage) if row["message_id"] == result["assistant_message_id"])
    assert assistant["status"] == "failed"


@pytest.fixture
def real_cancel(monkeypatch, runtime):
    url, _ = deployed_redis_urls()
    wire = run_state.RuntimeStateService()
    wire._client = redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    wire.client.ping()
    monkeypatch.setattr(run_state, "RUNTIME_STATE_REDIS_URL", url)
    prefix = "auto-lifecycle-test:" + uuid4().hex + ":"
    for name in ("_run_key", "_cancel_key", "_stream_key", "_stream_done_key"):
        original = getattr(wire, name)
        monkeypatch.setattr(wire, name, lambda *args, original=original: prefix + original(*args))
    for module in (run, execution, lifecycle):
        monkeypatch.setattr(module, "runtime_state_service", wire)
    monkeypatch.setattr(run, "_cancel_task_on_runtime_signal", cancel_poll)
    monkeypatch.setattr(execution, "_poll_runtime_cancel_signal", stop_poll)
    monkeypatch.setattr(run.agent_run_manager, "stop_agent_run",
                        lifecycle.AgentRunManager.stop_agent_run.__get__(run.agent_run_manager))
    monkeypatch.setattr(runner, "stop_agent_tasks", run.stop_agent_tasks)
    monkeypatch.setattr(execution, "RUNTIME_CANCEL_POLL_INTERVAL_SECONDS", 0.01)
    try:
        yield wire
    finally:
        keys = list(wire.client.scan_iter(prefix + "*"))
        if keys:
            wire.client.delete(*keys)
        assert list(wire.client.scan_iter(prefix + "*")) == []
        wire.client.close()


@pytest.mark.asyncio
async def test_next_turn_clears_old_cancel_but_rejects_delayed_stop(run_store, runtime, real_cancel):
    runtime.mode = "during_output"
    first = await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL")
    assert first["status"] == "TIMEOUT" and real_cancel.is_cancelled("owner", 1)
    runtime.mode = "completed"
    runtime.entered.clear()
    second = await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL")
    assert second["status"] == "SUCCEEDED"
    assert second["assistant_message_id"] != first["assistant_message_id"]
    assert not real_cancel.set_cancel_signal("owner", 1, str(first["run_id"]))
    real_cancel.mark_run_finished("owner", 1, "failed", generation=str(first["run_id"]))
    assert real_cancel.get_run_state("owner", 1).get("status") != "failed"
    assert not real_cancel.is_cancelled("owner", 1)
    assert real_cancel.set_cancel_signal("owner", 1, str(second["run_id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_assistant", "during_output"])
async def test_user_cancel_returns_http_result_and_preparation_cancel_survives(run_store, runtime, real_cancel,
                                                                               monkeypatch, phase):
    runtime.mode = phase
    monkeypatch.setattr(api, "_get_current_user", lambda _: ("owner", "tenant"))
    app = FastAPI()
    app.include_router(api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        request = asyncio.create_task(client.post(f"/agent/automations/{run_store.task['task_id']}/run"))
        await asyncio.wait_for(runtime.entered.wait(), 3)
        current = runs.list_runs(run_store.task["task_id"], "tenant", "owner")[0]
        canceled = AgentAutomationFacade().cancel_run(current["run_id"], "tenant", "owner")
        assert canceled["status"] == "CANCELED"
        response = await asyncio.wait_for(request, 5)
        assert response.status_code == 200 and response.json()["data"]["status"] == "CANCELED"
        assert response.json()["data"]["user_message_id"] is not None
        assert not runs.has_active_run_for_conversation(1)
    runtime.mode = "completed"
    assert (await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL"))["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_actual_caller_cancellation_still_propagates(run_store, runtime, real_cancel):
    runtime.mode = "during_output"
    request = asyncio.create_task(runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL"))
    await asyncio.wait_for(runtime.entered.wait(), 3)
    current = runs.list_runs(run_store.task["task_id"], "tenant", "owner")[0]
    AgentAutomationFacade().cancel_run(current["run_id"], "tenant", "owner")
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(request, 5)


@pytest.mark.asyncio
async def test_regression_detects_missing_background_reset(run_store, runtime, real_cancel, monkeypatch):
    real_cancel.reset_stream("owner", 1, generation="previous")
    assert real_cancel.set_cancel_signal("owner", 1, expected_generation="previous")
    runtime.mode = "during_output"
    with monkeypatch.context() as fault:
        fault.setattr(real_cancel, "reset_stream_async", AsyncMock())
        with pytest.raises(asyncio.CancelledError):
            await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL")
    runtime.mode = "completed"
    assert (await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL"))["status"] == "SUCCEEDED"
