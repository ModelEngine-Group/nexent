# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator executor identity, target authorization and single-write history contracts."""

from unittest.mock import AsyncMock

import pytest

from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest, SystemAgentRef
from management.services.conversation import creator_execution as execution
from management.services.conversation import creation_history, creator_targets


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("workbench", [False, True])
async def test_both_entrypoints_save_each_turn_once_with_executor_and_target(mocker, kind, workbench):
    ref = SystemAgentRef("shared", f"nl2{kind}_main", 77, 0)
    mocker.patch.object(execution.system_agent_provider, "get_creator_ref", return_value=ref)
    mocker.patch.object(execution, "authorize_target", side_effect=lambda target, *_: target)
    create = mocker.patch.object(creation_history, "create_new_conversation", return_value={"conversation_id": 9})
    save = mocker.patch.object(creation_history, "save_message", side_effect=[10, 11])
    unit = mocker.patch.object(creation_history, "save_message_unit")
    target = {"type": kind, "id": 201}
    config = {"schema_version": 3, "mode": f"{kind}_create", "agent_mounts": [], "skill_mounts": []} if workbench else None
    request = (NL2AgentRunRequest if kind == "agent" else NL2SkillRunRequest)(
        query="build", target=target, workbench_config=config, persist_history=False,
    )
    async def raw():
        yield 'data: {"type":"string","content":"answer"}\n\n'
    factory = AsyncMock(return_value=raw())
    stream, conversation_id = await execution.start_creation_turn(
        request, kind=kind, user_id="user", tenant_id="tenant", stream_factory=factory,
    )
    events = [event async for event in stream]
    assert conversation_id == 9 and len(events) == 1
    if workbench:
        assert create.call_args.kwargs["workbench_config"]["mode"] == f"{kind}_create"
    else:
        assert create.call_args.kwargs["workbench_config"] is None
    assert create.call_args.kwargs["title"] == ("新对话" if workbench else "build")
    assert create.call_args.kwargs["agent_id"] == 77
    assert create.call_args.kwargs["target"] == target
    assert [call.args[0].role for call in save.call_args_list] == ["user", "assistant"]
    assert unit.call_count == 1
    effective, actor = factory.call_args.args
    assert actor == ref and effective.target.model_dump() == target
    if kind == "agent":
        assert effective.agent_id == 201 and request.agent_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [None, {"agent_id": 88, "target": {"type": "agent", "id": 201}}])
async def test_inaccessible_or_different_executor_history_never_runs_or_writes(mocker, history):
    mocker.patch.object(execution.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef("shared", "nl2agent_main", 77, 0))
    mocker.patch.object(execution, "get_conversation_history", return_value=history)
    prepare = mocker.patch.object(execution, "prepare_creation_history")
    factory = AsyncMock()
    with pytest.raises(ValueError, match="does not belong"):
        await execution.start_creation_turn(NL2AgentRunRequest(query="edit", conversation_id=9), kind="agent", user_id="user", tenant_id="tenant", stream_factory=factory)
    prepare.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("previous,records,allowed", [
    (None, [], True),
    ({"type": "agent", "id": 200}, [{"delete_flag": "Y"}], True),
    ({"type": "agent", "id": 200}, [{"delete_flag": "N"}], False),
    ({"type": "agent", "id": 200}, [], False),
    ({"type": "skill", "id": 200}, [], False),
])
def test_target_binding_cannot_replace_live_or_unowned_resources(mocker, previous, records, allowed):
    target = {"type": "agent", "id": 201}
    mocker.patch.object(creator_targets, "authorize_target", return_value=target)
    mocker.patch.object(creator_targets.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef("shared", "nl2agent_main", 77, 0))
    mocker.patch.object(creator_targets, "get_conversation_history", return_value={"agent_id": 77, "target": previous})
    mocker.patch.object(creator_targets, "query_agent_records_for_nl2agent", return_value=records)
    write = mocker.patch.object(creator_targets, "bind_creation_conversation_target", return_value=True)
    if allowed:
        assert creator_targets.bind_creator_target(9, target, "user", "tenant") == target
        write.assert_called_once_with(9, 77, previous, target, "user")
    else:
        with pytest.raises(ValueError):
            creator_targets.bind_creator_target(9, target, "user", "tenant")
        write.assert_not_called()


@pytest.mark.parametrize("target", [{"type": "agent", "id": True}, {"type": "file", "id": 1}, {"type": "skill", "id": 0}, {"type": "skill", "id": 1, "other": 2}])
def test_target_contract_rejects_ambiguous_values(target):
    from contracts.conversation import ConversationTarget
    with pytest.raises(ValueError):
        ConversationTarget.model_validate(target)


@pytest.mark.parametrize("kind", ["agent", "skill"])
def test_target_authorization_uses_current_tenant_and_edit_permission(mocker, kind):
    target = {"type": kind, "id": 201}
    agent = mocker.patch.object(creator_targets, "require_agent_draft_edit", return_value={"agent_origin": "USER"})
    skill = mocker.patch.object(creator_targets.skill_db, "get_skill_by_id", return_value={"skill_id": 201})
    edit = mocker.patch.object(creator_targets, "_can_edit_skill", return_value=True)
    assert creator_targets.authorize_target(target, "user-a", "tenant-a") == target
    if kind == "agent":
        agent.assert_called_once_with(agent_id=201, tenant_id="tenant-a", user_id="user-a")
        agent.return_value = {"agent_origin": "SYSTEM"}
    else:
        skill.assert_called_once_with(201, "tenant-a")
        edit.assert_called_once_with({"skill_id": 201}, "user-a")
        edit.return_value = False
    with pytest.raises(PermissionError):
        creator_targets.authorize_target(target, "user-a", "tenant-a")


@pytest.mark.asyncio
async def test_resume_derives_target_from_owned_history(mocker):
    ref = SystemAgentRef("shared", "nl2agent_main", 77, 0)
    mocker.patch.object(execution.system_agent_provider, "get_creator_ref", return_value=ref)
    mocker.patch.object(execution, "get_conversation_history", return_value={"agent_id": 77, "target": {"type": "agent", "id": 201}})
    authorize = mocker.patch.object(execution, "authorize_target", side_effect=lambda target, *_: target)
    prepare = mocker.patch.object(execution, "prepare_creation_history", return_value=(9, 3))
    async def raw():
        if False:
            yield ""
    factory = AsyncMock(return_value=raw())
    stream, _ = await execution.start_creation_turn(NL2AgentRunRequest(query="edit", conversation_id=9), kind="agent", user_id="user", tenant_id="tenant", stream_factory=factory)
    authorize.assert_called_once_with({"type": "agent", "id": 201}, "user", "tenant")
    assert prepare.call_args.kwargs["agent_id"] == 77
    assert factory.call_args.args[0].agent_id == 201
    await stream.aclose()
