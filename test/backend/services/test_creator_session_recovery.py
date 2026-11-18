# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creator ownership, incremental persistence and reconnect boundaries."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest, SystemAgentRef
from management.services.conversation import creator_checkpoints as checkpoints
from management.services.conversation import creator_execution as execution
from management.services.conversation import creator_runtime as runtime


@pytest.fixture
def store(monkeypatch):
    rows = []
    user = "creator-recovery-test-user"

    def history(cid, uid):
        assert uid == user
        return {
            "agent_id": 77,
            "target": {"type": "agent", "id": 42},
            "message_records": copy.deepcopy(rows),
        }

    def save(request, **kwargs):
        mid = len(rows) + 1
        rows.append(
            {
                "message_id": mid,
                "role": request.role,
                "message_index": request.message_idx,
                "message_content": request.message[0].content
                if request.message
                else "",
                "status": kwargs.get("status", "completed"),
                "units": [],
            }
        )
        return mid

    def checkpoint(mid, cid, uid, units, content, status):
        row = next(r for r in rows if r["message_id"] == mid)
        assert row["status"] == "streaming"
        row["units"].extend(copy.deepcopy(units))
        row.update(status=status, message_content=content)

    monkeypatch.setattr(
        execution.system_agent_provider,
        "get_creator_ref",
        lambda *_: SystemAgentRef("shared", "nl2agent_main", 77, 0),
    )
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)
    monkeypatch.setattr(execution, "get_conversation_history", history)
    monkeypatch.setattr(runtime, "get_conversation_history", history)
    monkeypatch.setattr(execution, "save_message", save)
    monkeypatch.setattr(checkpoints, "checkpoint_creator_message", checkpoint)
    monkeypatch.setattr(runtime, "checkpoint_creator_message", checkpoint)
    monkeypatch.setattr(
        runtime,
        "get_message_units",
        lambda mid: copy.deepcopy(
            next(r["units"] for r in rows if r["message_id"] == mid)
        ),
    )

    def prepare(**kwargs):
        if kwargs.get("retry_message_index") is not None:
            return 91, kwargs["retry_message_index"] + 1
        index = max((r["message_index"] for r in rows), default=-1) + 1
        save(
            SimpleNamespace(
                role="user",
                message_idx=index,
                message=[SimpleNamespace(content=kwargs["query"])],
            )
        )
        return 91, index + 1

    monkeypatch.setattr(execution, "prepare_creation_history", prepare)
    monkeypatch.setattr(
        "management.services.conversation.model_preferences.read_model_preferences",
        lambda *_: {"model_parameter_preferences": {}, "selected_model_id": None},
    )
    state = SimpleNamespace(
        enabled=False,
        claim_creator_run_async=AsyncMock(return_value=True),
        creator_lease_async=AsyncMock(return_value=True),
        is_cancelled_async=AsyncMock(return_value=False),
        get_run_state_async=AsyncMock(return_value={}),
        read_replay_checkpoint_async=AsyncMock(return_value=None),
        mark_stream_completed_async=AsyncMock(),
        _run_managed=AsyncMock(),
    )
    monkeypatch.setattr(runtime, "runtime_state_service", state)
    monkeypatch.setattr(execution, "runtime_state_service", state)
    runtime._request_claims.clear()
    return SimpleNamespace(rows=rows, user=user, state=state)


async def settle():
    if runtime._producers:
        await asyncio.wait_for(asyncio.gather(*runtime._producers), timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
async def test_disconnect_keeps_creator_running_and_reconnect_replays_once(store, kind):
    gate = asyncio.Event()

    async def source():
        yield 'data: {"type":"final_answer","content":"first"}\n\n'
        await gate.wait()
        yield 'data: {"type":"final_answer","content":"second"}\n\n'

    factory = AsyncMock(return_value=source())
    request = (NL2AgentRunRequest if kind == "agent" else NL2SkillRunRequest)(
        query="build", target={"type": kind, "id": 42}
    )
    stream, cid = await execution.start_creation_turn(
        request,
        kind=kind,
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=factory,
    )
    assert store.rows[-1]["status"] == "streaming"
    await anext(stream)
    await stream.aclose()
    assert runtime._producers
    gate.set()
    await settle()
    assert store.rows[-1]["status"] == "completed"
    resumed = await runtime.resume_creator(cid, store.user)
    events = [json.loads(event[6:]) async for event in resumed]
    assert [e["content"] for e in events] == ["first", "second"]
    assert [e["unit_index"] for e in events] == [0, 1]
    assert factory.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_start_cannot_write_another_user_turn(store):
    gate = asyncio.Event()

    async def source():
        await gate.wait()
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    factory = AsyncMock(side_effect=lambda *_: source())
    request = NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42})
    await execution.start_creation_turn(
        request,
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=factory,
    )
    try:
        with pytest.raises(runtime.AgentRunAlreadyActiveError):
            await execution.start_creation_turn(
                request.model_copy(update={"conversation_id": 91}),
                kind="agent",
                user_id=store.user,
                tenant_id="tenant",
                stream_factory=factory,
            )
        assert len(store.rows) == 2
        assert factory.await_count == 1
    finally:
        gate.set()
        await settle()


