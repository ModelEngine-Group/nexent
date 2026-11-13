# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deletion previews list all bound agents returned by the tenant-scoped query."""

from unittest.mock import MagicMock

from management.services.knowledge_base.providers import shared_aidp as aidp_service
from management.services.knowledge_base import management as local_service
import pytest


@pytest.fixture(params=["local", "aidp"])
def service(request):
    local = request.param == "local"
    module = local_service if local else aidp_service
    function = local_service.KnowledgeBaseManagementService.get_bound_agents if local else aidp_service.get_bound_agents
    return module, function, "index_names" if local else "kds_ids"


def test_preview_lists_every_bound_agent_without_user_visibility_filter(service, monkeypatch):
    module, function, field = service
    names = [{"agent_id": 7, "display_name": "Private agent"}, {"agent_id": 8, "display_name": "Shared agent"}]
    lookup = MagicMock(return_value=names)
    monkeypatch.setattr(module, "query_knowledge_binding_agents", lookup)
    assert function(["one", "two"], tenant_id="t1") == {"agents": names}
    lookup.assert_called_once_with(**{field: ["one", "two"]}, tenant_id="t1")


def test_unbound_or_missing_knowledge_returns_empty_without_knowledge_probe(service, monkeypatch):
    module, function, _ = service
    monkeypatch.setattr(module, "query_knowledge_binding_agents", lambda **kwargs: [])
    probe = MagicMock(side_effect=AssertionError("preview must not probe knowledge"))
    if module is local_service:
        monkeypatch.setattr(module, "get_knowledge_record", probe)
    else:
        monkeypatch.setattr(module.aidp_service, "get_aidp_kb_impl", probe)
    assert function(["missing"], tenant_id="t1") == {"agents": []}
    probe.assert_not_called()


def test_database_failure_propagates_from_preview(service, monkeypatch):
    module, function, _ = service
    monkeypatch.setattr(module, "query_knowledge_binding_agents", MagicMock(side_effect=RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError, match="db unavailable"):
        function(["one"], tenant_id="t1")



@pytest.mark.parametrize("failure", [None, "remote", "tool", "conversation", "commit"])
def test_aidp_delete_cleans_bindings_only_after_provider_succeeds(mocker, caplog, failure):
    upstream = mocker.patch.object(aidp_service.aidp_service, "delete_aidp_kb_impl", return_value=True)
    db = mocker.patch.object(aidp_service, "get_db_session")
    session = db.return_value.__enter__.return_value
    db.return_value.__exit__.return_value = False
    tools = mocker.patch.object(aidp_service, "remove_tool_knowledge_references")
    conversations = mocker.patch.object(aidp_service, "remove_conversation_knowledge_bindings")
    if failure == "remote":
        upstream.side_effect = RuntimeError("provider rejected deletion")
        with pytest.raises(RuntimeError, match="provider rejected"):
            aidp_service.delete_aidp_kb_impl("http://aidp.invalid", "fixture-key", "kb")
        db.assert_not_called()
        return
    if failure == "commit":
        db.return_value.__exit__.side_effect = RuntimeError("commit failed")
    elif failure is not None:
        (tools if failure == "tool" else conversations).side_effect = RuntimeError("cleanup failed")

    assert aidp_service.delete_aidp_kb_impl("http://aidp.invalid", "fixture-key", "kb")
    upstream.assert_called_once_with("http://aidp.invalid", "fixture-key", "kb")
    tools.assert_called_once_with(session, kds_ids=["kb"])
    if failure == "tool":
        conversations.assert_not_called()
    else:
        conversations.assert_called_once_with(session, kds_ids=["kb"])
    if failure:
        assert "Failed to clean up bindings for deleted AIDP knowledge base 'kb'" in caplog.text
