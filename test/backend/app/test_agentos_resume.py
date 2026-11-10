# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from contracts.agentos import AgentResume, AgentRunReference
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.redis.agent_events import RunJournal
from runtime.agentos import resume

RUN_ID = "a" * 32
ACTOR = ServicePrincipal("actor", "tenant")


@pytest.mark.asyncio
async def test_signed_inspect_supports_owned_terminal_message_reference(mocker):
    import httpx
    from fastapi import FastAPI

    from contracts.agentos import AgentMessageRunLookup, AgentOperation
    from contracts.constants import environment
    from contracts.errors.exceptions import RuntimeUpstreamError
    from management.clients.agentos import AgentOSClient
    from runtime.agentos.middleware import AgentOSMiddleware

    def read(conversation_id, assistant_message_id, user_id, tenant_id):
        assert (conversation_id, assistant_message_id) == (42, 61)
        if (user_id, tenant_id) != (ACTOR.user_id, ACTOR.tenant_id):
            raise PermissionError
        return RUN_ID, {
            "conversation_id": 42, "assistant_message_id": 61, "status": "failed",
            "cancellation_requested": False,
        }

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-inspect-terminal-key")
    mocker.patch.object(resume, "_control_io", side_effect=control_io)
    lookup = mocker.patch.object(resume, "read_terminal_execution_for_message", side_effect=read)
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(resume.create_run_lifecycle_router())
    transport = httpx.ASGITransport(app=app)
    agentos = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs))
    message = AgentMessageRunLookup(conversation_id=42, assistant_message_id=61)

    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        response = await client.post(f"/api{AgentOperation.INSPECT.value}", json=message.model_dump())
        assert response.status_code == 401
    lookup.assert_not_called()

    result = await agentos.inspect_run(message, ACTOR.user_id, ACTOR.tenant_id)
    assert (result.run_id, result.conversation_id, result.assistant_message_id, result.status) == (RUN_ID, 42, 61, "failed")
    with pytest.raises(RuntimeUpstreamError) as denied:
        await agentos.inspect_run(message, ACTOR.user_id, "other")
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_standard_stop_dispatches_signed_debug_id_without_conversation_scope(mocker):
    import httpx
    from fastapi import FastAPI

    from contracts.agentos import AgentOperation
    from contracts.constants import environment
    from infrastructure.agentos_identity import sign_call
    from management.clients.agentos import AgentOSClient
    from runtime.agentos import debug
    from runtime.agentos.middleware import AgentOSMiddleware

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-debug-stop-key")
    stopped = {"status": "success", "message": "stopped"}
    cancel = mocker.patch.object(debug, "stop_agentos_debug", return_value=stopped)
    persisted = mocker.patch.object(resume, "read_execution")
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(resume.create_run_lifecycle_router())
    transport = httpx.ASGITransport(app=app)
    agentos = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs))
    debug_id = f"debug-{RUN_ID}"
    assert await agentos.stop_debug_run(debug_id, ACTOR.user_id, ACTOR.tenant_id) == stopped
    cancel.assert_awaited_once_with(debug_id, ACTOR)
    persisted.assert_not_called()

    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        path = f"/api{AgentOperation.STOP.value}"
        unsigned = await client.post(path, json={"run_id": debug_id})
        assert unsigned.status_code == 401
        for invalid in ('"conversation_id":42', '"prevent_start":true'):
            body = f'{{"run_id":"{debug_id}",{invalid}}}'.encode()
            token = sign_call(AgentOperation.STOP, body, ACTOR)
            result = await client.post(path, content=body, headers={"Authorization": f"Bearer {token}"})
            assert result.status_code == 422
    cancel.assert_awaited_once()
    persisted.assert_not_called()


@pytest.fixture
def journal(mocker):
    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(resume, "_control_io", side_effect=control_io)
    mocker.patch.object(resume, "conversation_belongs_to", return_value=True)
    mocker.patch.object(resume, "read_execution", return_value=None)
    mocker.patch.object(resume, "runtime_state_service", MagicMock(enabled=True))
    return mocker.patch.object(resume, "RunJournal").return_value


