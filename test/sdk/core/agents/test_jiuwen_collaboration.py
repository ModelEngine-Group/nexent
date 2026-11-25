# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.types import StreamResponse
from google.protobuf.json_format import ParseDict
from jsonschema import ValidationError
from openjiuwen.core.foundation.tool import ToolCard
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent import AgentCard
from openjiuwen.core.single_agent.ability_manager import AbilityManager

from nexent.core.agents.cores.jiuwen.a2a import _RemoteResult
from nexent.core.agents.cores.jiuwen.collaboration import (
    CollaborationAgent,
    _CollaborationAbilityManager,
    collaboration_dispatch,
    create_collaboration_host,
    remove_run_abilities,
)
from nexent.core.agents.cores.jiuwen.resources import JiuwenResourceBridge
from nexent.core.concurrency import RunCancellationScope


@pytest.fixture
def delegate():
    schema = {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"],
              "additionalProperties": False}
    return CollaborationAgent(AgentCard(id="native-delegate", name="delegate", input_params=schema), "owned",
                              AsyncMock(return_value="result"))


@pytest.mark.asyncio
async def test_native_agent_checks_parent_session_and_rejects_hidden_arguments():
    execute = AsyncMock(return_value="result")
    schema = {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"],
              "additionalProperties": False}
    agent = CollaborationAgent(AgentCard(id="id", name="delegate", input_params=schema), "owned", execute)
    owner = SimpleNamespace(get_session_id=lambda: "owned:call")
    stranger = SimpleNamespace(get_session_id=lambda: "other:call")

    with pytest.raises(PermissionError):
        await agent.invoke({"task": "delegate"}, session=stranger)
    with pytest.raises(PermissionError, match="dispatch identity"):
        await agent.invoke({"task": "delegate"}, session=owner)
    with collaboration_dispatch("owned:other", "other"):
        with pytest.raises(PermissionError, match="dispatch identity"):
            await agent.invoke({"task": "delegate"}, session=owner)

    with collaboration_dispatch("owned:call", "call"):
        with pytest.raises(ValidationError):
            await agent.invoke({"task": "delegate", "provider_call_id": "spoof"}, session=owner)
    execute.assert_not_awaited()

    with collaboration_dispatch("owned:call", "call"):
        assert await agent.invoke({"task": "delegate", "conversation_id": "owned:call"}, session=owner) == "result"
    execute.assert_awaited_once_with({"task": "delegate"}, provider_call_id="call")


@pytest.mark.asyncio
async def test_native_collaborator_dispatch_rejects_missing_call_id(mocker):
    manager = _CollaborationAbilityManager("owned")
    manager.collaborators["delegate"] = object()
    tool_call = SimpleNamespace(name="delegate", id="")
    execute = mocker.patch(
        "openjiuwen.core.single_agent.ability_manager.AbilityManager._execute_single_tool_call",
    )
    with pytest.raises(PermissionError, match="call ID is missing"):
        await manager._execute_single_tool_call(tool_call, None)
    execute.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.asyncio
