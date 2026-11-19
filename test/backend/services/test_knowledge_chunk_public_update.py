# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-UPDATE-01/02 preserve native doc merge over AgentOS."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge import ChunkUpdateRequest
from contracts.knowledge_chunk_mutation import ChunkMutationState, ChunkMutationTarget
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from management.services.knowledge_base.chunk_update import update_manual_chunk
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
def update(monkeypatch):
    actor = ServicePrincipal("editor", "tenant")
    row = {"knowledge_id": 1, "index_name": "kb", "tenant_id": "tenant", "deletion_request": None,
           "knowledge_sources": "elasticsearch", "embedding_model_id": 2}
    reader = SimpleNamespace(knowledge=Mock(return_value=row), files=Mock(return_value=[]))
    revision = chunks_resource_grant(row).revision
    source = {"id": "alias", "filename": ["old.txt"], "title": "old", "created_by": "creator",
              "custom": {"keep": 1, "change": 2, "inner": {"keep": 3, "replace": 4}}, "array": [1, 2]}
    target = ChunkMutationTarget(knowledge_id=1, chunk_id="alias", operation="update", resource_revision=revision,
        resolve_public_id=True, change_epoch=7, generation="created", chunk={"knowledge_id": 1,
            "chunk_id": "physical", "content": "old body", "location": {PUBLIC_CHUNK_SOURCE_KEY: deepcopy(source)}})
    state = ChunkMutationState(knowledge_id=1, chunk_id="physical", operation="update", mutation_id="a" * 64,
        status="completed", writer_ended=True, count_delta=0, commit_epoch=8)
    client = SimpleNamespace(inspect_knowledge_chunk=AsyncMock(return_value=target), mutate_knowledge_chunk=AsyncMock(return_value=state))
    contexts = []

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop("lane"); kwargs.pop("owner")
        contexts.append(kwargs["context"])
        return action(*args, **kwargs)

    monkeypatch.setattr("management.services.knowledge_base.chunk_update.run_blocking", blocking)
    return SimpleNamespace(**locals())


async def test_recursive_metadata_merge_keeps_unmodified_fields_and_actual_storage_id(update):
    s = update
    patch = ChunkUpdateRequest(content="request body", metadata={"content": ["raw", 42], "id": ["new", "alias"],
        "custom": {"change": None, "inner": {"replace": [9]}}, "array": [3], "title": None,
        "updated_by": "display-only", "embedding_model_id": "opaque"})
    result = await update_manual_chunk("kb", "alias", patch, s.actor, reader=s.reader, client=s.client)
    assert result == {"status": "success", "chunk_id": "physical", "message": "Chunk physical updated successfully"}
    request, user, tenant = s.client.inspect_knowledge_chunk.await_args.args
    assert request.resolve_public_id and request.operation == "update" and request.chunk_id == "alias"
    assert (user, tenant) == ("editor", "tenant")
    intent, user, tenant = s.client.mutate_knowledge_chunk.await_args.args
    assert intent.chunk_id == "physical" and intent.expected_change_epoch == 7 and intent.file_ref is None
    assert intent.changes["content"] == ["raw", 42] and "embedding" not in intent.changes
    raw = intent.changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["id"] == ["new", "alias"] and raw["filename"] == ["old.txt"] and raw["title"] == "old"
    assert raw["custom"] == {"keep": 1, "change": None, "inner": {"keep": 3, "replace": [9]}}
    assert raw["array"] == [3] and raw["created_by"] == "creator" and raw["updated_by"] == "display-only"
    assert raw["embedding_model_id"] == "opaque" and raw["update_time"] and "content" not in raw
    assert s.target.chunk.location[PUBLIC_CHUNK_SOURCE_KEY] == s.source
    assert (user, tenant) == ("editor", "tenant") and s.contexts[0].cancelled.is_set()


async def test_explicit_embedding_uses_standard_replacement_without_model_calls(update):
    s = update
    await update_manual_chunk("kb", "alias", ChunkUpdateRequest(metadata={"embedding": [0, 1, 0]}),
                               s.actor, reader=s.reader, client=s.client)
    intent = s.client.mutate_knowledge_chunk.await_args.args[0]
    assert intent.changes["embedding"] == [0, 1, 0] and "content" not in intent.changes
    assert "embedding" not in intent.changes["location"][PUBLIC_CHUNK_SOURCE_KEY]


