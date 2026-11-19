# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Search receives no file catalog grant and closes all readonly vector handles."""

from time import monotonic
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import (
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
)

from infrastructure import knowledge_cleanse, knowledge_runtime
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414 - Actual catalog fixture.
)


def context():
    return OperationContext("search-ports", monotonic() + 5)


def test_search_resource_scope_has_no_file_or_job_namespace(mocker):
    engine, records = Mock(), Mock()
    mocker.patch.object(knowledge_cleanse, "record_engine", return_value=engine)
    bind = mocker.patch.object(knowledge_cleanse, "bind_cleanse_resources", return_value=records)
    with knowledge_cleanse.knowledge_resource_ports("tenant", "user", context=context()) as port:
        assert port is records
        scope = bind.call_args.args[0]
        assert scope.tenant_id == "tenant" and scope.actor_id == "user" and not scope.system
        assert scope.namespaces == {"cleanse_knowledge", "cleanse_memberships", "cleanse_accounts", "cleanse_group_memberships", "cleanse_groups"}
    records.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_partial_vector_assembly_closes_first_readonly_handle_and_records(mocker):
    record, vector = Mock(), Mock()
    engine = Mock()
    mocker.patch.object(knowledge_runtime, "record_engine", return_value=engine)
    bind_records = mocker.patch.object(knowledge_runtime, "bind_knowledge_lifecycle", return_value=record)
    bind = mocker.patch.object(knowledge_runtime, "bind_knowledge_vectors", side_effect=[vector, ValueError("controlled")])
    grant = KnowledgeSearchGrant(knowledge_bases=[KnowledgeBaseGrant(collection=name, knowledge_id=i, resource_tenant_id="tenant", embedding_model_id=2, revision="a"*64) for i,name in [(1,"one"),(2,"two")]])
    with pytest.raises(ValueError), knowledge_runtime.knowledge_search_ports(ServicePrincipal("user", "tenant"), grant, 2, context=context()):
        raise AssertionError("Incomplete port assembly must not yield")
    assert all(c.kwargs["writable"] is False for c in bind.call_args_list)
    vector.close.assert_called_once()
    assert bind_records.call_args.kwargs == {"mode": "read", "knowledge_ids": (1, 2)}
    assert bind_records.call_args.args[0].actor_id == "user"
    record.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_real_resource_binding_accepts_only_its_explicit_subset(resources):
    _, _, engine, _ = resources
    scope = StorageScope("management", "tenant-a", "user-a", {"cleanse_knowledge"})
    port = bind_cleanse_resources(scope, engine)
    try:
        assert len(port.query("cleanse_knowledge", RecordQuery(), PageRequest(), context=context()).items) == 1
        with pytest.raises(ScopeDenied):
            port.query("cleanse_files", RecordQuery(), PageRequest(), context=context())
    finally:
        port.close()
