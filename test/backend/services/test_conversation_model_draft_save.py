# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""First conversation creation keeps the selected model and explicit draft values."""

import sys
from unittest.mock import Mock

import pytest
from test.backend.services import test_conversation_management_service as legacy


@pytest.mark.parametrize("preferences", [{}, {"42": {"temperature": 0, "enable_thinking": False}}])
def test_conversation_creation_forwards_only_present_draft_preferences(monkeypatch, preferences):
    module = sys.modules[legacy.create_new_conversation.__module__]
    create = Mock(return_value={"conversation_id": 11})
    monkeypatch.setattr(module, "create_conversation", create)
    assert module.create_new_conversation("draft", "owner", selected_model_id=42,
        model_parameter_preferences=preferences) == {"conversation_id": 11}
    assert create.call_args.args == ("draft", "owner")
    assert create.call_args.kwargs["selected_model_id"] == 42
    assert create.call_args.kwargs.get("model_parameter_preferences") == (preferences or None)
