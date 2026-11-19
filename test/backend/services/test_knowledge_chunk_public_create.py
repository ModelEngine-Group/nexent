# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-CREATE-01 preserves the public source and creation identity."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge import ChunkCreateRequest
from contracts.knowledge_chunk_mutation import ChunkMutationState, ChunkMutationTarget
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from management.services.knowledge_base.chunk_creation import create_manual_chunk
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
def creation(monkeypatch):
    actor = ServicePrincipal("editor", "tenant")
    row = {"knowledge_id": 1, "index_name": "kb", "tenant_id": "tenant", "deletion_request": None,
           "knowledge_sources": "elasticsearch", "embedding_model_id": 2}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))
    revision = chunks_resource_grant(row).revision
    client = SimpleNamespace(inspect_knowledge_chunk=AsyncMock(), mutate_knowledge_chunk=AsyncMock())
    contexts = []

    async def lookup(request, user, tenant):
        assert (user, tenant) == (actor.user_id, actor.tenant_id)
        return ChunkMutationTarget(**request.model_dump(), change_epoch=7)

    async def mutate(intent, user, tenant):
        assert (user, tenant) == (actor.user_id, actor.tenant_id)
        return ChunkMutationState(knowledge_id=1, chunk_id=intent.chunk_id, operation="create", mutation_id="a" * 64,
            status="completed", writer_ended=True, count_delta=1, commit_epoch=8)

    client.inspect_knowledge_chunk.side_effect = lookup
    client.mutate_knowledge_chunk.side_effect = mutate

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop("lane"); kwargs.pop("owner")
        contexts.append(kwargs["context"])
        return action(*args, **kwargs)

    monkeypatch.setattr("management.services.knowledge_base.chunk_creation.run_blocking", blocking)
    return SimpleNamespace(**locals())


async def test_metadata_overrides_preserve_original_model_input_and_actual_audit(creation):
    s = creation
    request = ChunkCreateRequest(content="original input", chunk_id="base", title="old", metadata={
        "id": "actual", "content": [123, "raw"], "filename": ["name"], "created_by": "display-only",
        "embedding": [1, 0, 0], "embedding_model_id": "display-only-model", "title": None,
        "custom": {"nested": [False, None]}})
    result = await create_manual_chunk("kb", request, s.actor, reader=s.reader, client=s.client)
    assert result == {"status": "success", "chunk_id": "actual", "message": "Chunk actual created successfully"}
    lookup = s.client.inspect_knowledge_chunk.await_args.args[0]
    assert lookup.chunk_id == "actual" and not lookup.resolve_public_id
    intent = s.client.mutate_knowledge_chunk.await_args.args[0]
    assert intent.chunk_id == "actual" and intent.expected_change_epoch == 7 and intent.file_ref is None
    assert intent.changes["content"] == [123, "raw"] and intent.changes["embedding_input"] == "original input"
    assert intent.changes["embedding_model"] == {"model_id": 2}
    assert intent.changes["supplied_embedding"] == [1, 0, 0]
    raw = intent.changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["created_by"] == "display-only" and raw["filename"] == ["name"]
    assert raw["title"] == "old" and raw["custom"] == {"nested": [False, None]}
    assert raw["embedding_model_id"] == "display-only-model" and raw["create_time"]
    assert "content" not in raw and "embedding" not in raw
    s.reader.knowledge.assert_called_once_with("kb", s.actor, edit=True, context=s.contexts[0])
    assert s.contexts[0].cancelled.is_set()


@pytest.mark.parametrize("value,key", [(123, "123"), (False, "false"), (1.5, "1.5"),
    (["one", 2, False, None], "one,2,false,None"), (["one", ["two", 3]], "one,two,3")])
async def test_native_client_id_conversion_is_preserved(creation, value, key):
    s = creation
    result = await create_manual_chunk("kb", ChunkCreateRequest(content="body", metadata={"id": value}),
                                       s.actor, reader=s.reader, client=s.client)
    assert result["chunk_id"] == key
    raw = s.client.mutate_knowledge_chunk.await_args.args[0].changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["id"] == value and type(raw["id"]) is type(value)


@pytest.mark.parametrize("value", ["", []])
async def test_empty_id_gets_new_storage_key_while_raw_source_is_unchanged(creation, value):
    s = creation
    result = await create_manual_chunk("kb", ChunkCreateRequest(content="body", metadata={"id": value}),
                                       s.actor, reader=s.reader, client=s.client)
    assert result["chunk_id"] and result["chunk_id"] != str(value)
    assert s.client.mutate_knowledge_chunk.await_args.args[0].changes["location"][PUBLIC_CHUNK_SOURCE_KEY]["id"] == value


