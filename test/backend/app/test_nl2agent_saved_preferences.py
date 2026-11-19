# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator history uses the saved selection and canonical preferences."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test.common.creator_runtime_boundary import isolate_creator_runtime

from contracts.agent import NL2AgentRunRequest
from infrastructure.agentos_identity import ServicePrincipal
from management.api.agent import creator
from management.services.conversation import creator_execution, model_preferences


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, 77])
async def test_existing_creator_history_restores_preferences_before_stream(monkeypatch, explicit):
    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    read_preferences = Mock(return_value={
        "selected_model_id": 42, "model_parameter_preferences": preferences,
    })
    monkeypatch.setattr(model_preferences, "read_model_preferences", read_preferences)
    monkeypatch.setattr("nexent.core.concurrency.run_blocking", inline)
    monkeypatch.setattr(creator, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(creator, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(creator_execution.system_agent_provider, "get_creator_ref",
                        Mock(return_value=SimpleNamespace(agent_id=99, version_no=1)))
    monkeypatch.setattr(creator_execution, "get_conversation_history", Mock(return_value={"agent_id": 99}))
    monkeypatch.setattr(creator_execution, "authorize_target", lambda target, *_: target)

    payload = Mock()
    prepare_snapshot = AsyncMock(return_value=payload)
    prepare_history = Mock(return_value=(11, 0))
    monkeypatch.setattr(creator, "prepare_nl2agent_snapshot", prepare_snapshot)
    monkeypatch.setattr(creator_execution, "prepare_creation_history", prepare_history)
    runtime = isolate_creator_runtime(monkeypatch, creator_execution)

    async def events():
        yield 'data: {"type": "done", "content": ""}\n\n'

    dispatch = Mock(return_value=events())
    monkeypatch.setattr(creator, "create_nl2agent_stream", dispatch)
    request = NL2AgentRunRequest(query="fixture", agent_id=7, conversation_id=11,
                                model_id=explicit, persist_history=True)
    response = await creator.nl2agent_run_api(request, Mock(), authorization="token")

    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks and any('"done"' in chunk for chunk in chunks)
    read_preferences.assert_called_once_with(11, "owner")
    effective, actor, language = prepare_snapshot.await_args.args
    assert effective is not request
    assert effective.model_id == (42 if explicit is None else explicit)
    assert effective.__dict__["_runtime_model_parameter_preferences"] == preferences
    assert actor == ServicePrincipal("owner", "tenant")
    assert language == "en"
    dispatch.assert_called_once_with(payload.model_copy.return_value, actor)
    assert prepare_history.call_args.kwargs["selected_model_id"] == effective.model_id
    assert prepare_history.call_args.kwargs.get("model_parameter_preferences", {}) == {}
    assert response.headers["conversation_id"] == "11"
    runtime.control.admit.assert_awaited_once()
    runtime.checkpoint.assert_called_once()
    runtime.launch.assert_awaited_once()
