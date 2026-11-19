# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SHARED-SEARCH-02 opens bounded per-tenant read ports and closes all handles."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure import knowledge_runtime
from infrastructure.agentos_identity import ServicePrincipal
from test.backend.infrastructure.test_knowledge_search_ports import context


def grant():
    return KnowledgeSearchGrant(knowledge_bases=[KnowledgeBaseGrant(knowledge_id=k, collection=f"kb-{k}",
        resource_tenant_id=ASSET_OWNER_TENANT_ID if k==2 else "tenant", embedding_model_id=2, revision="a"*64)
        for k in (2,1,3)])


@pytest.fixture
def ports(monkeypatch):
    opened = []
    engine = Mock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(knowledge_runtime, "record_engine", factory)

    def bind(scope, actual_engine, *, mode, knowledge_ids):
        assert actual_engine is engine and mode == "read"
        value = SimpleNamespace(scope=scope, knowledge_ids=knowledge_ids, close=Mock())
        opened.append(value)
        return value

    vectors = []
    def vector(actor, collection, dimensions, *, writable, resource_tenant_id):
        assert actor == ServicePrincipal("user", "tenant") and writable is False and dimensions == 3
        value = SimpleNamespace(scope=StorageScope("runtime",resource_tenant_id,actor.user_id,{collection}), close=Mock())
        vectors.append(value)
        return value

    monkeypatch.setattr(knowledge_runtime,"bind_knowledge_lifecycle",bind)
    build_vectors = Mock(side_effect=vector)
    monkeypatch.setattr(knowledge_runtime,"bind_knowledge_vectors",build_vectors)
    return SimpleNamespace(**locals())


def test_mixed_ports_group_only_authorized_kbs_and_keep_actual_actor(ports):
    s = ports
    with knowledge_runtime.knowledge_search_ports(ServicePrincipal("user","tenant"),grant(),3,context=context()) as (records,vectors):
        assert set(records)=={1,2,3} and set(vectors)=={"kb-1","kb-2","kb-3"}
        assert records[1] is records[3] and records[1] is not records[2]
        assert records[1].knowledge_ids==(1,3) and records[2].knowledge_ids==(2,)
        assert records[2].scope.tenant_id==ASSET_OWNER_TENANT_ID and records[2].scope.actor_id=="user"
    assert len(s.opened)==2
    for value in s.opened+s.vectors:value.close.assert_called_once()
    s.engine.dispose.assert_called_once()


def test_foreign_namespace_is_rejected_before_engine_or_provider(ports):
    s = ports
    value = grant()
    value.knowledge_bases[0].resource_tenant_id="foreign"
    with pytest.raises(ScopeDenied), knowledge_runtime.knowledge_search_ports(ServicePrincipal("user","tenant"),value,3,context=context()):
        pytest.fail("Foreign namespace was opened")
    s.factory.assert_not_called()
    s.build_vectors.assert_not_called()


def test_partial_vector_failure_closes_both_record_groups_and_first_vector(ports):
    s = ports
    create = s.build_vectors.side_effect
    def fail(actor,collection,dimensions,**kwargs):
        if collection=="kb-1":raise ValueError("controlled")
        return create(actor,collection,dimensions,**kwargs)
    s.build_vectors.side_effect=fail
    with pytest.raises(ValueError), knowledge_runtime.knowledge_search_ports(ServicePrincipal("user","tenant"),grant(),3,context=context()):
        pytest.fail("Incomplete assembly yielded")
    assert len(s.opened)==2 and len(s.vectors)==1
    for value in s.opened+s.vectors:value.close.assert_called_once()
    s.engine.dispose.assert_called_once()
