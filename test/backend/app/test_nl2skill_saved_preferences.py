# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill creation retains saved preferences and explicit request selection."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test.backend.app import test_skill_app as legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, 77])
async def test_existing_skill_history_restores_preferences_before_stream(monkeypatch, explicit):
    module = legacy.skill_app_creation
    monkeypatch.setattr(module, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(module, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    service = types.ModuleType("management.services.conversation.model_preferences")
    service.read_model_preferences = Mock(return_value={"selected_model_id": 42, "model_parameter_preferences": preferences})
    monkeypatch.setitem(sys.modules, service.__name__, service)
    from nexent.core import concurrency
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("_skill_preferences_creation", Path(__file__).parents[3] / "backend/management/services/conversation/creator_execution.py")
    execution = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(execution)
    monkeypatch.setattr(module, "start_creation_turn", execution.start_creation_turn)
    monkeypatch.setattr(concurrency, "run_blocking", AsyncMock(side_effect=lambda name, fn, *args: fn(*args)))
    monkeypatch.setattr(execution.system_agent_provider, "get_creator_ref", Mock(return_value=types.SimpleNamespace(agent_id=99)))
    monkeypatch.setattr(execution, "get_conversation_history", Mock(return_value={"agent_id": 99}))
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)

    async def events():
        yield "data: done\n\n"

    stream = AsyncMock(return_value=events())
    prepare = Mock(return_value=(11, 0))
    monkeypatch.setattr(module, "create_nl2skill_stream", stream)
    monkeypatch.setattr(execution, "prepare_creation_history", prepare)
    monkeypatch.setattr(execution, "persist_creation_stream", lambda value, **kwargs: value)
    from contracts.agent import NL2SkillRunRequest
    request = NL2SkillRunRequest(query="fixture", conversation_id=11, model_id=explicit, persist_history=True)
    response = await module.nl2skill_run_api(request, authorization="token")
    assert [chunk async for chunk in response.body_iterator] == ["data: done\n\n"]
    service.read_model_preferences.assert_called_once_with(11, "owner")
    effective = stream.call_args.kwargs["request"]
    assert effective is not request
    assert effective.model_id == (42 if explicit is None else explicit)
    assert effective.__dict__["_runtime_model_parameter_preferences"] == preferences
    assert prepare.call_args.kwargs["selected_model_id"] == effective.model_id
    assert prepare.call_args.kwargs.get("model_parameter_preferences", {}) == {}
    assert response.headers["conversation_id"] == "11"