async def test_default_id_and_time_keep_public_format(creation):
    s = creation
    result = await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader, client=s.client)
    assert result["chunk_id"].startswith("chunk_") and len(result["chunk_id"]) == 38
    raw = s.client.mutate_knowledge_chunk.await_args.args[0].changes["location"][PUBLIC_CHUNK_SOURCE_KEY]
    assert raw["created_by"] == "editor" and len(raw["create_time"]) == 19
    assert "filename" not in raw


@pytest.mark.parametrize("failure", [ScopeDenied(), ValueError("missing")])
async def test_resource_failure_prevents_all_http(creation, failure):
    s = creation
    s.reader.knowledge.side_effect = failure
    with pytest.raises(type(failure)):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader, client=s.client)
    s.client.inspect_knowledge_chunk.assert_not_awaited()
    s.client.mutate_knowledge_chunk.assert_not_awaited()


async def test_unfinished_receipt_is_not_success_or_retried(creation):
    s = creation
    async def unknown(*args):
        return (await s.mutate(*args)).model_copy(update={"status": "unknown"})
    s.client.mutate_knowledge_chunk.side_effect = unknown
    with pytest.raises(OutcomeUnknown):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader, client=s.client)
    assert s.client.mutate_knowledge_chunk.await_count == 1


async def test_mismatched_lookup_prevents_write(creation):
    s = creation
    async def foreign(*args):
        return (await s.lookup(*args)).model_copy(update={"knowledge_id": 2})
    s.client.inspect_knowledge_chunk.side_effect = foreign
    with pytest.raises(Conflict):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()


async def test_write_timeout_cancels_http_without_new_budget_or_replay(creation):
    s = creation
    cancelled = []
    async def block(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    s.client.mutate_knowledge_chunk.side_effect = block
    with pytest.raises(DeadlineExceeded):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader,
                                  client=s.client, operation_seconds=0.03)
    assert cancelled == [True] and s.client.mutate_knowledge_chunk.await_count == 1


async def test_existing_file_key_is_conditionally_overwritten_with_zero_count_delta(creation):
    s = creation
    async def existing(*args):
        result = await s.lookup(*args)
        return ChunkMutationTarget(**{**result.model_dump(), "generation": "published", "chunk": {
            "knowledge_id": 1, "chunk_id": "existing", "content": "old",
            "file_id": "c" * 32, "file_version": 3, "chunk_index": 2}})
    async def overwrite(*args):
        return (await s.mutate(*args)).model_copy(update={"count_delta": 0})
    s.client.inspect_knowledge_chunk.side_effect = existing
    s.client.mutate_knowledge_chunk.side_effect = overwrite
    result = await create_manual_chunk("kb", ChunkCreateRequest(content="new", chunk_id="existing"),
                                       s.actor, reader=s.reader, client=s.client)
    assert result["chunk_id"] == "existing"
    intent = s.client.mutate_knowledge_chunk.await_args.args[0]
    assert intent.file_ref.model_dump() == {"knowledge_id": 1, "file_id": "c" * 32, "file_version": 3}
    assert intent.generation == "published" and intent.chunk_index == 2 and intent.expected_change_epoch == 7


@pytest.mark.parametrize("field,value", [("chunk_id", "foreign"), ("writer_ended", False),
    ("count_delta", 0), ("commit_epoch", None), ("commit_epoch", 7)])
async def test_bad_completed_receipt_is_not_returned_as_public_success(creation, field, value):
    s = creation
    async def corrupt(*args):
        return (await s.mutate(*args)).model_copy(update={field: value})
    s.client.mutate_knowledge_chunk.side_effect = corrupt
    with pytest.raises(Conflict):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor, reader=s.reader, client=s.client)
    assert s.client.mutate_knowledge_chunk.await_count == 1


async def test_invalid_source_after_resource_lookup_keeps_creation_failure_status(creation):
    s = creation
    request = ChunkCreateRequest(content="body", metadata={"custom": float("nan")})
    with pytest.raises(RuntimeError, match="Error creating chunk"):
        await create_manual_chunk("kb", request, s.actor, reader=s.reader, client=s.client)
    s.client.mutate_knowledge_chunk.assert_not_awaited()
