# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator history uses the same saved selection and canonical preferences."""

import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest
from test.backend.app import test_agent_app as legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, 77])
async def test_existing_creator_history_restores_preferences_before_stream(monkeypatch, explicit):
    module = sys.modules[legacy.nl2agent_run_api.__module__]
    monkeypatch.setattr(module, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(module, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    service = types.ModuleType("management.services.conversation.model_preferences")
    service.read_model_preferences = Mock(return_value={"selected_model_id": 42, "model_parameter_preferences": preferences})
    monkeypatch.setitem(sys.modules, service.__name__, service)
    from nexent.core import concurrency
    from management.services.conversation import creator_execution as execution
    monkeypatch.setattr(concurrency, "run_blocking", AsyncMock(side_effect=lambda name, fn, *args: fn(*args)))
    monkeypatch.setattr(execution.system_agent_provider, "get_creator_ref", Mock(return_value=types.SimpleNamespace(agent_id=99)))
    monkeypatch.setattr(execution, "get_conversation_history", Mock(return_value={"agent_id": 99}))
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)

    async def events():
        yield "data: done\n\n"

    stream = AsyncMock(return_value=events())
    prepare = Mock(return_value=(11, 0))
    monkeypatch.setattr(module, "create_nl2agent_stream", stream)
    monkeypatch.setattr(execution, "prepare_creation_history", prepare)
    monkeypatch.setattr(execution, "persist_creation_stream", lambda value, **kwargs: value)
    request = legacy.NL2AgentRunRequest(query="fixture", agent_id=7, conversation_id=11,
                                      model_id=explicit, persist_history=True)
    response = await module.nl2agent_run_api(request, Mock(), authorization="token")
    assert [chunk async for chunk in response.body_iterator] == ["data: done\n\n"]
    service.read_model_preferences.assert_called_once_with(11, "owner")
    effective = stream.call_args.kwargs["request"]
    assert effective is not request
    assert effective.model_id == (42 if explicit is None else explicit)
    assert effective.__dict__["_runtime_model_parameter_preferences"] == preferences
    assert prepare.call_args.kwargs["selected_model_id"] == effective.model_id
    assert prepare.call_args.kwargs.get("model_parameter_preferences", {}) == {}
    assert response.headers["conversation_id"] == "11"
