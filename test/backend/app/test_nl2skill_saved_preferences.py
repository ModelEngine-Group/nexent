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
    monkeypatch.setattr(module, "get_current_user_id", Mock(return_value=("owner", "tenant")))
    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    service = types.ModuleType("management.services.conversation.model_preferences")
    service.read_model_preferences = Mock(return_value={"selected_model_id": 42, "model_parameter_preferences": preferences})
    monkeypatch.setitem(sys.modules, service.__name__, service)
    monkeypatch.setattr(module, "run_blocking", AsyncMock(side_effect=lambda name, fn, *args: fn(*args)))

    async def events():
        yield "data: done\n\n"

    stream = AsyncMock(return_value=events())
    prepare = Mock(return_value=(11, 0))
    monkeypatch.setattr(module, "create_nl2skill_stream", stream)
    monkeypatch.setattr(module, "prepare_creation_history", prepare)
    monkeypatch.setattr(module, "persist_creation_stream", lambda value, **kwargs: value)
    request = SimpleNamespace(query="fixture", conversation_id=11, model_id=explicit, persist_history=True,
        workbench_config=None, language=None, minio_files=[], model_parameter_preferences={},
        retry_user_message_id=None, retry_message_index=None)
    response = await module.nl2skill_run_api(request, authorization="token")
    assert [chunk async for chunk in response.body_iterator] == ["data: done\n\n"]
    service.read_model_preferences.assert_called_once_with(11, "owner")
    assert stream.call_args.kwargs["request"] is request
    assert request.model_id == (42 if explicit is None else explicit)
    assert request.__dict__["_runtime_model_parameter_preferences"] == preferences
    assert prepare.call_args.kwargs["selected_model_id"] == request.model_id
    assert prepare.call_args.kwargs["model_parameter_preferences"] == {}
    assert response.headers["conversation_id"] == "11"
