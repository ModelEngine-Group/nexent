# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Automation outcomes through the AgentOS journal and Management persistence."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import redis
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from shared.automation_run_fixture import run_store
from shared.factories.redis_target import deployed_redis_urls

from contracts.agentos import AgentRunReference
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.redis import agent_events, run_state
from management.api.automation import agent_automation as api
from management.db.automation import repository as runs
from management.db.models import ConversationMessage, ConversationMessageUnit
from management.services.agent import background, prepared_projection, runtime_client
from management.services.automation import runner
from management.services.automation.service import AgentAutomationFacade
from runtime.agentos import resume

pytestmark = [pytest.mark.case_id("AUTO-RUN-D3-001"), pytest.mark.stage("D3")]

ACTOR = ServicePrincipal("owner", "tenant")
ANSWER = "saved partial answer"
CHUNK = f"event: agentos_observer\ndata: {json.dumps({'type': 'final_answer', 'content': ANSWER})}\n\n"


@pytest.fixture
def wire(monkeypatch):
    url, _ = deployed_redis_urls()
    monkeypatch.setattr(run_state, "RUNTIME_STATE_REDIS_URL", url)
    service = run_state.RuntimeStateService()
    client = redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    service._client = client
    client.ping()
    monkeypatch.setattr(agent_events, "runtime_state_service", service)
    monkeypatch.setattr(resume, "runtime_state_service", service)
    journals = {}

    def journal(reference):
        return journals.setdefault(reference.run_id, agent_events.RunJournal(
            ACTOR.tenant_id, ACTOR.user_id, reference.conversation_id, reference.run_id, retain_for_projection=True,
        ))

    try:
        yield journal
    finally:
        keys = [key for item in journals.values() for key in (item.key, item.cancel_key)]
        if keys:
            client.delete(*keys)
            assert not client.exists(*keys)
        client.close()