@pytest.mark.asyncio
async def test_card_checkpoint_has_stable_identity_before_delivery(store):
    payload = {"subtype": "requirement_clarification", "agent_id": 42, "questions": []}

    async def source():
        yield (
            "data: "
            + json.dumps({"type": "nl2a", "content": json.dumps(payload)})
            + "\n\n"
        )

    factory = AsyncMock(return_value=source())
    request = NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42})
    stream, _ = await execution.start_creation_turn(
        request,
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=factory,
    )
    event = json.loads((await anext(stream))[6:])
    assert json.loads(event["content"])["card_id"] == "2:0"
    assert json.loads(store.rows[-1]["units"][0]["unit_content"])["card_id"] == "2:0"
    await stream.aclose()
    await settle()


@pytest.mark.asyncio
async def test_explicit_stop_cancels_an_idle_producer_and_persists_stopped(store):
    gate = asyncio.Event()

    async def source():
        yield 'data: {"type":"final_answer","content":"partial"}\n\n'
        await gate.wait()

    request = NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42})
    stream, _ = await execution.start_creation_turn(
        request,
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=AsyncMock(return_value=source()),
    )
    await anext(stream)
    runtime.agent_run_manager.stop_agent_run(91, store.user)
    await settle()
    assert store.rows[-1]["status"] == "stopped"
    await stream.aclose()


def test_context_preserves_questions_and_retry_discards_later_turns():
    history = {
        "message_records": [
            {
                "role": "assistant",
                "message_index": 1,
                "message_content": "",
                "units": [
                    {
                        "unit_type": "nl2a",
                        "unit_content": '{"questions":[{"title":"Original question"}]}',
                    }
                ],
            },
            {"role": "user", "message_index": 2, "message_content": "answer"},
            {"role": "assistant", "message_index": 3, "message_content": "later"},
        ]
    }
    context = execution.creator_history_context(history, retry_index=2)
    assert len(context) == 1 and "Original question" in context[0].content


@pytest.mark.asyncio
async def test_live_reconnect_tails_without_duplicate_units(store):
    gate = asyncio.Event()

    async def source():
        yield 'data: {"type":"final_answer","content":"first"}\n\n'
        await gate.wait()
        yield 'data: {"type":"final_answer","content":"last"}\n\n'

    stream, cid = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42}),
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=AsyncMock(return_value=source()),
    )
    await anext(stream)
    await stream.aclose()
    resumed = await runtime.resume_creator(cid, store.user)
    events = [json.loads((await anext(resumed))[6:])]
    gate.set()
    events.extend([json.loads(event[6:]) async for event in resumed])
    await settle()
    assert [event["unit_index"] for event in events] == [0, 1]
    assert [event["content"] for event in events] == ["first", "last"]


@pytest.mark.asyncio
async def test_immediate_shutdown_finalizes_the_accepted_turn(store):
    async def source():
        await asyncio.Event().wait()
        yield "unreachable"

    await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42}),
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=AsyncMock(return_value=source()),
    )
    assert await runtime.shutdown_creator_streams(2) == 0
    assert store.rows[-1]["status"] == "stopped"
    assert runtime.agent_run_manager.get_agent_run_info(91, store.user) is None


