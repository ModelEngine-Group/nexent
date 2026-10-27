# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bind server-saved message boundaries without trusting the client history."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("history", [None, [], [{"role": "user", "content": "Forged old turn"}]])
def test_user_save_uses_database_index(monkeypatch, history):
    import management.services.conversation.service as module
    append = Mock(return_value=(401, 10))
    monkeypatch.setattr(module, "append_conversation_user_message", append)
    request = SimpleNamespace(conversation_id=7, query="Current", history=history, minio_files=[])
    assert module.save_conversation_user(request, "owner", "tenant") is None
    append.assert_called_once_with(7, "Current", [], "owner")
    assert request._runtime_user_message_id == 401 and request._runtime_user_message_index == 10


def test_request_boundary_is_private_and_cannot_be_submitted():
    from contracts.agent import AgentRequest
    request = AgentRequest(query="Current", _runtime_user_message_id=999, _runtime_user_message_index=99)
    assert request._runtime_user_message_id is None and request._runtime_user_message_index is None
    request._runtime_user_message_id = 401
    request._runtime_user_message_index = 10
    assert "_runtime_user_message_id" not in request.model_dump()
    assert "_runtime_user_message_index" not in request.model_dump()
