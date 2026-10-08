from copy import deepcopy
from types import SimpleNamespace

import pytest

from services import runtime_knowledge_mount as service


def scope(source="local", mode="override", params=None):
    return SimpleNamespace(
        local=SimpleNamespace(mode=mode if source == "local" else "disabled"),
        aidp=SimpleNamespace(mode=mode if source == "aidp" else "disabled"),
        retrieval_config=params,
    )


def tool(kind="KnowledgeBaseSearchTool"):
    return {"class_name": kind, "is_available": True,
            "params": [{"name": "top_k", "type": "number", "default": 5}]}


@pytest.mark.parametrize("aidp", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_mount_is_request_local_and_replaces_other_source(mocker, aidp, existing):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", aidp)
    kind = "AidpSearchTool" if aidp else "KnowledgeBaseSearchTool"
    catalog = [tool(kind)]
    query = mocker.patch.object(service, "query_all_tools", return_value=catalog)
    records = [tool("KnowledgeBaseSearchTool" if aidp else "AidpSearchTool"), {"class_name": "OtherTool"}]
    if existing:
        records.append(tool(kind))
    before = deepcopy(records)
    mounted = service.mount_knowledge_records(records, scope("aidp" if aidp else "local", params={"top_k": 8}), "tenant")
    assert records == before
    assert catalog[0]["params"][0]["default"] == 5
    assert [t["class_name"] for t in mounted] == ["OtherTool", kind]
    assert mounted[-1]["params"][0]["default"] == 8
    assert query.call_count == int(not existing)
    second = service.mount_knowledge_records(records, scope("aidp" if aidp else "local"), "tenant")
    assert second[-1]["params"][0]["default"] == 5


@pytest.mark.parametrize("mode", ["disabled", "inherit"])
def test_no_selection_never_creates_unrestricted_tool(mocker, mode):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", False)
    query = mocker.patch.object(service, "query_all_tools")
    assert service.mount_knowledge_records([], scope(mode=mode), "tenant") == []
    query.assert_not_called()


@pytest.mark.parametrize("params", [{"api_key": "secret"}, {"index_names": ["other"]}, {"top_k": "8"}])
def test_rejects_connection_range_and_invalid_parameters(mocker, params):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", False)
    with pytest.raises(service.ValidationError):
        service.mount_knowledge_records([tool()], scope(params=params), "tenant")


def test_selected_range_replaces_defaults_before_tool_construction(mocker):
    from consts.model import ConversationKnowledgeScopeRequest
    from services import knowledge_scope_service as scopes

    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", False)
    original = tool()
    original["name"] = "knowledge_base_search"
    original["params"].append({"name": "index_names", "default": ["old-index"]})
    request = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "override", "knowledge_ids": ["12"]},
        "aidp": {"mode": "disabled"}, "retrieval_config": {"top_k": 8},
    })
    mounted = service.mount_knowledge_records([original], request, "tenant")
    mocker.patch.object(scopes, "_resolve_local_override", return_value=([
        {"knowledge_id": 12, "index_name": "new-index", "knowledge_name": "Selected"},
    ], []))
    resolved = scopes.resolve_knowledge_scope(
        request, agent_id=1, tenant_id="tenant", user_id="user", version_no=1, is_debug=False,
        runtime_agent_tree=[{"agent_name": "root", "tools": mounted}],
    )
    assert resolved.tool_params.agents["root"].tools["knowledge_base_search"]["index_names"] == ["new-index"]
    assert mounted[0]["params"][0]["default"] == 8
    assert original["params"][0]["default"] == 5
    assert original["params"][1]["default"] == ["old-index"]


def test_connection_credentials_cannot_be_saved_as_session_parameters():
    from consts.model import ConversationKnowledgeScopeRequest

    with pytest.raises(ValueError):
        ConversationKnowledgeScopeRequest.model_validate({"retrieval_config": {"api_key": "secret"}})