@pytest.mark.asyncio
async def test_resume_replays_after_cursor_then_follows(journal):
    journal.replay.return_value = (
        [("1-0", {"kind": "chunk", "data": "data: before\n\n"})],
        [("2-0", {"kind": "chunk", "data": "data: replay\n\n"})],
        [("2-0", {"kind": "chunk", "data": "data: replay\n\n"})],
    )
    journal.wait.return_value = [("3-0", {"kind": "terminal", "status": "completed"})]
    result = await resume.resume_run(
        AgentResume(conversation_id=42, run_id=RUN_ID, after_event_id=f"{RUN_ID}:1"), ACTOR,
    )
    assert [part async for part in result.body_iterator] == [
        f"id: {RUN_ID}:2\ndata: replay\n\n",
        f'id: {RUN_ID}:3\nevent: agentos_terminal\ndata: {{"status": "completed"}}\n\n',
    ]
    journal.replay.assert_called_once_with("1-0")
    journal.wait.assert_called_once_with("2-0")
    resume.conversation_belongs_to.assert_called_once_with(42, user_id="actor", tenant_id="tenant")


@pytest.mark.asyncio
async def test_replay_count_excludes_the_terminal_frame(journal):
    first = ("1-0", {"kind": "chunk", "data": "data: answer\n\n"})
    terminal = ("2-0", {"kind": "terminal", "status": "completed"})
    journal.replay.return_value = ([("0-1", {"kind": "start"})], [first, terminal], [terminal])

    result = await resume.resume_run(AgentResume(conversation_id=42, run_id=RUN_ID), ACTOR)

    assert result.headers["X-AgentOS-Replay-Count"] == "1"
    assert len([part async for part in result.body_iterator]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("owned", "after", "status", "code"), [
    (False, None, 404, "AGENTOS_RUN_NOT_FOUND"),
    (True, f"{'b' * 32}:1", 409, "AGENTOS_CURSOR_RUN_MISMATCH"),
    (True, f"{RUN_ID}:1", 410, "AGENTOS_CURSOR_UNAVAILABLE"),
])
async def test_resume_rejects_invalid_scope_or_cursor(journal, owned, after, status, code):
    resume.conversation_belongs_to.return_value = owned
    journal.replay.return_value = ([], [], [("5-0", {"kind": "terminal", "status": "failed"})])
    with pytest.raises(HTTPException) as exc:
        await resume.resume_run(AgentResume(conversation_id=42, run_id=RUN_ID, after_event_id=after), ACTOR)
    assert exc.value.status_code == status
    assert exc.value.detail == {"code": code}
    if status != 410:
        journal.replay.assert_not_called()
    journal.wait.assert_not_called()


def test_journal_key_binds_all_scope_fields():
    first = RunJournal("tenant", "user", 42, RUN_ID)
    assert len({
        first.key,
        RunJournal("other", "user", 42, RUN_ID).key,
        RunJournal("tenant", "other", 42, RUN_ID).key,
        RunJournal("tenant", "user", 43, RUN_ID).key,
        RunJournal("tenant", "user", 42, "b" * 32).key,
    }) == 5


@pytest.mark.asyncio
async def test_legacy_channel_records_complete_sse_frames(mocker):
    from management.services.agent import channels

    async def control_io(_task, function, *args, **_kwargs):
        return function(*args)

    mocker.patch.object(channels, "run_blocking", side_effect=control_io)
    mocker.patch.object(channels, "runtime_state_service", MagicMock(append_stream_event_async=AsyncMock()))
    journal = mocker.patch.object(channels, "RunJournal").return_value
    journal.run_id = RUN_ID
    channel = channels.StreamingChannel(42, "actor")

    assert await channel.start_journal("tenant", RUN_ID) == RUN_ID
    await channel.publish("event: stream_status\n")
    journal.append.assert_not_called()
    await channel.publish("data: payload\n\n")
    journal.append.assert_called_once_with(1, "event: stream_status\ndata: payload\n\n")
    await channel.finish_journal("completed")
    await channel.finish_journal("completed")
    journal.finish.assert_called_once_with(2, "completed")