async def test_empty_update_still_records_old_audit_fields_without_changing_content_or_vector(update):
    s = update
    await update_manual_chunk("kb", "alias", ChunkUpdateRequest(content=None, metadata={"embedding": None}),
                               s.actor, reader=s.reader, client=s.client)
    changes = s.client.mutate_knowledge_chunk.await_args.args[0].changes
    assert set(changes) == {"location"}
    raw = changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["updated_by"] == "editor" and raw["update_time"]


async def test_original_file_source_uses_authorized_path_and_keeps_binding(update):
    s = update
    chunk = s.target.chunk
    s.target.chunk_id = "physical"
    chunk.file_id, chunk.file_version, chunk.chunk_index = "c" * 32, 3, 2
    chunk.location, chunk.filename = {"page": 7}, "original.txt"
    s.reader.files.return_value = [{"file_id": chunk.file_id, "knowledge_id": 1, "tenant_id": "tenant",
        "delete_flag": "N", "object_name": "original/path", "local_source_path": None, "create_time": "original-time"}]
    await update_manual_chunk("kb", "physical", ChunkUpdateRequest(title="changed"), s.actor, reader=s.reader, client=s.client)
    intent = s.client.mutate_knowledge_chunk.await_args.args[0]
    assert intent.file_ref.model_dump() == {"knowledge_id": 1, "file_id": "c" * 32, "file_version": 3}
    assert intent.generation == "created" and intent.chunk_index == 2
    assert intent.changes["location"]["page"] == 7
    raw = intent.changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["path_or_url"] == "original/path" and raw["create_time"] == "original-time"
    assert raw["filename"] == "original.txt" and raw["title"] == "changed"


async def test_missing_file_metadata_cannot_invent_a_public_source(update):
    s = update
    s.target.chunk_id = "physical"
    s.target.chunk.file_id, s.target.chunk.file_version, s.target.chunk.chunk_index = "c" * 32, 3, 2
    s.target.chunk.location = {}
    with pytest.raises(ScopeDenied):
        await update_manual_chunk("kb", "physical", ChunkUpdateRequest(title="changed"), s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


async def test_missing_chunk_keeps_original_update_failure(update):
    s = update
    s.target.chunk, s.target.generation = None, None
    with pytest.raises(RuntimeError, match="Error updating chunk"):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("field,value", [("knowledge_id", 2), ("chunk_id", "other"), ("operation", "delete"),
    ("resource_revision", "f" * 64), ("resolve_public_id", False)])
async def test_mismatched_target_is_rejected_before_write(update, field, value):
    s = update
    setattr(s.target, field, value)
    with pytest.raises(Conflict):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("status", ["reserved", "writing", "unknown", "failed"])
async def test_unfinished_update_never_returns_success_or_retries(update, status):
    s = update
    s.state.status = status
    with pytest.raises(OutcomeUnknown):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client)
    assert s.client.mutate_knowledge_chunk.await_count == 1


@pytest.mark.parametrize("phase", ["lookup", "write"])
async def test_timeout_cancels_http_without_another_request(update, phase):
    s = update
    cancelled = []
    async def wait(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    method = s.client.inspect_knowledge_chunk if phase == "lookup" else s.client.mutate_knowledge_chunk
    method.side_effect = wait
    with pytest.raises(DeadlineExceeded):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client, operation_seconds=0.03)
    assert cancelled == [True] and method.await_count == 1


async def test_resource_denial_prevents_all_http(update):
    s = update
    s.reader.knowledge.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client)
    s.client.inspect_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("field,value", [("chunk_id", "other"), ("writer_ended", False),
    ("count_delta", 1), ("commit_epoch", None), ("commit_epoch", 7)])
async def test_inconsistent_completed_receipt_cannot_become_success(update, field, value):
    s = update
    setattr(s.state, field, value)
    with pytest.raises(Conflict):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(), s.actor, reader=s.reader, client=s.client)
    assert s.client.mutate_knowledge_chunk.await_count == 1


async def test_invalid_source_after_resource_lookup_is_update_failure(update):
    s = update
    with pytest.raises(RuntimeError, match="Error updating chunk"):
        await update_manual_chunk("kb", "alias", ChunkUpdateRequest(metadata={"value": float("nan")}),
                                  s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()
