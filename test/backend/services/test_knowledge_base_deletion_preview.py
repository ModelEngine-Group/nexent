# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deletion previews list all bound agents returned by the tenant-scoped query."""

from unittest.mock import MagicMock

import ext_components.aidp.services.aidp_service as aidp_service
import management.services.knowledge_base.management as local_service
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
    probe_name = "get_knowledge_record" if module is local_service else "get_aidp_kb_impl"
    probe = MagicMock(side_effect=AssertionError("preview must not probe knowledge"))
    monkeypatch.setattr(module, probe_name, probe)
    assert function(["missing"], tenant_id="t1") == {"agents": []}
    probe.assert_not_called()


def test_database_failure_propagates_from_preview(service, monkeypatch):
    module, function, _ = service
    monkeypatch.setattr(module, "query_knowledge_binding_agents", MagicMock(side_effect=RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError, match="db unavailable"):
        function(["one"], tenant_id="t1")
