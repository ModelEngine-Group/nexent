# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator admission rejects stale cards and releases unsuccessful preparations."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest, SystemAgentRef
from management.services.conversation import creator_execution as execution
from test.common.creator_runtime_boundary import isolate_creator_runtime


@pytest.fixture
def turn(monkeypatch, mocker):
    boundary = isolate_creator_runtime(monkeypatch, execution)
    history = {"agent_id": 77, "target": {"type": "agent", "id": 42}, "message_records": []}
    read = mocker.patch.object(execution, "get_conversation_history", return_value=history)
    mocker.patch.object(execution.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef(
        "shared", "nl2agent_main", 77, 0,
    ))
    authorize = mocker.patch.object(execution, "authorize_target", side_effect=lambda target, *_: target)
    prepare = mocker.patch.object(execution, "prepare_creation_history", return_value=(91, 1))
    update = mocker.patch.object(execution, "update_message_status")
    release = mocker.patch.object(execution.agent_run_manager, "release_agent_run_reservation")
    mocker.patch("management.services.conversation.model_preferences.read_model_preferences", return_value={
        "model_parameter_preferences": {"9": {"temperature": 0.3}}, "selected_model_id": 9,
    })
    stream = MagicMock(aclose=AsyncMock())
    return SimpleNamespace(
        control=boundary.control, save=boundary.save, checkpoint=boundary.checkpoint,
        launch=boundary.launch, history=history,
        read=read, authorize=authorize, prepare=prepare, update=update, release=release,
        stream=stream, factory=AsyncMock(return_value=stream),
    )


async def start(turn, request=None, **kwargs):
    request = request or NL2AgentRunRequest(query="build", conversation_id=91, agent_id=42)
    return await execution.start_creation_turn(
        request, kind="agent", user_id="owner", tenant_id="tenant", stream_factory=turn.factory, **kwargs,
    )


@pytest.mark.parametrize("query", [None, "not-json", "[]", '{"type":"other"}', '{"type":"nl2agent_card_action"}'])
def test_non_card_queries_do_not_require_a_card_origin(query):
    assert execution.validate_creator_card_action({}, query) is None


def card(card_id="2:0", **overrides):
    return {"card_id": card_id, "agent_id": 42, "subtype": "requirement_clarification", **overrides}


@pytest.mark.parametrize("changed", [{}, {"card_id": "old"}, {"agent_id": 43}, {"subtype": "agent_draft"}])
def test_card_actions_must_match_the_latest_assistant_identity(changed):
    history = {"message_records": [
        {"message_id": 1, "role": "assistant", "units": [{"unit_type": "nl2a", "unit_content": json.dumps(card("old"))}]},
        {"message_id": 2, "role": "assistant", "units": [{"unit_type": "nl2a", "unit_content": json.dumps(card())}]},
    ]}
    action = {"type": "nl2agent_card_action", **card(**changed)}
    if not changed:
        assert execution.validate_creator_card_action(history, json.dumps(action)) is None
    else:
        with pytest.raises(ValueError, match="stale or does not belong"):
            execution.validate_creator_card_action(history, json.dumps(action))


def test_card_action_without_an_origin_is_rejected():
    with pytest.raises(ValueError, match="no originating answer"):
        execution.validate_creator_card_action({}, json.dumps({"type": "nl2agent_card_action", **card()}))


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [None, {"agent_id": 88}])
async def test_other_executor_history_is_rejected_before_preparation(turn, history):
    turn.read.return_value = history
    with pytest.raises(ValueError, match="does not belong"):
        await start(turn)
    turn.factory.assert_not_awaited()
    turn.prepare.assert_not_called()


@pytest.mark.asyncio
async def test_resume_cannot_change_the_owned_target(turn):
    with pytest.raises(ValueError, match="Resume target does not match"):
        await start(turn, NL2AgentRunRequest(query="resume", conversation_id=91, agent_id=43), resume=True)
    turn.authorize.assert_not_called()
    turn.factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_creation_requires_a_target_before_reserving_any_worker(turn):
    with pytest.raises(ValueError, match="requires an editable Agent target"):
        await start(turn, NL2AgentRunRequest(query="build"))
    execution.claim_creator.assert_not_awaited()


@pytest.mark.asyncio
async def test_skill_resume_requires_an_existing_conversation(turn):
    with pytest.raises(ValueError, match="Resume requires a creator conversation"):
        await execution.start_creation_turn(
            NL2SkillRunRequest(query="resume"), kind="skill", user_id="owner", tenant_id="tenant",
            stream_factory=turn.factory, resume=True,
        )
    turn.factory.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [False, True])
async def test_resume_attaches_to_the_existing_generation_without_admission(turn, mocker, local):
    execution.runtime_state_service.get_run_state_async = AsyncMock(return_value={"generation": "shared"})
    info = SimpleNamespace(_automation_runtime_generation="local") if local else None
    mocker.patch.object(execution.agent_run_manager, "get_agent_run_info", return_value=info)
    attach = mocker.patch.object(execution, "resume_creator", new_callable=AsyncMock, return_value=turn.stream)
    request = NL2AgentRunRequest(query="resume", conversation_id=91, agent_id=42)
    stream, conversation_id = await start(turn, request, resume=True)
    assert conversation_id == 91 and request.__dict__["_creator_generation"] == ("local" if local else "shared")
    attach.assert_awaited_once_with(91, "owner")
    turn.factory.assert_not_awaited()
    turn.save.assert_not_called()
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [None, 8])
async def test_retry_uses_the_original_user_boundary_and_saved_model_preferences(turn, selected):
    turn.history["message_records"] = [
        {"message_id": 5, "message_index": 0, "role": "user", "message_content": "original"},
        {"message_id": 6, "message_index": 1, "role": "assistant", "message_content": "partial", "status": "streaming"},
    ]
    stream, _ = await start(turn, NL2AgentRunRequest(
        query="retry", conversation_id=91, agent_id=42, retry_user_message_id=5, model_id=selected,
    ))
    effective = turn.factory.call_args.args[0]
    assert effective.history == []
    assert effective.model_id == (9 if selected is None else selected)
    assert effective.__dict__["_runtime_model_parameter_preferences"] == {"9": {"temperature": 0.3}}
    turn.update.assert_called_once_with(6, "failed", "owner")
    assert turn.prepare.call_args.kwargs["retry_user_message_id"] == 5
    await stream.aclose()


@pytest.mark.asyncio
async def test_failure_after_message_creation_keeps_the_request_fence_and_marks_failed(turn):
    turn.launch.side_effect = RuntimeError("launch rejected")
    request = NL2AgentRunRequest(query="build", conversation_id=91, agent_id=42, request_id="request")
    with pytest.raises(RuntimeError, match="launch rejected"):
        await start(turn, request)
    turn.update.assert_called_once_with(101, "failed", "owner")
    turn.stream.aclose.assert_awaited_once()
    turn.control.cancel.assert_called_once()
    turn.release.assert_called_once_with(91, "owner", "reservation")
    execution.release_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_preparation_releases_the_request_fence_and_its_heartbeat(turn):
    guard = asyncio.create_task(asyncio.Event().wait())
    turn.control.guard_preparation.return_value = guard
    turn.prepare.side_effect = ValueError("history rejected")
    request = NL2AgentRunRequest(query="build", conversation_id=91, agent_id=42, request_id="request")
    with pytest.raises(ValueError, match="history rejected"):
        await start(turn, request)
    assert guard.cancelled()
    execution.release_request.assert_awaited_once_with("creator-request:tenant:owner:request")
    turn.stream.aclose.assert_awaited_once()
    turn.save.assert_not_called()

