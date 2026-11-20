# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import RedisError

from contracts.agent import AgentRequest, NL2SkillRunRequest, SystemAgentRef
from contracts.errors.exceptions import ForbiddenError, RuntimeCoordinationUnavailableError
from management.services.agent import control, execution, run, subscription
from management.services.conversation import creator_execution, creator_runtime


def stream_snapshot(*entries, generation="execution:42", terminal=None, cursor="1-0"):
    return {
        "generation": generation, "terminal_status": terminal, "message_id": 100,
        "checkpoint": {"entries": entries, "cursor": cursor, "generation": generation} if entries else None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [None, (42, "PREPARING", "agent:11"), (42, "RUNNING", "agent:11")])
async def test_stop_reads_identity_scoped_reservation_before_touching_redis(monkeypatch, owned):
    lookup = AsyncMock(return_value=owned)
    signal = AsyncMock(return_value=True)
    monkeypatch.setattr(control, "get_owned_execution", lookup)
    monkeypatch.setattr(control.runtime_state_service, "request_execution_cancel_async", signal)

    result = await control.request_owned_stop("tenant-b", "owner-b", 91)
    lookup.assert_awaited_once_with("tenant-b", "owner-b", 91, active_only=True)
    assert result is (owned is not None)
    if owned is None:
        signal.assert_not_awaited()
    else:
        signal.assert_awaited_once_with("owner-b", 91, 42, None)


@pytest.mark.asyncio
async def test_explicit_generation_never_falls_back_to_an_unscoped_stop(monkeypatch):
    monkeypatch.setattr(control, "get_owned_execution", AsyncMock(return_value=(43, "RUNNING", "nl2skill_main")))
    signal = AsyncMock(return_value=False)
    monkeypatch.setattr(control.runtime_state_service, "request_execution_cancel_async", signal)
    preprocess = Mock()
    monkeypatch.setattr(run.preprocess_manager, "stop_preprocess_tasks", preprocess)

    response = await run.stop_shared_agent_tasks(91, "owner", "tenant", "execution:42")
    assert response["status"] == "success" and response["already_stopped"] is True
    signal.assert_awaited_once_with("owner", 91, 43, "execution:42")
    preprocess.assert_not_called()


@pytest.mark.asyncio
async def test_missing_reservation_cannot_stop_another_users_preprocess(monkeypatch):
    monkeypatch.setattr(run, "request_owned_stop", AsyncMock(return_value=False))
    owner_check = AsyncMock(return_value=None)
    monkeypatch.setattr(run, "run_blocking", owner_check)
    preprocess = Mock()
    monkeypatch.setattr(run.preprocess_manager, "stop_preprocess_tasks", preprocess)

    response = await run.stop_shared_agent_tasks(91, "other", "tenant")
    assert response["already_stopped"] is True
    assert owner_check.await_args.args[2:] == (91, "other", "tenant")
    preprocess.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_stop_dependency_fault_is_not_reported_as_already_stopped(monkeypatch, internal):
    from runtime.api.agent import execution as route

    monkeypatch.setattr(route, "uses_durable_agent_admission", lambda: True)
    monkeypatch.setattr(route, "verify_internal_runtime_jwt", lambda *_: ("owner", "tenant"))
    monkeypatch.setattr(route, "get_current_user_id", lambda *_: ("owner", "tenant"))
    monkeypatch.setattr(control, "get_owned_execution", AsyncMock(return_value=(42, "RUNNING", "agent:11")))
    signal = AsyncMock(side_effect=RedisError("coordination down"))
    monkeypatch.setattr(control.runtime_state_service, "request_execution_cancel_async", signal)

    if internal:
        response = await route.northbound_agent_stop_api(91, "token")
    else:
        response = await route.agent_stop_api("91", "token", "execution:42")
    assert response.status_code == 503
    assert json.loads(response.body)["code"] == "RUNTIME_COORDINATION_UNAVAILABLE"
    assert signal.await_args.args[:3] == ("owner", 91, 42)


@pytest.mark.asyncio
async def test_producer_polls_only_its_execution_and_legacy_occurrence(monkeypatch):
    state = SimpleNamespace(is_execution_cancelled_async=AsyncMock(return_value=True), is_cancelled_async=AsyncMock())
    monkeypatch.setattr(execution, "runtime_state_service", state)
    scope = Mock()
    event = asyncio.Event()
    await execution._poll_runtime_cancel_signal(
        91, "owner", event, scope, reservation=SimpleNamespace(execution_id=42), generation="17",
    )
    assert event.is_set()
    scope.cancel.assert_called_once()
    state.is_execution_cancelled_async.assert_awaited_once_with("owner", 91, 42, "17")
    state.is_cancelled_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("readiness", [None, {"incomplete": True}])
async def test_missing_replay_does_not_conclude_or_mutate_active_run(monkeypatch, readiness):
    monkeypatch.setattr(subscription, "get_owned_execution", AsyncMock(return_value=(42, "RUNNING", "agent:11")))
    monkeypatch.setattr(subscription, "read_owned_stream", AsyncMock(return_value=readiness))
    mutate = Mock()
    monkeypatch.setattr(subscription, "update_message_status", mutate)
    response = await subscription._resume_owned_agent_stream(91, "owner", "tenant")
    payload = json.loads(response.body)
    assert payload["status"] == "streaming" and payload["replay_unavailable"] is True
    mutate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped", None])
