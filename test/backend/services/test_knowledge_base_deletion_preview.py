# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge services own the preview; Agent read only projects visible names."""

from unittest.mock import MagicMock

import pytest

import ext_components.aidp.services.aidp_service as aidp_service
import management.services.knowledge_base.management as local_service


@pytest.fixture(params=["local", "aidp"])
def service(request, monkeypatch):
    local = request.param == "local"
    module = local_service if local else aidp_service
    function = local_service.KnowledgeBaseManagementService.get_bound_agents if local else aidp_service.get_bound_agents
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(module, "get_db_session", lambda: context)
    return module, function, session, "index_names" if local else "kds_ids"


def test_preview_keeps_batch_contract_and_counts_hidden_agents(service, monkeypatch):
    module, function, session, field = service
    rows = [{"agent_id": 7, "version_no": 0}, {"agent_id": 7, "version_no": 1}, {"agent_id": 8, "version_no": 0}]
    query = MagicMock(return_value=rows)
    metadata = {7: {"display_name": "A"}, 8: {"display_name": "Hidden"}}
    names = [{"agent_id": 7, "display_name": "A"}]
    monkeypatch.setattr(module, "query_live_knowledge_bindings", query)
    lookup = MagicMock(return_value=metadata)
    monkeypatch.setattr(module, "query_binding_agent_metadata", lookup)
    visible = MagicMock(return_value=names)
    monkeypatch.setattr(module, "get_visible_agent_names", visible)
    assert function(["one", "two"], user_id="u1", tenant_id="t1") == {
        "agents": names, "hidden_agent_count": 1, "total_agent_count": 2,
    }
    query.assert_called_once_with(session, **{field: ["one", "two"]})
    lookup.assert_called_once_with(session, [7, 7, 8], tenant_id="t1")
    visible.assert_called_once_with(metadata, user_id="u1")


def test_unbound_or_missing_knowledge_returns_empty_without_knowledge_probe(service, monkeypatch):
    module, function, _, _ = service
    monkeypatch.setattr(module, "query_live_knowledge_bindings", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "query_binding_agent_metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "get_visible_agent_names", lambda *args, **kwargs: [])
    probe_name = "get_knowledge_record" if module is local_service else "get_aidp_kb_impl"
    probe = MagicMock(side_effect=AssertionError("preview must not probe knowledge"))
    monkeypatch.setattr(module, probe_name, probe)
    assert function(["missing"], user_id="u1", tenant_id="t1") == {
        "agents": [], "hidden_agent_count": 0, "total_agent_count": 0,
    }
    probe.assert_not_called()


def test_database_failure_propagates_from_preview(service, monkeypatch):
    module, function, _, _ = service
    monkeypatch.setattr(module, "query_live_knowledge_bindings", MagicMock(side_effect=RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError, match="db unavailable"):
        function(["one"], user_id="u1", tenant_id="t1")