@pytest.mark.asyncio
async def test_legacy_channel_marks_gap_and_keeps_serving_when_journal_fails(mocker):
    from management.services.agent import channels

    async def control_io(_task, function, *args, **_kwargs):
        return function(*args)

    mocker.patch.object(channels, "run_blocking", side_effect=control_io)
    legacy_append = AsyncMock()
    mocker.patch.object(channels, "runtime_state_service", MagicMock(append_stream_event_async=legacy_append))
    journal = mocker.patch.object(channels, "RunJournal").return_value
    journal.run_id = RUN_ID
    journal.append.side_effect = ConnectionError("event store disconnected")
    channel = channels.StreamingChannel(42, "actor")

    await channel.start_journal("tenant", RUN_ID)
    await channel.publish("data: first\n\n")
    await channel.publish("data: second\n\n")
    await channel.finish_journal("completed")

    assert legacy_append.await_count == 2
    journal.append.assert_called_once_with(1, "data: first\n\n")
    journal.finish.assert_called_once_with(3, "completed")


@pytest.mark.asyncio
@pytest.mark.parametrize(("request_stop", "tail", "status", "cursor", "requested"), [
    (False, ("0-1", "starting", False), "starting", None, False),
    (True, ("7-0", "running", True), "running", f"{RUN_ID}:7", True),
    (True, ("8-0", "completed", False), "completed", f"{RUN_ID}:8", False),
])
async def test_run_state_returns_status_and_exact_cursor(journal, request_stop, tail, status, cursor, requested):
    journal.run_state.return_value = tail
    payload = AgentRunReference(conversation_id=42, run_id=RUN_ID)
    result = await resume.run_state(payload, ACTOR, request_stop=request_stop)

    assert (result.run_id, result.status, result.latest_event_id, result.cancellation_requested) == (
        RUN_ID, status, cursor, requested,
    )
    resume.RunJournal.assert_called_once_with("tenant", "actor", 42, RUN_ID)
    journal.run_state.assert_called_once_with(request_stop=request_stop)


@pytest.mark.asyncio
@pytest.mark.parametrize(("owned", "enabled", "error", "status", "code"), [
    (False, True, None, 404, "AGENTOS_RUN_NOT_FOUND"),
    (True, True, None, 404, "AGENTOS_RUN_NOT_FOUND"),
    (True, False, None, 503, "AGENTOS_EVENT_STORE_UNAVAILABLE"),
    (True, True, ConnectionError("Redis disconnected"), 503, "AGENTOS_EVENT_STORE_UNAVAILABLE"),
])
async def test_stop_denial_has_no_conversation_wide_fallback(journal, owned, enabled, error, status, code):
    resume.conversation_belongs_to.return_value = owned
    resume.runtime_state_service.enabled = enabled
    journal.run_state.side_effect = error
    journal.run_state.return_value = None

    with pytest.raises(HTTPException) as exc:
        await resume.run_state(AgentRunReference(conversation_id=42, run_id=RUN_ID), ACTOR, request_stop=True)
    assert (exc.value.status_code, exc.value.detail) == (status, {"code": code})
    assert journal.run_state.call_count == int(owned and enabled)
    resume.runtime_state_service.set_cancel_signal.assert_not_called()


@pytest.mark.asyncio
async def test_durable_status_returns_resolved_versions_without_redis(journal):
    from contracts.agentos import AgentRunLookup

    resume.runtime_state_service.enabled = False
    resume.read_execution.return_value = {
        "conversation_id": 42, "status": "completed", "assistant_message_id": 97,
        "cancellation_requested": False,
        "resource_versions": {"agent_id": 9, "agent_version_no": 3, "model_id": 8, "model_revision": "2026-11-10"},
    }

    result = await resume.run_state(AgentRunLookup(run_id=RUN_ID), ACTOR)

    assert (result.conversation_id, result.status, result.latest_event_id, result.assistant_message_id) == (
        42, "completed", None, 97,
    )
    assert result.resource_versions.agent_version_no == 3
    assert result.resource_versions.model_revision == "2026-11-10"
    resume.read_execution.assert_called_once_with(RUN_ID, "actor", "tenant", None, request_stop=False, prevent_start=False)
    journal.run_state.assert_not_called()
