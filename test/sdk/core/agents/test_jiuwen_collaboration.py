# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from a2a.types import StreamResponse
from google.protobuf.json_format import ParseDict
from jsonschema import ValidationError
from nexent.core.agents.cores.jiuwen.a2a import _RemoteResult
from nexent.core.agents.cores.jiuwen.collaboration import (
    CollaborationAgent,
    _CollaborationAbilityManager,
    collaboration_dispatch,
)
from openjiuwen.core.single_agent import AgentCard


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