@pytest.fixture
def runtime(monkeypatch, wire, run_store):
    state = SimpleNamespace(
        mode="completed", entered=asyncio.Event(), release=asyncio.Event(),
        preparations=0, reference=None, replay_attempts=0, admissions=0,
    )

    async def prepare(request, reference, user_id, tenant_id, *, current_user_message_id):
        assert (user_id, tenant_id, request.conversation_id) == (ACTOR.user_id, ACTOR.tenant_id, 1)
        assert request.enable_automation_tool is False and current_user_message_id > 0
        state.preparations += 1
        if state.mode == "preparation_failed":
            raise RuntimeError("controlled preparation failure")
        if state.mode == "cancel_in_preparation":
            state.entered.set()
            await state.release.wait()
        if state.mode == "fallback" and state.preparations == 1:
            return None
        return SimpleNamespace(reference=reference, memory_enabled=False)

    async def start(snapshot, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        state.admissions += 1
        state.reference = reference = snapshot.reference
        journal = wire(reference)
        journal.start()
        if state.mode != "before_output":
            journal.append(1, CHUNK)
        if state.mode == "during_artifacts":
            artifact = {
                "type": "file_artifact",
                "content": {"artifacts": [{
                    "object_name": f"workspace/{user_id}/{reference.run_id}/outputs/report.txt",
                    "name": "report.txt",
                }]},
            }
            journal.append(2, f"event: agentos_observer\ndata: {json.dumps(artifact)}\n\n")
        if state.mode in {"before_output", "during_output", "during_artifacts", "missing"}:
            return reference
        if state.mode in {"failed", "raised"}:
            journal.finish(2, "failed")
        else:
            journal.finish(2, "completed")
        return reference

    async def replay(request, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        state.replay_attempts += 1
        if state.mode in {"missing", "retry"} and (state.mode == "missing" or state.replay_attempts == 1):
            async def truncated():
                if request.after_event_id is None:
                    yield f"id: {request.run_id}:1\n{CHUNK}"
            return StreamingResponse(truncated(), media_type="text/event-stream")
        state.entered.set()
        return await resume.resume_run(request, ACTOR)

    async def stop(request, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        journal = wire(request)
        result = await resume.stop_run(request, ACTOR)
        stopped = journal.run_state(request_stop=True)
        if stopped and stopped[2]:
            # The controlled producer observes the same scoped Redis stop marker.
            # Stop remains durable even while the producer is settling artifacts.
            journal.repair_terminal("stopped")
        return result

    client = SimpleNamespace(
        start_prepared_run=start, resume=replay, stop_run=stop,
        inspect_run=lambda request, user_id, tenant_id: resume.inspect_run(request, ACTOR),
        acknowledge_projection=lambda request, user_id, tenant_id: resume.acknowledge_projection(request, ACTOR),
    )
    monkeypatch.setattr(runner, "prepare_conversation_snapshot", prepare)
    monkeypatch.setattr(background, "prepare_conversation_snapshot", prepare)
    monkeypatch.setattr(runner, "validate_bindings_available", AsyncMock(return_value={"available": True}))
    monkeypatch.setattr(runner, "forward_active_run", AsyncMock(return_value=None))
    monkeypatch.setattr(runner, "forward_scoped_stop", stop)
    monkeypatch.setattr(runner, "_agentos_client", lambda: client)
    monkeypatch.setattr(runtime_client, "_agentos_client", lambda: client)
    return state


def assert_identity(store, result, *, assistant=True):
    own = {row["message_id"]: row for row in store.rows(ConversationMessage)
           if row["message_source"] == "AUTOMATION"}
    assert own[result["user_message_id"]]["message_role"] == "user"
    if assistant:
        assert own[result["assistant_message_id"]]["message_role"] == "assistant"
    else:
        assert result["assistant_message_id"] is None
    assert set(own) == {result["user_message_id"], result["assistant_message_id"]} - {None}


def latest_run(store):
    return runs.list_runs(store.task["task_id"], ACTOR.tenant_id, ACTOR.user_id)[0]


async def settle(executor, store):
    run = latest_run(store)
    if run["projection_message_index"] is not None:
        await executor.recover_prepared_run(run)
    return latest_run(store)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("completed", "SUCCEEDED"), ("failed", "FAILED"), ("raised", "FAILED"),
    ("preparation_failed", "FAILED"), ("missing", "FAILED"), ("retry", "SUCCEEDED"), ("fallback", "SUCCEEDED"),
])
async def test_stream_result_and_own_message_identity(run_store, runtime, wire, mode, expected):
    runtime.mode = mode
    from management.db.conversation.repository import create_conversation_message
    previous = create_conversation_message(
        dict(conversation_id=1, message_idx=1, role="assistant", content="previous"), ACTOR.user_id,
    )
    executor = runner.AgentAutomationRunner()
    result = await executor.execute_task(run_store.task)
    if mode == "missing":
        assert result["status"] == "RUNNING" and result["assistant_message_id"] is None
        runtime.mode = "failed"
        wire(runtime.reference).finish(2, "failed")
        result = await settle(executor, run_store)
    assert result["status"] == expected
    assert result["assistant_message_id"] != previous
    assert_identity(run_store, result, assistant=mode != "preparation_failed")
    task = runs.get_task(run_store.task["task_id"], ACTOR.tenant_id, ACTOR.user_id)
    assert task["consecutive_failures"] == (0 if expected == "SUCCEEDED" else 1)
    assert task["last_run_status"] == expected
    if mode != "preparation_failed":
        message = next(row for row in run_store.rows(ConversationMessage)
                       if row["message_id"] == result["assistant_message_id"])
        assert message["status"] == ("completed" if expected == "SUCCEEDED" else "failed")
        assert message["message_content"] == ANSWER
    if mode == "retry":
        assert runtime.replay_attempts == 2
    if mode == "fallback":
        assert runtime.preparations == 2 and runtime.admissions == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_output", "during_output", "during_artifacts"])
@pytest.mark.parametrize("terminal", ["TIMEOUT", "CANCELED"])
async def test_timeout_and_cancel_preserve_links_and_settle_output(run_store, runtime, wire, phase, terminal):
    runtime.mode = phase
    executor = runner.AgentAutomationRunner()
    worker = asyncio.create_task(executor.execute_task(run_store.task, trigger_type="MANUAL"))
    await asyncio.wait_for(runtime.entered.wait(), 3)
    if terminal == "CANCELED":
        canceled = await AgentAutomationFacade().cancel_run(latest_run(run_store)["run_id"], ACTOR.tenant_id, ACTOR.user_id)
        assert canceled["status"] == "CANCELED"
    await asyncio.wait_for(worker, 5)
    assert wire(runtime.reference).is_stop_requested()
    result = await settle(executor, run_store)
    assert result["status"] == terminal
    assert_identity(run_store, result)
    assistant = next(row for row in run_store.rows(ConversationMessage)
                     if row["message_id"] == result["assistant_message_id"])
    assert assistant["status"] == "stopped"
    assert (assistant["message_content"] or "") == ("" if phase == "before_output" else ANSWER)
    if phase != "before_output":
        assert any(row["message_id"] == result["assistant_message_id"]
                   for row in run_store.rows(ConversationMessageUnit))
    attachments = json.loads(assistant["minio_files"] or "[]")
    if phase == "during_artifacts":
        assert [item["object_name"] for item in attachments] == [
            f"workspace/{ACTOR.user_id}/{runtime.reference.run_id}/outputs/report.txt"
        ]
    else:
        assert attachments == []
    assert not runs.has_active_run_for_conversation(1, ACTOR.user_id, ACTOR.tenant_id)


@pytest.mark.asyncio
async def test_failed_commit_cannot_be_reported_as_success(run_store, runtime, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("controlled persistence failure")

    executor = runner.AgentAutomationRunner()
    with monkeypatch.context() as fault:
        fault.setattr(prepared_projection, "persist_prepared_assistant_projection", fail)
        result = await executor.execute_task(run_store.task, trigger_type="MANUAL")
        assert result["status"] == "RUNNING" and result["projection_message_index"] is not None
        assert_identity(run_store, result, assistant=False)
    result = await settle(executor, run_store)
    assert result["status"] == "SUCCEEDED"
    assert_identity(run_store, result)


@pytest.mark.asyncio
async def test_next_turn_clears_old_cancel_but_rejects_delayed_stop(run_store, runtime, wire):
    runtime.mode = "during_output"
    executor = runner.AgentAutomationRunner()
    first = await executor.execute_task(run_store.task, trigger_type="MANUAL")
    assert first["status"] == "TIMEOUT"
    first = await settle(executor, run_store)
    old_ref = runtime.reference
    assert wire(old_ref).is_stop_requested()
    runtime.mode = "completed"
    second = await executor.execute_task(run_store.task, trigger_type="MANUAL")
    assert second["status"] == "SUCCEEDED"
    assert second["assistant_message_id"] != first["assistant_message_id"]
    assert runtime.reference.run_id != old_ref.run_id
    await executor.cancel_runtime_run(old_ref.run_id, 1, ACTOR.user_id, ACTOR.tenant_id)
    assert wire(runtime.reference).run_state()[1:] == ("completed", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["cancel_in_preparation", "during_output"])
async def test_user_cancel_returns_http_result_and_preparation_cancel_survives(run_store, runtime, monkeypatch, phase):
    runtime.mode = phase
    monkeypatch.setattr(api, "_get_current_user", lambda _: (ACTOR.user_id, ACTOR.tenant_id))
    app = FastAPI()
    app.include_router(api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.post(f"/agent/automations/{run_store.task['task_id']}/run"))
        try:
            await asyncio.wait_for(runtime.entered.wait(), 3)
            current = latest_run(run_store)
            canceled = await AgentAutomationFacade().cancel_run(current["run_id"], ACTOR.tenant_id, ACTOR.user_id)
            assert canceled["status"] == "CANCELED"
        finally:
            runtime.release.set()
        response = await asyncio.wait_for(request, 5)
    assert response.status_code == 200 and response.json()["data"]["status"] == "CANCELED"
    assert response.json()["data"]["user_message_id"] is not None
    if phase == "cancel_in_preparation":
        assert runtime.admissions == 0
    else:
        await settle(runner.AgentAutomationRunner(), run_store)
    assert not runs.has_active_run_for_conversation(1, ACTOR.user_id, ACTOR.tenant_id)
    runtime.mode = "completed"
    assert (await runner.AgentAutomationRunner().execute_task(run_store.task, trigger_type="MANUAL"))["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_actual_caller_cancellation_still_propagates(run_store, runtime):
    runtime.mode = "during_output"
    executor = runner.AgentAutomationRunner()
    request = asyncio.create_task(executor.execute_task(run_store.task, trigger_type="MANUAL"))
    await asyncio.wait_for(runtime.entered.wait(), 3)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(request, 5)
    current = latest_run(run_store)
    assert current["projection_message_index"] is not None and current["status"] != "SUCCEEDED"


@pytest.mark.asyncio
async def test_regression_detects_reuse_of_a_canceled_run(run_store, runtime, wire):
    executor = runner.AgentAutomationRunner()
    old = AgentRunReference(run_id=uuid4().hex, conversation_id=1)
    journal = wire(old)
    journal.start()
    assert journal.run_state(request_stop=True)[2]
    # Retain the cancel marker while completing a different generation.
    assert (await executor.execute_task(run_store.task, trigger_type="MANUAL"))["status"] == "SUCCEEDED"
    assert journal.is_stop_requested() and not wire(runtime.reference).is_stop_requested()
