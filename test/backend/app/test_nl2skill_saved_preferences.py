# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill creation retains saved preferences and explicit request selection."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from contracts.agent import NL2SkillRunRequest
from management.api.skill import creation
from management.services.conversation import creator_execution, model_preferences


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, 77])
async def test_existing_skill_history_restores_preferences_before_stream(monkeypatch, explicit):
    async def inline(_task, function, *args, **kwargs):
        return function(*args)

    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    read_preferences = Mock(return_value={
        "selected_model_id": 42, "model_parameter_preferences": preferences,
    })
    monkeypatch.setattr(model_preferences, "read_model_preferences", read_preferences)
    monkeypatch.setattr("nexent.core.concurrency.run_blocking", inline)
    monkeypatch.setattr(creation, "run_blocking", inline)
    monkeypatch.setattr(creation, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(creator_execution.system_agent_provider, "get_creator_ref",
                        Mock(return_value=SimpleNamespace(agent_id=99, version_no=1)))
    monkeypatch.setattr(creator_execution, "get_conversation_history", Mock(return_value={"agent_id": 99}))

    payload = Mock()
    prepare_snapshot = Mock(return_value=payload)
    prepare_history = Mock(return_value=(11, 0))
    monkeypatch.setattr(creation, "prepare_nl2skill_snapshot", prepare_snapshot)
    monkeypatch.setattr(creator_execution, "prepare_creation_history", prepare_history)
    monkeypatch.setattr(creator_execution, "persist_creation_stream", lambda value, **kwargs: value)

    async def events():
        yield 'data: {"type": "done", "content": ""}\n\n'

    dispatch = Mock(return_value=events())
    monkeypatch.setattr(creation, "create_nl2skill_stream", dispatch)
    request = NL2SkillRunRequest(query="fixture", conversation_id=11, model_id=explicit, persist_history=True)
    response = await creation.nl2skill_run_api(request, authorization="token")

    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks and any('"done"' in chunk for chunk in chunks)
    read_preferences.assert_called_once_with(11, "owner")
    effective = prepare_snapshot.call_args.args[0]
    assert effective is not request
    assert effective.model_id == (42 if explicit is None else explicit)
    assert effective.__dict__["_runtime_model_parameter_preferences"] == preferences
    dispatch.assert_called_once_with(payload.model_copy.return_value, "owner", "tenant")
    assert prepare_history.call_args.kwargs["selected_model_id"] == effective.model_id
    assert prepare_history.call_args.kwargs.get("model_parameter_preferences", {}) == {}
    assert response.headers["conversation_id"] == "11"
