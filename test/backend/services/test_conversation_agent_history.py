# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent history service identity and delegation contracts."""

from unittest.mock import Mock

import pytest
from management.services.conversation import agent_history as service


@pytest.mark.parametrize("user,tenant", [("", "tenant"), ("owner", "")])
def test_groups_require_authenticated_identity(monkeypatch, user, tenant):
    query = Mock()
    monkeypatch.setattr(service, "get_agent_conversation_group_page", query)
    with pytest.raises(ValueError, match="Authenticated user and tenant"):
        service.list_agent_groups(user, tenant)
    query.assert_not_called()


@pytest.mark.parametrize("function,args,target", [
    (service.list_agent_group_conversations, ("", "agent:7"), "get_agent_group_conversation_page"),
    (service.list_agent_group_conversation_ids, ("", 7), "list_agent_conversation_ids"),
])
def test_group_operations_reject_missing_user(monkeypatch, function, args, target):
    query = Mock()
    monkeypatch.setattr(service, target, query)
    with pytest.raises(ValueError, match="Authenticated user"):
        function(*args)
    query.assert_not_called()


def test_services_forward_scope_and_return_database_results(monkeypatch):
    groups = Mock(return_value={"items": []})
    conversations = Mock(return_value={"items": []})
    ids = Mock(return_value=[41, 42])
    monkeypatch.setattr(service, "get_agent_conversation_group_page", groups)
    monkeypatch.setattr(service, "get_agent_group_conversation_page", conversations)
    monkeypatch.setattr(service, "list_agent_conversation_ids", ids)
    assert service.list_agent_groups("owner", "tenant", 10, "cursor", "budget", [7], True) == {"items": []}
    groups.assert_called_once_with("owner", "tenant", 10, "cursor", "budget", [7], True)
    assert service.list_agent_group_conversations("owner", "agent:7", 10, "cursor", "budget") == {"items": []}
    conversations.assert_called_once_with("owner", "agent:7", 10, "cursor", "budget")
    assert service.list_agent_group_conversation_ids("owner", 7) == {"items": [41, 42]}
    ids.assert_called_once_with("owner", 7)
