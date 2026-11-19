# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-DELETE-03 keeps the actual actor for shared asset deletion."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_mutation import ChunkMutationGrant, ChunkMutationLookup
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import DeleteReceipt
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_write import ChunkMutationService

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle
from test.backend.services.test_knowledge_chunk_creation import context
from test.backend.services.test_knowledge_chunk_creation import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
def shared_ports(creation):
    s = creation.s
    ports = []
    try:
        for name, mode in (("record", "jobs"), ("mutation_records", "mutation")):
            scope = replace(getattr(s, name).scope, tenant_id=ASSET_OWNER_TENANT_ID)
            port = bind_knowledge_lifecycle(scope, s.engine, mode=mode)
            ports.append(port)
            setattr(s, name, port)
        yield
    finally:
        for port in ports:
            port.close()


async def test_shared_asset_lookup_and_delete_keep_actor_and_resource_separate(creation, shared_ports):
    s = creation
    actor = s.s.actor
    owner = ServicePrincipal(actor.user_id, ASSET_OWNER_TENANT_ID)
    s.s.actor = owner
    s.vectors.scope = replace(s.vectors.scope, tenant_id=ASSET_OWNER_TENANT_ID)
    journal = ChunkMutationAdmission(s.s.mutation_records, 1)
    s.service.journal, s.service.actor = journal, owner
    await s.service.execute(s.value, context=context())
    calls = []

    @contextmanager
    def records(principal, *, resource_tenant_id, context):
        assert principal == actor and resource_tenant_id == ASSET_OWNER_TENANT_ID
        calls.append("records")
        yield s.s.mutation_records

    @contextmanager
    def vectors(principal, collection, *, resource_tenant_id, context):
        assert principal == actor and resource_tenant_id == ASSET_OWNER_TENANT_ID
        calls.append("vectors")
        yield s.vectors

    @contextmanager
    def lookup(principal, grant, *, context):
        assert principal == actor and grant.resource_tenant_id == ASSET_OWNER_TENANT_ID
        yield s.s.record, s.vectors

    client = SimpleNamespace(authorize_knowledge_chunk_mutation=AsyncMock(return_value=ChunkMutationGrant(
        knowledge_id=1, chunk_id="manual", operation="delete", collection="collection",
        resource_tenant_id=ASSET_OWNER_TENANT_ID, revision="a" * 64)))
    service = ChunkMutationService(client, s.models, records=records, maintenance_ports=vectors, lookup_ports=lookup)
    request = ChunkMutationLookup(knowledge_id=1, chunk_id="manual", operation="delete", resource_revision="a" * 64)
    target = await service.lookup(request, actor)
    s.vectors.delete_key.return_value = DeleteReceipt("delete", True)
    result = await service.mutate(s.value.model_copy(update={"operation": "delete", "request_key": "delete",
        "changes": {}, "expected_change_epoch": target.change_epoch}), actor)
    assert result.status == "completed" and calls == ["records", "vectors"]
    for call in client.authorize_knowledge_chunk_mutation.await_args_list:
        assert call.args[1:] == (actor.user_id, actor.tenant_id)
    row = await s.db(journal.records.get, "runtime_knowledge_chunk_changes", result.mutation_id, context=context())
    assert row["tenant_id"] == ASSET_OWNER_TENANT_ID
    assert row["user_id"] == row["created_by"] == row["updated_by"] == actor.user_id


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_unmigrated_shared_writes_remain_rejected(creation, operation):
    s = creation
    client = SimpleNamespace(authorize_knowledge_chunk_mutation=AsyncMock(return_value=ChunkMutationGrant(
        knowledge_id=1, chunk_id="manual", operation=operation, collection="collection",
        resource_tenant_id=ASSET_OWNER_TENANT_ID, revision="a" * 64)))
    service = ChunkMutationService(client, s.models)
    with pytest.raises(ScopeDenied):
        await service._grant(s.value.model_copy(update={"operation": operation}), s.s.actor)
