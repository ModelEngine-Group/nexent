# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from consts.exceptions import ConversationNotFoundError, ValidationError
from management.services.conversation.service import (
    update_conversation_knowledge_scope_service,
)


SCOPE = {
    "schema_version": 1,
    "local": {"mode": "override", "knowledge_ids": ["12"]},
    "aidp": {"mode": "disabled", "kds_ids": []},
}


@patch("management.services.conversation.service.update_conversation_knowledge_scope")
@patch("management.services.conversation.service._resolve_knowledge_scope_for_update")
@patch("management.services.conversation.service.get_conversation")
def test_update_returns_effective_preview_and_warnings(
    mock_get_conversation, mock_resolve, mock_update
):
    mock_get_conversation.return_value = {"conversation_id": 1, "agent_id": 7}
    mock_resolve.return_value = SimpleNamespace(
        warnings=[{
            "code": "KNOWLEDGE_SCOPE_CAPABILITY_UNSUPPORTED",
            "source": "aidp",
            "count": 1,
        }],
        local_disabled=False,
        local_knowledge_ids=["12"],
        local_display_names=["Local KB"],
        aidp_disabled=True,
        aidp_kds_ids=[],
        aidp_display_names=[],
    )
    mock_update.return_value = True

    result = update_conversation_knowledge_scope_service(
        conversation_id=1,
        knowledge_scope=SCOPE,
        user_id="user",
        tenant_id="tenant",
    )

    assert result["desired_scope"] == SCOPE
    assert result["effective_preview"]["local"]["knowledge_ids"] == ["12"]
    assert result["warnings"][0]["source"] == "aidp"
    mock_update.assert_called_once_with(
        conversation_id=1,
        knowledge_scope=SCOPE,
        user_id="user",
    )


@patch("management.services.conversation.service.update_conversation_knowledge_scope")
@patch("management.services.conversation.service._resolve_knowledge_scope_for_update")
@patch("management.services.conversation.service.get_conversation")
def test_update_rejects_unavailable_items_before_save(
    mock_get_conversation, mock_resolve, mock_update
):
    mock_get_conversation.return_value = {"conversation_id": 1, "agent_id": 7}
    mock_resolve.return_value = SimpleNamespace(
        warnings=[{
            "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE",
            "source": "local",
            "count": 1,
        }]
    )

    with pytest.raises(ValidationError, match="unavailable or inaccessible"):
        update_conversation_knowledge_scope_service(
            conversation_id=1,
            knowledge_scope=SCOPE,
            user_id="user",
            tenant_id="tenant",
        )

    mock_update.assert_not_called()


@patch("management.services.conversation.service.update_conversation_knowledge_scope")
@patch("management.services.conversation.service.get_conversation")
def test_update_without_agent_preserves_desired_scope(
    mock_get_conversation, mock_update
):
    mock_get_conversation.return_value = {"conversation_id": 1, "agent_id": None}
    mock_update.return_value = True

    result = update_conversation_knowledge_scope_service(
        conversation_id=1,
        knowledge_scope=SCOPE,
        user_id="user",
        tenant_id="tenant",
    )

    assert result["effective_preview"] is None
    assert result["warnings"] == [{
        "code": "KNOWLEDGE_SCOPE_AGENT_UNASSIGNED",
        "count": 1,
    }]


@patch("management.services.conversation.service.get_conversation", return_value=None)
def test_update_rejects_inaccessible_conversation(_mock_get_conversation):
    with pytest.raises(ConversationNotFoundError):
        update_conversation_knowledge_scope_service(
            conversation_id=404,
            knowledge_scope=SCOPE,
            user_id="user",
            tenant_id="tenant",
        )


@pytest.mark.parametrize("policy", [{"top_k": 0}, {"hybrid_top_k": 8, "graph_top_k": 5}, {"vector_candidates": True}])
def test_actual_workbench_save_rejects_invalid_retrieval_before_persistence(mocker, policy):
    from management.services.agent.system import system_agent_provider
    from management.services.conversation import service as conversations
    from management.services.knowledge_base import scope as scopes

    mocker.patch("consts.const.ENABLE_AIDP_KNOWLEDGE", True)
    mocker.patch.object(system_agent_provider, "get_workbench_main_ref", return_value=SimpleNamespace(agent_id=7, version_no=3))
    mocker.patch.object(scopes, "snapshot_runtime_knowledge_tree", return_value=[{"tools": [{
        "class_name": "AidpSearchTool", "params": [{"name": "top_k", "default": 10}],
    }]}])
    mocker.patch.object(conversations, "get_conversation", return_value={"workbench_config": {"mode": "generic_chat"}})
    persist = mocker.patch.object(conversations, "replace_conversation_workbench_config")
    from consts.model import ConversationKnowledgeScopeRequest
    with pytest.raises(ValidationError):
        conversations.prepare_conversation_retrieval_request(
            1, ConversationKnowledgeScopeRequest(retrieval_config=policy), "user", "tenant",
        )
    persist.assert_not_called()
