# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared mutation ports bind resource namespace without changing the actor."""

from time import monotonic
from unittest.mock import Mock

import pytest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure import knowledge_chunk_mutations as ports
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_vectors import (
    bind_knowledge_chunk_vectors,
    bind_knowledge_creation_vectors,
)


@pytest.mark.parametrize("resource", [None, "tenant", ASSET_OWNER_TENANT_ID])
def test_mutation_record_port_keeps_actor_and_closes_owned_engine(monkeypatch, resource):
    engine, records = Mock(), Mock()
    monkeypatch.setattr(ports, "record_engine", Mock(return_value=engine))
    bind = Mock(return_value=records)
    monkeypatch.setattr(ports, "bind_knowledge_lifecycle", bind)
    actor = ServicePrincipal("editor", "tenant")
    with ports.knowledge_chunk_mutation_ports(actor, resource_tenant_id=resource,
        context=OperationContext("shared-port", monotonic()+5)) as result:
        assert result is records
        scope = bind.call_args.args[0]
        assert scope.tenant_id == (resource or actor.tenant_id)
        assert scope.actor_id == actor.user_id and scope.service_role == "runtime" and not scope.system
        assert bind.call_args.kwargs == {"mode": "mutation"}
    records.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_foreign_resource_is_rejected_before_provider_access(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(ports, "record_engine", factory)
    actor = ServicePrincipal("editor", "tenant")
    with pytest.raises(ScopeDenied), ports.knowledge_chunk_mutation_ports(actor, resource_tenant_id="other",
        context=OperationContext("foreign", monotonic()+5)):
        pytest.fail("Foreign namespace was opened")
    with pytest.raises(ScopeDenied):
        bind_knowledge_chunk_vectors(actor, "kb", resource_tenant_id="other")
    with pytest.raises(ScopeDenied):
        bind_knowledge_creation_vectors(actor, "kb", 3, resource_tenant_id="other")
    factory.assert_not_called()


def test_shared_vectors_have_exact_namespace_and_no_actor_impersonation():
    actor = ServicePrincipal("editor", "tenant")
    port = bind_knowledge_chunk_vectors(actor, "kb", resource_tenant_id=ASSET_OWNER_TENANT_ID)
    try:
        assert port.scope.tenant_id == ASSET_OWNER_TENANT_ID and port.scope.actor_id == actor.user_id
        assert port.scope.namespaces == {"kb"}
    finally:
        port.close()
    creation = bind_knowledge_creation_vectors(actor, "kb", 3, resource_tenant_id=ASSET_OWNER_TENANT_ID)
    try:
        assert creation.scope.tenant_id == ASSET_OWNER_TENANT_ID and creation.scope.actor_id == actor.user_id
        assert creation.scope.namespaces == {"kb"}
    finally:
        creation.close()
