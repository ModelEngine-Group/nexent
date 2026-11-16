# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing Agent turns restore saved controls before selection or writes."""

import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest
from test.backend.services import test_agent_service as legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit,unsaved", [(None, False), (77, False), (None, True)])
async def test_saved_controls_precede_validation_and_new_drafts_are_rejected(monkeypatch, explicit, unsaved):
    from contracts.errors.exceptions import RunModelControlsError
    from management.services.model import run_controls
    module = legacy.agent_subscription
    request = legacy.AgentRequest(agent_id=7, query="fixture", conversation_id=11, model_id=explicit)
    if unsaved:
        # Internal callers can mutate an already validated DTO's dictionary.
        request.model_parameter_preferences["42"] = {"temperature": 0.4}
    monkeypatch.setattr(module, "_resolve_user_tenant_language", lambda **kwargs: ("owner", "tenant", "en"))
    monkeypatch.setattr(module, "prepend_current_time", lambda query, *args, **kwargs: query)
    lookup = Mock(return_value={})
    monkeypatch.setattr(module, "get_conversation_service", lookup)
    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    service = types.ModuleType("management.services.conversation.model_preferences")
    service.read_model_preferences = Mock(return_value={"selected_model_id": 42, "model_parameter_preferences": preferences})
    monkeypatch.setitem(sys.modules, service.__name__, service)
    monkeypatch.setattr(module, "run_blocking", AsyncMock(side_effect=lambda name, fn, *args: fn(*args)))
    selection = Mock(side_effect=None if unsaved else RunModelControlsError("model_controls_invalid"))
    monkeypatch.setattr(run_controls, "validate_agent_model_selection", selection)
    write = Mock(side_effect=AssertionError("Preflight must precede writes"))
    monkeypatch.setattr(module, "create_new_conversation", write)
    monkeypatch.setattr(module, "save_messages", write)
    expected = module.ValidationError if unsaved else RunModelControlsError
    with pytest.raises(expected):
        await module.run_agent_stream(request, Mock(), user_id="owner", tenant_id="tenant")
    lookup.assert_called_once_with(conversation_id=11, user_id="owner", tenant_id="tenant")
    service.read_model_preferences.assert_called_once_with(11, "owner")
    assert request.model_id == (42 if explicit is None else explicit)
    assert request.__dict__["_runtime_model_parameter_preferences"] == preferences
    selection.assert_called_once_with(request, "tenant", module.search_agent_info_by_agent_id)
    write.assert_not_called()
