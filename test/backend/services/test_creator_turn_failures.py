# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rejected creator turns never leak a stream or rebind another owner's history."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.agent import NL2AgentRunRequest, SystemAgentRef
from management.services.conversation import creation_history, creator_execution, creator_targets


@pytest.fixture
def target_binding(mocker):
    target = {"type": "agent", "id": 201}
    mocker.patch.object(creator_targets, "authorize_target", return_value=target)
    mocker.patch.object(creator_targets.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef(
        "shared", "nl2agent_main", 77, 0,
    ))
    return target


@pytest.mark.parametrize("history", [None, {"agent_id": 88}])
def test_binding_rejects_missing_or_wrong_executor_history(mocker, target_binding, history):
    mocker.patch.object(creator_targets, "get_conversation_history", return_value=history)
    write = mocker.patch.object(creator_targets, "bind_creation_conversation_target")
    with pytest.raises(ValueError, match="does not belong"):
        creator_targets.bind_creator_target(9, target_binding, "user", "tenant")
    write.assert_not_called()


def test_binding_same_target_is_idempotent(mocker, target_binding):
    mocker.patch.object(creator_targets, "get_conversation_history", return_value={"agent_id": 77, "target": target_binding})
    write = mocker.patch.object(creator_targets, "bind_creation_conversation_target")
    assert creator_targets.bind_creator_target(9, target_binding, "user", "tenant") == target_binding
    write.assert_not_called()


def test_binding_reports_compare_and_set_conflict(mocker, target_binding):
    mocker.patch.object(creator_targets, "get_conversation_history", return_value={"agent_id": 77, "target": None})
    write = mocker.patch.object(creator_targets, "bind_creation_conversation_target", return_value=False)
    with pytest.raises(ValueError, match="changed concurrently"):
        creator_targets.bind_creator_target(9, target_binding, "user", "tenant")
    write.assert_called_once_with(9, 77, None, target_binding, "user")


@pytest.mark.asyncio
async def test_turn_rejects_target_for_different_creator_before_runtime_or_history(mocker):
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef(
        "shared", "nl2agent_main", 77, 0,
    ))
    prepare = mocker.patch.object(creator_execution, "prepare_creation_history")
    factory = AsyncMock()
    with pytest.raises(ValueError, match="does not match executor"):
        await creator_execution.start_creation_turn(
            NL2AgentRunRequest(query="edit", target={"type": "skill", "id": 201}),
            kind="agent", user_id="user", tenant_id="tenant", stream_factory=factory,
        )
    factory.assert_not_called()
    prepare.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("history rejected"), KeyboardInterrupt()])
async def test_failed_history_preparation_closes_built_stream(mocker, failure):
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef(
        "shared", "nl2agent_main", 77, 0,
    ))
    mocker.patch.object(creator_execution, "authorize_target", side_effect=lambda target, *_: target)
    mocker.patch.object(creator_execution, "prepare_creation_history", side_effect=failure)
    stream = MagicMock(aclose=AsyncMock())
    factory = AsyncMock(return_value=stream)
    with pytest.raises(type(failure)) as caught:
        await creator_execution.start_creation_turn(
            NL2AgentRunRequest(query="edit", agent_id=201), kind="agent",
            user_id="user", tenant_id="tenant", stream_factory=factory,
        )
    assert caught.value is failure
    stream.aclose.assert_awaited_once_with()


@pytest.mark.parametrize("retry", [{"retry_user_message_id": 10}, {"retry_message_index": 0}])
def test_retry_cannot_change_existing_target(mocker, retry):
    mocker.patch.object(creation_history, "get_conversation_history", return_value={
        "agent_id": 77, "target": {"type": "agent", "id": 200},
    })
    bind = mocker.patch.object(creation_history, "bind_creator_target")
    save = mocker.patch.object(creation_history, "save_message")
    with pytest.raises(ValueError, match="Cannot change a creation retry target"):
        creation_history.prepare_creation_history(
            conversation_id=9, mode="agent_create", query="retry", minio_files=None,
            workbench_config=None, agent_id=77, target={"type": "agent", "id": 201},
            user_id="user", tenant_id="tenant", **retry,
        )
    bind.assert_not_called()
    save.assert_not_called()
