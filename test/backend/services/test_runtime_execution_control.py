# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agent import NL2SkillRunRequest, SystemAgentRef
from contracts.errors.exceptions import ForbiddenError
from management.services.conversation import creator_execution, creator_runtime

RUN_ID = "a" * 32


def stream_snapshot(*entries):
    return {
        "generation": RUN_ID,
        "terminal_status": None,
        "message_id": 100,
        "checkpoint": {"entries": entries, "cursor": "1-0", "generation": RUN_ID} if entries else None,
    }


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
    monkeypatch.setattr(creator_execution, "get_owned_execution", AsyncMock(return_value=(RUN_ID, "running", "nl2skill_main")))
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
    monkeypatch.setattr(creator_runtime, "get_owned_execution", AsyncMock(return_value=(RUN_ID, "running", "nl2skill_main")))
    monkeypatch.setattr(creator_runtime, "get_message_units", lookup)
    monkeypatch.setattr(creator_runtime, "run_blocking", blocking)
    monkeypatch.setattr(creator_runtime, "checkpoint_creator_message", mutate)

    frames = [json.loads(frame[6:]) async for frame in creator_runtime.resume_owned_creator(
        91, "owner", "tenant", RUN_ID, stream_snapshot(first), 100, agent_scope="nl2skill_main",
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
