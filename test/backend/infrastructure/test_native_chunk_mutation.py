# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from nexent.storage.errors import Conflict, InvalidInput, NotFound
from nexent.storage.models import (
    FieldPatch,
    OperationContext,
    Revision,
    VectorKey,
    VectorRecord,
)

from infrastructure.vdb.native_chunk_mutation import NativeChunkMutation
from infrastructure.vdb.native_knowledge import (
    INGEST_GENERATION,
    native_file_document_id,
)


@pytest.fixture
def target():
    es = Mock()
    es.options.return_value = es
    es.indices.get_settings.return_value = {"kb": {"settings": {"index": {"uuid": "original"}}}}
    hit = {"_index": "kb", "_id": "elastic-id", "_seq_no": 3, "_primary_term": 1,
           "_source": {"id": "public-id", "content": "before", "path_or_url": "files/old.txt"}}
    es.get.return_value = hit
    actor = SimpleNamespace(tenant_id="tenant", user_id="actor")
    grant = SimpleNamespace(knowledge_id=1, collection="kb", resource_tenant_id="tenant")
    port = NativeChunkMutation(es, actor, grant, None, Mock())
    return es, hit, port, OperationContext("native-write-test", monotonic() + 5)


def test_native_historical_patch_uses_physical_identity_and_inspected_revision(target):
    es, hit, port, context = target
    key = VectorKey("kb", hit["_id"])
    row, revision = port.find(key, resolve_public_id=False, context=context)
    assert row.key == key and row.generation is None
    port.storage_revision = revision
    es.update.return_value = {"_index": "kb", "result": "updated"}
    assert port.patch_payload(key, FieldPatch(set_values={"content": "after"}), expected_generation=None, context=context).matched
    es.update.assert_called_once_with(index="kb", id="elastic-id", doc={"content": "after"},
                                     if_seq_no=3, if_primary_term=1, refresh="wait_for")
    hit["_seq_no"] = 4
    with pytest.raises(Conflict):
        port.delete_key(key, expected_generation=None, context=context)
    es.delete.assert_not_called()


def test_duplicate_display_key_cannot_choose_an_arbitrary_native_document(target, mocker):
    es, hit, port, context = target
    es.indices.get_mapping.return_value = {"kb": {"mappings": {}}}
    original = port._call

    def call(method, ctx, **options):
        if method == "get":
            raise NotFound()
        return original(method, ctx, **options)

    mocker.patch.object(port, "_call", side_effect=call)
    es.search.return_value = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [
        hit, {**hit, "_id": "second-physical-id"},
    ]}}
    with pytest.raises(Conflict):
        port.find(VectorKey("kb", "public-id"), resolve_public_id=True, context=context)
    es.update.assert_not_called()


def test_published_native_chunk_cannot_change_file_source(target):
    es, hit, port, context = target
    generation = "a" * 32
    hit["_id"] = native_file_document_id("b" * 32, 4, generation, 0)
    hit["_source"].update({INGEST_GENERATION: generation, "id": hit["_id"], "index": 0})
    key = VectorKey("kb", hit["_id"])
    row, port.storage_revision = port.find(key, resolve_public_id=False, context=context)
    location = next(iter(row.payload["location"].values()))
    location["path_or_url"] = "files/elsewhere.txt"
    with pytest.raises(InvalidInput):
        port.patch_payload(key, FieldPatch(set_values={"location": row.payload["location"]}),
                           expected_generation=row.generation, context=context)
    es.update.assert_not_called()


def test_native_manual_create_without_embedding_preserves_flat_format_and_requires_new_key(target):
    es, _, port, context = target
    es.index.return_value = {"_index": "kb", "result": "created"}
    row = VectorRecord(VectorKey("kb", "new-physical"), (), {"knowledge_id": 1, "content": "manual",
        "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "new-id", "title": "Visible title"}}}, Revision("journal"))
    assert port.put(row, expected_generation=None, context=context).matched
    es.index.assert_called_once_with(index="kb", id="new-physical", op_type="create", refresh="wait_for",
                                     document={"content": "manual", "id": "new-id", "title": "Visible title"})