async def test_native_dispatch_binds_each_identical_call_and_releases_child_on_exit(delegate, mocker, failure):
    manager = _CollaborationAbilityManager("owned")
    manager.collaborators[delegate.card.name] = ToolCard(name=delegate.card.name, parallel_safe=True)
    parent = SimpleNamespace(get_session_id=lambda: "owned")
    release = mocker.patch.object(Runner, "release", new_callable=AsyncMock)
    if failure:
        delegate.execute.side_effect = RuntimeError("child failed")

    async def framework_dispatch(_manager, call, session, tag, context):
        child = SimpleNamespace(get_session_id=lambda: f"{session.get_session_id()}:{call.id}")
        assert tag == "tag" and context == "context"
        await asyncio.sleep(0)
        return await delegate.invoke({"task": "same"}, session=child)

    mocker.patch.object(AbilityManager, "_execute_single_tool_call", new=framework_dispatch)
    calls = [SimpleNamespace(name="delegate", id=call_id) for call_id in ("id-a", "id-b")]
    results = await asyncio.gather(
        *(manager._execute_single_tool_call(call, parent, "tag", "context") for call in calls),
        return_exceptions=True,
    )
    if failure:
        assert [str(error) for error in results] == ["child failed", "child failed"]
    else:
        assert results == ["result", "result"]
    assert {call.kwargs["provider_call_id"] for call in delegate.execute.await_args_list} == {"id-a", "id-b"}
    assert all(call.args == ({"task": "same"},) for call in delegate.execute.await_args_list)
    assert sorted(call.args[0] for call in release.await_args_list) == ["owned:id-a", "owned:id-b"]
    with pytest.raises(PermissionError, match="dispatch identity"):
        await delegate.invoke({"task": "same"}, SimpleNamespace(get_session_id=lambda: "owned:id-a"))


@pytest.mark.asyncio
async def test_native_scheduler_preserves_tool_dispatch_and_parallel_policy(delegate, mocker):
    manager = _CollaborationAbilityManager("owned")
    registered = mocker.patch.object(Runner.resource_mgr, "add_agent")
    registered.return_value.is_err.return_value = False
    manager.add_collaborator(delegate, parallel_safe=True)
    card, constructor = registered.call_args.args
    assert card is delegate.card and constructor() is delegate
    assert manager.get("delegate") is delegate.card
    with pytest.raises(ValueError, match="Duplicate"):
        manager.add_collaborator(delegate, parallel_safe=False)
    assert registered.call_count == 1

    framework_batch = mocker.patch.object(AbilityManager, "_execute_parallel_tool_tasks", new_callable=AsyncMock)
    framework_dispatch = mocker.patch.object(AbilityManager, "_execute_single_tool_call", new_callable=AsyncMock)
    upload = ToolCard(name="upload", parallel_safe=False)
    calls, tasks, hook = [object()], [object()], Mock()
    result = await manager._execute_parallel_tool_tasks(calls, tasks, {"upload": upload}, on_task_started=hook)
    assert result is framework_batch.return_value
    forwarded = framework_batch.await_args
    assert forwarded.args[:2] == (calls, tasks) and forwarded.kwargs == {"on_task_started": hook}
    assert forwarded.args[2]["upload"] is upload
    assert forwarded.args[2]["delegate"].parallel_safe is True
    call = SimpleNamespace(name="upload", id=None)
    assert await manager._execute_single_tool_call(call, "session") is framework_dispatch.return_value
    framework_dispatch.assert_awaited_once_with(call, "session", None, None)


def test_registration_failure_propagates_without_adding_a_collaborator(delegate, mocker):
    manager = _CollaborationAbilityManager("owned")
    registered = mocker.patch.object(Runner.resource_mgr, "add_agent")
    registered.return_value.is_err.return_value = True
    registered.return_value.msg.return_value = RuntimeError("registry unavailable")
    with pytest.raises(RuntimeError, match="registry unavailable"):
        manager.add_collaborator(delegate, parallel_safe=True)
    assert not manager.collaborators and manager.get("delegate") is None


def test_collaboration_host_uses_scoped_manager_and_removes_both_resource_types(delegate, mocker):
    from nexent.core.agents.cores.jiuwen import collaboration

    parts = SimpleNamespace(config=SimpleNamespace(card=AgentCard(id="owned", name="parent")))
    resolve = mocker.patch.object(collaboration, "resolve_deep_agent_parts", return_value=parts)
    apply = mocker.patch.object(collaboration, "apply_deep_agent_parts")
    model = object()
    host = create_collaboration_host(model, parallel_tool_calls=True)
    assert isinstance(host.ability_manager, _CollaborationAbilityManager)
    resolve.assert_called_once_with(model, parallel_tool_calls=True)
    apply.assert_called_once_with(host, parts)

    tool = ToolCard(id="owned-tool", name="read")
    host.ability_manager.add(delegate.card)
    host.ability_manager.add(tool)
    remove_agent = mocker.patch.object(Runner.resource_mgr, "remove_agent")
    remove_tool = mocker.patch.object(Runner.resource_mgr, "remove_tool")
    remove_run_abilities(host)
    remove_agent.assert_called_once_with(delegate.card.id)
    remove_tool.assert_called_once_with(tool.id)
    assert not host.ability_manager.list()