async def test_resume_consumes_only_matching_terminal_snapshot_and_no_duplicate_prefix(monkeypatch, outcome):
    first = {"type": "final_answer", "content": "first"}
    final = {**first, "content": "first second"}
    terminal = stream_snapshot(final, terminal=outcome, cursor="2-0") if outcome else None
    state = SimpleNamespace(
        wait_for_stream_events_async=AsyncMock(),
        read_execution_stream_async=AsyncMock(return_value=terminal),
    )
    lookup = AsyncMock(side_effect=[
        (42, "RUNNING", "agent:11"), (42, "RUNNING", "agent:11"), (43, "RUNNING", "agent:11"),
    ])
    monkeypatch.setattr(subscription, "get_owned_execution", lookup)
    monkeypatch.setattr(subscription, "read_owned_stream", AsyncMock(return_value=stream_snapshot(first)))
    monkeypatch.setattr(subscription, "runtime_state_service", state)
    monkeypatch.setattr(subscription, "_detect_resume_position", Mock(return_value={"resume_from_unit_index": 0}))

    response = await subscription._resume_owned_agent_stream(91, "owner", "tenant")
    output = [json.loads(frame[6:]) async for frame in response.body_iterator if frame.startswith("data: ")]
    assert [frame["content"] for frame in output if frame.get("type") == "final_answer"] == (
        ["first", " second"] if outcome else ["first"]
    )
    assert output[-1]["status"] == (outcome or "stopped")
    assert bool(output[-1].get("replay_unavailable")) is (outcome is None)
    state.read_execution_stream_async.assert_awaited_once_with("owner", 91, 42)


@pytest.mark.asyncio
async def test_old_cursor_replays_only_unicode_suffix_with_repeatable_event_id(monkeypatch):
    answer = {"type": "final_answer", "content": "前😀后半", "unit_index": 0}
    snapshot = stream_snapshot(answer, terminal="completed")
    monkeypatch.setattr(subscription, "get_owned_execution", AsyncMock(return_value=(42, "COMPLETED", "agent:11")))
    monkeypatch.setattr(subscription, "read_owned_stream", AsyncMock(return_value=snapshot))
    read_unit = AsyncMock(return_value=None)
    monkeypatch.setattr(subscription, "run_blocking", read_unit)

    for _attempt in range(2):
        response = await subscription._resume_owned_agent_stream(
            91, "owner", "tenant", replay_cursor="execution:42:1:2", resume_message_id=100,
        )
        assert response.headers["conversation_id"] == "91"
        output = "".join([frame async for frame in response.body_iterator])
        events = [json.loads(line[6:]) for line in output.splitlines() if line.startswith("data: ")]
        assert [event["content"] for event in events if event.get("type") == "final_answer"] == ["后半"]
        assert output.count("id: execution:42:1:4\n") == 1
        assert events[-1]["status"] == "completed"
    assert all(call.args[-1] == 100 for call in read_unit.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor,message_id,read_shared", [
    ("execution:41:1:1", 100, False),
    ("malformed", 100, False),
    ("execution:42:1:999", 100, True),
    ("execution:42:2:1", 100, True),
    (None, 99, True),
])
async def test_stale_or_missing_replay_never_follows_another_answer(monkeypatch, cursor, message_id, read_shared):
    shared = AsyncMock(return_value=stream_snapshot({"type": "final_answer", "content": "current"}))
    monkeypatch.setattr(subscription, "get_owned_execution", AsyncMock(return_value=(42, "RUNNING", "agent:11")))
    monkeypatch.setattr(subscription, "read_owned_stream", shared)
    monkeypatch.setattr(subscription, "get_last_unit_for_message", Mock(side_effect=AssertionError("unrelated history")))

    result = await subscription._resume_owned_agent_stream(
        91, "owner", "tenant", replay_cursor=cursor, resume_message_id=message_id,
    )
    assert json.loads(result.body)["replay_unavailable"] is True
    assert shared.await_count == int(read_shared)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_cursor_request_is_read_only_and_checks_conversation_before_redis(monkeypatch, authorized):
    monkeypatch.setattr(subscription, "uses_durable_agent_admission", lambda: True)
    owner = Mock(return_value={"conversation_id": 91} if authorized else None)
    monkeypatch.setattr(subscription, "get_conversation_service", owner)
    resume = AsyncMock(return_value=Mock())
    producer = Mock(side_effect=AssertionError("must not start another run"))
    monkeypatch.setattr(subscription, "_resume_owned_agent_stream", resume)
    monkeypatch.setattr(subscription, "generate_stream", producer)
    request = AgentRequest(conversation_id=91, query="", replay_cursor="execution:42:1:2")

    if authorized:
        assert await subscription.run_agent_stream(request, None, "owner", "tenant") is resume.return_value
        resume.assert_awaited_once_with(91, "owner", "tenant", replay_cursor=request.replay_cursor,
                                       resume_message_id=None, stream_cursor=False)
    else:
        with pytest.raises(ForbiddenError):
            await subscription.run_agent_stream(request, None, "owner", "tenant")
        resume.assert_not_awaited()
    owner.assert_called_once_with(conversation_id=91, user_id="owner", tenant_id="tenant")
    producer.assert_not_called()


