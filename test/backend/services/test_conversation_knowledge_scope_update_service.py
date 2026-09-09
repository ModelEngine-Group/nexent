from types import SimpleNamespace
from unittest.mock import patch

import pytest

from consts.exceptions import ConversationNotFoundError, ValidationError
from services.conversation_management_service import (
    update_conversation_knowledge_scope_service,
)


SCOPE = {
    "schema_version": 1,
    "local": {"mode": "override", "knowledge_ids": ["12"]},
    "aidp": {"mode": "disabled", "kds_ids": []},
}


@patch("services.conversation_management_service.update_conversation_knowledge_scope")
@patch("services.conversation_management_service._resolve_knowledge_scope_for_update")
@patch("services.conversation_management_service.get_conversation")
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


@patch("services.conversation_management_service.update_conversation_knowledge_scope")
@patch("services.conversation_management_service._resolve_knowledge_scope_for_update")
@patch("services.conversation_management_service.get_conversation")
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


@patch("services.conversation_management_service.update_conversation_knowledge_scope")
@patch("services.conversation_management_service.get_conversation")
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


@patch("services.conversation_management_service.get_conversation", return_value=None)
def test_update_rejects_inaccessible_conversation(_mock_get_conversation):
    with pytest.raises(ConversationNotFoundError):
        update_conversation_knowledge_scope_service(
            conversation_id=404,
            knowledge_scope=SCOPE,
            user_id="user",
            tenant_id="tenant",
        )