@pytest.mark.asyncio
async def test_python_binding_uses_unique_authorized_agent_sessions_and_releases_failures(delegate, mocker):
    scope = RunCancellationScope()
    manager = Mock()
    manager.list.return_value = [delegate.card, AgentCard(id="hidden", name="hidden")]
    bridge = JiuwenResourceBridge(SimpleNamespace(ability_manager=manager), asyncio.get_running_loop(), scope,
                                  {"delegate"}, "owned")
    release = mocker.patch.object(Runner, "release", new_callable=AsyncMock)
    delegate.execute.side_effect = ["result", RuntimeError("child failed")]

    async def run(card_id, inputs, *, session):
        assert card_id == delegate.card.id
        child_session = SimpleNamespace(get_session_id=lambda: session)
        return [value async for value in delegate.stream(inputs, session=child_session)]

    framework = mocker.patch.object(Runner, "run_agent", side_effect=run)
    bindings = bridge.bindings()
    assert set(bindings) == {"delegate"}
    with pytest.raises(ValidationError):
        bindings["delegate"]("same", provider_call_id="forged")
    framework.assert_not_awaited()
    assert await asyncio.to_thread(bindings["delegate"], "same") == ["result"]
    with pytest.raises(RuntimeError, match="child failed"):
        await asyncio.to_thread(bindings["delegate"], "same")
    sessions = [call.kwargs["session"] for call in framework.await_args_list]
    assert len(set(sessions)) == 2 and all(session.startswith("owned:") for session in sessions)
    assert [call.args[0] for call in release.await_args_list] == sessions
    assert all(call.kwargs["provider_call_id"] is None for call in delegate.execute.await_args_list)
    assert not scope._closers


def test_native_a2a_artifact_updates_merge_by_id_and_require_completion():
    result = _RemoteResult()

    def artifact(text, append=False):
        return {"artifactUpdate": {"taskId": "task", "append": append,
                                   "artifact": {"artifactId": "artifact", "parts": [{"text": text}]}}}

    for data in (artifact("discarded"), artifact("first"), artifact(" second", append=True)):
        result.accept(ParseDict(data, StreamResponse()))
    with pytest.raises(RuntimeError, match="did not complete"):
        result.answer()
    wrong_task = ParseDict({"statusUpdate": {"taskId": "other", "status": {
        "state": "TASK_STATE_COMPLETED",
    }}}, StreamResponse())
    with pytest.raises(ValueError, match="switched task IDs"):
        result.accept(wrong_task)
    result.accept(ParseDict({"statusUpdate": {"taskId": "task", "status": {
        "state": "TASK_STATE_COMPLETED", "message": {"parts": [{"text": "duplicate fallback"}]},
    }}}, StreamResponse()))
    assert result.task_id == "task" and result.answer() == "first second"


@pytest.mark.parametrize("state", ["FAILED", "CANCELED", "INPUT_REQUIRED"])
def test_native_a2a_terminal_error_does_not_publish_partial_text(state):
    result = _RemoteResult()
    result.accept(ParseDict({"task": {"id": "task", "status": {"state": "TASK_STATE_" + state},
        "artifacts": [{"artifactId": "discard", "parts": [{"text": "partial"}]}]}}, StreamResponse()))
    with pytest.raises(RuntimeError, match="did not complete"):
        result.answer()