@pytest.mark.asyncio
async def test_creator_history_pin_never_switches_to_new_assistant(monkeypatch):
    async def blocking(_name, function, *args):
        return function(*args)

    monkeypatch.setattr(creator_execution, "uses_durable_agent_admission", lambda: True)
    monkeypatch.setattr(creator_execution, "run_blocking", blocking)
    monkeypatch.setattr(creator_execution, "get_conversation_service", Mock(return_value={"conversation_id": 91}))
    monkeypatch.setattr(creator_execution, "_read_creator_history", Mock(return_value={}))
    monkeypatch.setattr(creator_execution, "_creator_target", Mock())
    monkeypatch.setattr(creator_execution.system_agent_provider, "get_creator_ref", Mock(return_value=Mock(agent_id=11)))
    monkeypatch.setattr(creator_execution, "get_owned_execution", AsyncMock(return_value=(42, "RUNNING", "nl2skill_main")))
    monkeypatch.setattr(creator_execution, "read_owned_stream", AsyncMock(return_value=stream_snapshot()))
    subscriber = Mock()
    monkeypatch.setattr(creator_execution, "resume_owned_creator", subscriber)

    stream, conversation_id = await creator_execution.start_creation_turn(
        NL2SkillRunRequest(query="Resume", conversation_id=91, resume_message_id=99), kind="skill",
        user_id="owner", tenant_id="tenant", stream_factory=AsyncMock(),
    )
    assert conversation_id == 91
    assert '"replay_unavailable":true' in "".join([frame async for frame in stream])
    subscriber.assert_not_called()


@pytest.mark.asyncio
async def test_creator_lease_loss_uses_pinned_history_without_recovering_owner(monkeypatch):
    first = {"type": "string", "content": "first", "unit_index": 0}
    latest = {"unit_type": "string", "unit_content": "second", "unit_index": 1}
    mutate = Mock()
    state = SimpleNamespace(
        creator_lease_async=AsyncMock(return_value=False),
        read_execution_stream_async=AsyncMock(return_value=None),
        wait_for_stream_events_async=AsyncMock(),
    )
    async def blocking(_name, function, *args):
        return function(*args)

    lookup = Mock(return_value=[{"unit_type": "string", "unit_content": "first", "unit_index": 0}, latest])
    monkeypatch.setattr(creator_runtime, "runtime_state_service", state)
    monkeypatch.setattr(creator_runtime, "get_owned_execution", AsyncMock(return_value=(42, "RUNNING", "nl2skill_main")))
    monkeypatch.setattr(creator_runtime, "get_message_units", lookup)
    monkeypatch.setattr(creator_runtime, "run_blocking", blocking)
    monkeypatch.setattr(creator_runtime, "checkpoint_creator_message", mutate)

    frames = [json.loads(frame[6:]) async for frame in creator_runtime.resume_owned_creator(
        91, "owner", "tenant", 42, stream_snapshot(first), 100,
    )]
    assert [frame["content"] for frame in frames[:2]] == ["first", "second"]
    assert frames[-1]["type"] == "error"
    lookup.assert_called_once_with(100)
    mutate.assert_not_called()
    state.wait_for_stream_events_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_creator_resume_checks_conversation_owner_before_shared_state(monkeypatch):
    monkeypatch.setattr(creator_execution, "uses_durable_agent_admission", lambda: True)
    monkeypatch.setattr(creator_execution.system_agent_provider, "get_creator_ref", Mock(
        return_value=SystemAgentRef("shared", "nl2skill_main", 77, 0),
    ))
    monkeypatch.setattr(creator_execution, "run_blocking", AsyncMock(return_value=None))
    owner_lookup = AsyncMock()
    monkeypatch.setattr(creator_execution, "get_owned_execution", owner_lookup)
    shared = AsyncMock()
    monkeypatch.setattr(creator_execution, "read_owned_stream", shared)

    with pytest.raises(ForbiddenError):
        await creator_execution.start_creation_turn(
            NL2SkillRunRequest(query="resume", conversation_id=91), kind="skill", user_id="other", tenant_id="tenant",
            stream_factory=AsyncMock(), resume=True,
        )

    owner_lookup.assert_not_awaited()
    shared.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_stop_does_not_write_after_postgres_failure(monkeypatch):
    monkeypatch.setattr(control, "get_owned_execution", AsyncMock(side_effect=RuntimeCoordinationUnavailableError()))
    signal = AsyncMock()
    monkeypatch.setattr(control.runtime_state_service, "request_execution_cancel_async", signal)
    with pytest.raises(RuntimeCoordinationUnavailableError):
        await control.request_owned_stop("tenant", "owner", 91)
    signal.assert_not_awaited()
