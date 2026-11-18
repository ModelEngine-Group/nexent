# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed write orchestration preserves actual scope, fresh grants and bounded execution."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.knowledge_chunk_mutation import ChunkMutationGrant
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import DeleteReceipt, WriteReceipt
from runtime.knowledge_base.chunk_write import ChunkMutationService

from test.backend.services.test_knowledge_chunk_creation import (
    context,
)
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
async def write(creation):
    s = creation
    grant = ChunkMutationGrant(
        knowledge_id=1,
        chunk_id=s.value.chunk_id,
        operation="create",
        collection="collection",
        resource_tenant_id=s.s.actor.tenant_id,
        revision="a" * 64,
        embedding_model_id=2,
    )
    client = SimpleNamespace(
        authorize_knowledge_chunk_mutation=AsyncMock(return_value=grant)
    )
    opened = []

    @contextmanager
    def records(actor, *, context):
        assert actor == s.s.actor
        opened.append(True)
        yield s.s.mutation_records

    @contextmanager
    def maintenance(actor, collection, *, context):
        assert actor == s.s.actor and collection == "collection"
        yield s.vectors

    service = ChunkMutationService(
        client,
        s.models,
        records=records,
        creation_ports=s.ports,
        maintenance_ports=maintenance,
    )
    return SimpleNamespace(**locals())


async def test_plaintext_write_projects_receipt_and_reauthorizes_before_write(write):
    s = write
    result = await s.service.mutate(s.s.value, s.s.s.actor)
    assert (
        result.status == "completed"
        and result.count_delta == 1
        and result.commit_epoch == 1
    )
    assert result.knowledge_id == 1 and result.chunk_id == "manual"
    assert (
        not {"created_by", "request_sha256", "changes", "content"}
        & result.model_dump().keys()
    )
    assert s.client.authorize_knowledge_chunk_mutation.await_count == 2
    assert all(
        c.args[1:] == (s.s.s.actor.user_id, s.s.s.actor.tenant_id)
        for c in s.client.authorize_knowledge_chunk_mutation.call_args_list
    )
    s.s.models.invoke.assert_not_awaited()
    duplicate = await s.service.mutate(s.s.value, s.s.s.actor)
    assert duplicate == result and s.s.vectors.put.call_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("knowledge_id", 2),
        ("chunk_id", "other"),
        ("operation", "delete"),
        ("resource_tenant_id", "other"),
        ("revision", "b" * 64),
        ("embedding_model_id", 3),
    ],
)
async def test_mismatched_grant_is_refused_before_opening_ports(write, field, value):
    s = write
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(
        update={field: value}
    )
    payload = s.s.value.model_copy(
        update={
            "changes": {
                **s.s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    with pytest.raises((ScopeDenied, Conflict)):
        await s.service.mutate(payload, s.s.s.actor)
    assert s.opened == []
    s.s.vectors.put.assert_not_called()


async def test_revocation_after_model_call_prevents_storage_and_releases_known_admission(
    write,
):
    s = write
    payload = s.s.value.model_copy(
        update={
            "changes": {
                **s.s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    s.client.authorize_knowledge_chunk_mutation.side_effect = [s.grant, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await s.service.mutate(payload, s.s.s.actor)
    s.s.models.invoke.assert_awaited_once()
    s.s.vectors.put.assert_not_called()
    await s.s.db(s.s.s.mutation.assert_drained, context=context())


async def test_authorization_timeout_cancels_once_without_opening_storage(write):
    s = write
    cancelled = []

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    s.client.authorize_knowledge_chunk_mutation.side_effect = stalled
    s.service.operation_seconds = 0.05
    with pytest.raises(DeadlineExceeded):
        await s.service.mutate(s.s.value, s.s.s.actor)
    assert cancelled == [True] and s.opened == []
    assert s.client.authorize_knowledge_chunk_mutation.await_count == 1


async def test_second_grant_timeout_never_writes_or_extends_the_budget(write):
    s = write
    calls = []

    async def authorize(*args):
        calls.append(True)
        if len(calls) == 1:
            return s.grant
        await asyncio.Event().wait()

    s.client.authorize_knowledge_chunk_mutation.side_effect = authorize
    s.service.operation_seconds = 0.05
    with pytest.raises(DeadlineExceeded):
        await s.service.mutate(s.s.value, s.s.s.actor)
    assert len(calls) == 2
    s.s.vectors.put.assert_not_called()


async def test_unknown_write_returns_existing_receipt_without_replay(write):
    s = write
    s.s.vectors.put.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await s.service.mutate(s.s.value, s.s.s.actor)
    receipt = await s.service.mutate(s.s.value, s.s.s.actor)
    assert receipt.status == "unknown" and receipt.count_delta is None
    assert s.s.vectors.put.call_count == 1


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_existing_write_uses_condition_executor_without_models(write, operation):
    s = write
    await s.service.mutate(s.s.value, s.s.s.actor)
    payload = s.s.value.model_copy(
        update={
            "operation": operation,
            "request_key": operation,
            "changes": {"content": "after"} if operation == "update" else {},
        }
    )
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(
        update={"operation": operation}
    )
    s.s.vectors.patch_payload.return_value = WriteReceipt("patch", True)
    s.s.vectors.delete_key.return_value = DeleteReceipt("delete", True)
    result = await s.service.mutate(payload, s.s.s.actor)
    assert result.status == "completed" and result.count_delta == (
        0 if operation == "update" else -1
    )
    s.s.models.invoke.assert_not_awaited()