@pytest.mark.asyncio
async def test_unexpected_producer_failure_is_visible_after_reconnect(store):
    async def source():
        raise RuntimeError("provider detail must not leak")
        yield "unreachable"

    stream, cid = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42}),
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=AsyncMock(return_value=source()),
    )
    await settle()
    await stream.aclose()
    assert store.rows[-1]["status"] == "failed"
    resumed = await runtime.resume_creator(cid, store.user)
    events = [json.loads(event[6:]) async for event in resumed]
    assert events == [
        {
            "type": "error",
            "content": "Creator execution failed.",
            "unit_index": 0,
            "tool_call_id": None,
            "invocation_id": None,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_during_tail", [False, True])
async def test_lost_remote_owner_persists_interruption(store, expires_during_tail):
    store.rows.append(
        {
            "message_id": 2,
            "role": "assistant",
            "message_index": 1,
            "message_content": "partial",
            "status": "streaming",
            "units": [],
        }
    )
    store.state.enabled = True
    store.state.get_run_state_async.return_value = {
        "generation": "old",
        "status": "running",
    }
    store.state.creator_lease_async.side_effect = (
        [True, False] if expires_during_tail else [False]
    )
    store.state.wait_for_stream_events_async = AsyncMock(return_value=[])
    store.state.mark_run_finished = MagicMock()
    resumed = await runtime.resume_creator(91, store.user)
    events = [json.loads(event[6:]) async for event in resumed]
    assert len(events) == 1 and events[0]["type"] == "error"
    assert store.rows[-1]["status"] == "failed"
    assert store.rows[-1]["units"][0]["unit_type"] == "error"


@pytest.mark.asyncio
async def test_preparation_renews_ownership_and_lost_lease_cannot_write_a_turn(store):
    store.state.enabled = True
    store.state.creator_lease_async.side_effect = [True, False]
    store.state.mark_run_finished = MagicMock()

    async def slow_factory(*_):
        await asyncio.Event().wait()

    task = asyncio.create_task(
        execution.start_creation_turn(
            NL2AgentRunRequest(
                query="build", conversation_id=91, target={"type": "agent", "id": 42}
            ),
            kind="agent",
            user_id=store.user,
            tenant_id="tenant",
            stream_factory=slow_factory,
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert store.rows == []
    assert store.state.creator_lease_async.await_count == 2
    reservation = runtime.agent_run_manager.reserve_agent_run(91, store.user)
    runtime.agent_run_manager.release_agent_run_reservation(91, store.user, reservation)


@pytest.mark.asyncio
async def test_duplicate_request_id_does_not_create_another_conversation(store):
    async def source():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    factory = AsyncMock(side_effect=lambda *_: source())
    request = NL2AgentRunRequest(
        query="build", target={"type": "agent", "id": 42}, request_id="same-request"
    )
    await execution.start_creation_turn(
        request,
        kind="agent",
        user_id=store.user,
        tenant_id="tenant",
        stream_factory=factory,
    )
    await settle()
    with pytest.raises(runtime.AgentRunAlreadyActiveError):
        await execution.start_creation_turn(
            request,
            kind="agent",
            user_id=store.user,
            tenant_id="tenant",
            stream_factory=factory,
        )
    assert len(store.rows) == 2 and factory.await_count == 1


@pytest.mark.asyncio
async def test_truncated_local_buffer_recovers_from_the_complete_memory_checkpoint(store, monkeypatch):
    from management.services.agent import channels

    saved = [
        {"unit_type": "final_answer", "unit_index": i, "unit_content": str(i)}
        for i in range(3)
    ]
    store.rows.append(
        {
            "message_id": 2,
            "role": "assistant",
            "message_index": 1,
            "message_content": "0",
            "status": "streaming",
            "units": saved,
        }
    )
    # The raw tail retains only the last token; the complete checkpoint owns recovery.
    database = MagicMock(side_effect=AssertionError("Local recovery must not read database units"))
    monkeypatch.setattr(runtime, "get_message_units", database)
    monkeypatch.setattr(
        channels,
        "runtime_state_service",
        SimpleNamespace(append_stream_event_async=AsyncMock()),
    )
    channel = channels.StreamingChannel("91", store.user, history_size=1)
    for i in range(3):
        await channel.publish(
            "data: "
            + json.dumps({"type": "final_answer", "unit_index": i, "content": str(i)})
            + "\n\n"
        )
    channel.complete("completed")
    monkeypatch.setattr(
        runtime.streaming_channel_manager, "get_channel", lambda *_: channel
    )
    resumed = await runtime.resume_creator(91, store.user)
    events = [json.loads(event[6:]) async for event in resumed]
    assert [event["unit_index"] for event in events] == [0, 1, 2]
    assert [event["content"] for event in events] == ["0", "1", "2"]
    database.assert_not_called()
