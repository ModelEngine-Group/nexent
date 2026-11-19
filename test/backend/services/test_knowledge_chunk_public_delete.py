# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-DELETE-01/02 preserve public semantics over typed AgentOS."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_chunk_mutation import ChunkMutationState, ChunkMutationTarget
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from management.services.knowledge_base.chunk_deletion import delete_manual_chunk
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
)

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def deletion(monkeypatch):
    actor = ServicePrincipal("editor", "tenant")
    row = {"knowledge_id": 1, "index_name": "kb", "tenant_id": "tenant", "deletion_request": None,
           "knowledge_sources": "elasticsearch"}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))
    grant = chunks_resource_grant(row)
    target = ChunkMutationTarget(knowledge_id=1, chunk_id="alias", operation="delete",
        resource_revision=grant.revision, resolve_public_id=True, change_epoch=7,
        chunk={"knowledge_id": 1, "chunk_id": "actual", "content": "body",
               "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "alias"}}}, generation="published")
    state = ChunkMutationState(knowledge_id=1, chunk_id="actual", operation="delete",
        mutation_id="b" * 64, status="completed", writer_ended=True, count_delta=-1, commit_epoch=8)
    client = SimpleNamespace(inspect_knowledge_chunk=AsyncMock(return_value=target),
                             mutate_knowledge_chunk=AsyncMock(return_value=state))
    contexts = []

    # Keep the actual resource reader boundary while isolating the managed scheduler.
    async def execute(name, action, *args, **kwargs):
        for key in ("lane", "owner"):
            kwargs.pop(key, None)
        contexts.append(kwargs["context"])
        return action(*args, **kwargs)

    monkeypatch.setattr("management.services.knowledge_base.chunk_deletion.run_blocking", execute)
    return SimpleNamespace(**locals())


async def test_alias_deletion_uses_real_target_and_returns_original_path_id(deletion):
    s = deletion
    result = await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    assert result == {"status": "success", "chunk_id": "alias", "message": "Chunk alias deleted successfully"}
    lookup, user, tenant = s.client.inspect_knowledge_chunk.await_args.args
    assert lookup.resolve_public_id and lookup.operation == "delete"
    assert (user, tenant) == ("editor", "tenant")
    intent, user, tenant = s.client.mutate_knowledge_chunk.await_args.args
    assert intent.chunk_id == "actual" and intent.expected_change_epoch == 7
    assert intent.file_ref is None and intent.generation is None and not intent.changes
    assert (user, tenant) == ("editor", "tenant")
    s.reader.knowledge.assert_called_once_with("kb", s.actor, edit=True, context=s.contexts[0])
    assert s.contexts[0].cancelled.is_set()


async def test_file_binding_is_transported_without_inventing_identity(deletion):
    s = deletion
    s.target.chunk.file_id = "c" * 32
    s.target.chunk.file_version = 3
    s.target.chunk.chunk_index = 2
    await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    intent = s.client.mutate_knowledge_chunk.await_args.args[0]
    assert intent.file_ref.model_dump() == {"knowledge_id": 1, "file_id": "c" * 32, "file_version": 3}
    assert intent.generation == "published" and intent.chunk_index == 2


async def test_missing_chunk_retains_old_public_failure_and_does_not_write(deletion):
    s = deletion
    s.target.chunk, s.target.generation = None, None
    with pytest.raises(RuntimeError, match="Error deleting chunk: Chunk alias not found in index kb"):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("field,value", [("knowledge_id", 2), ("chunk_id", "other"),
    ("operation", "update"), ("resource_revision", "f" * 64), ("resolve_public_id", False)])
async def test_mismatched_lookup_is_rejected_before_write(deletion, field, value):
    s = deletion
    setattr(s.target, field, value)
    with pytest.raises(Conflict):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("status", ["reserved", "writing", "unknown", "failed"])
async def test_unfinished_receipt_never_becomes_public_success_or_retries(deletion, status):
    s = deletion
    s.state.status = status
    with pytest.raises(OutcomeUnknown):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    assert s.client.inspect_knowledge_chunk.await_count == s.client.mutate_knowledge_chunk.await_count == 1


async def test_dac_failure_never_contacts_runtime(deletion):
    s = deletion
    s.reader.knowledge.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    s.client.inspect_knowledge_chunk.assert_not_awaited()
    s.client.mutate_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("field,value", [("knowledge_id", 2), ("chunk_id", "foreign"),
    ("operation", "create"), ("writer_ended", False), ("count_delta", 0), ("commit_epoch", None), ("commit_epoch", 7)])
async def test_inconsistent_completed_receipt_is_rejected(deletion, field, value):
    s = deletion
    setattr(s.state, field, value)
    with pytest.raises(Conflict):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client)
    assert s.client.mutate_knowledge_chunk.await_count == 1


@pytest.mark.parametrize("phase", ["lookup", "write"])
async def test_single_budget_cancels_http_and_never_retries(deletion, phase):
    s = deletion
    cancelled = []

    async def wait(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    method = s.client.inspect_knowledge_chunk if phase == "lookup" else s.client.mutate_knowledge_chunk
    method.side_effect = wait
    with pytest.raises(DeadlineExceeded):
        await delete_manual_chunk("kb", "alias", s.actor, reader=s.reader, client=s.client, operation_seconds=0.03)
    assert cancelled == [True] and method.await_count == 1
    assert s.client.mutate_knowledge_chunk.await_count == (phase == "write")
