from unittest.mock import patch

from backend.consts.model import ConversationKnowledgeScopeRequest
from backend.services.knowledge_scope_service import resolve_knowledge_scope


def _agent_tree():
    return [{
        "agent_id": 7,
        "version_no": 3,
        "agent_name": "root-agent",
        "tools": [
            {
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
                "params": [{"name": "index_names", "default": ["default-index"]}],
            },
            {
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "params": [{"name": "kds_list", "default": ["default-kds"]}],
            },
        ],
    }]


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
@patch("backend.services.knowledge_scope_service._resolve_local_override")
def test_override_projects_only_selected_local_indices(mock_local_override, _mock_tree):
    mock_local_override.return_value = ([{
        "knowledge_id": 12,
        "index_name": "selected-index",
        "knowledge_name": "Selected KB",
        "embedding_model_id": 9,
    }], [])
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "override", "knowledge_ids": ["12"]},
        "aidp": {"mode": "disabled", "kds_ids": []},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    tools = resolved.tool_params.agents["root-agent"].tools
    assert tools["knowledge_base_search"]["index_names"] == ["selected-index"]
    assert tools["aidp_search"]["kds_list"] == []
    assert resolved.local_knowledge_ids == ["12"]
    assert resolved.local_index_names == ["selected-index"]
    assert resolved.aidp_disabled is True


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
def test_disabled_projects_deny_all_whitelists(_mock_tree):
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "disabled", "knowledge_ids": []},
        "aidp": {"mode": "disabled", "kds_ids": []},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    tools = resolved.tool_params.agents["root-agent"].tools
    assert tools["knowledge_base_search"]["index_names"] == []
    assert tools["aidp_search"]["kds_list"] == []
    assert resolved.local_disabled is True
    assert resolved.aidp_disabled is True
