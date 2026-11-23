# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import OperationContext, Revision, VectorKey, VectorRecord

from infrastructure.vdb import native_knowledge


@pytest.fixture
def fixture():
    es = Mock()
    es.options.return_value = es
    es.indices.get_settings.return_value = {"kb": {"settings": {"index": {"uuid": "old-uuid"}}}}
    es.indices.get_mapping.return_value = {"kb": {"mappings": {"properties": {
        name: {"type": "dense_vector", "dims": 2} for name in ("embedding", "multi_embedding")
    }}}}
    actor = SimpleNamespace(user_id="user", tenant_id="tenant")
    grant = SimpleNamespace(knowledge_id=1, collection="kb", resource_tenant_id="tenant", revision="a" * 64)
    return es, actor, grant, OperationContext("test", monotonic() + 10)


def test_existing_flat_documents_recalled_without_publication_records(monkeypatch, fixture):
    es, actor, grant, context = fixture
    engine, owner = Mock(), Mock()
    monkeypatch.setattr(native_knowledge, "_configured_client", lambda _: es)
    monkeypatch.setattr(native_knowledge, "record_engine", lambda _: engine)
    monkeypatch.setattr(native_knowledge, "bind_legacy_index_owner", owner)
    owner.return_value.get.return_value = {"owner_count": 1, "selected_owner_count": 1}
    source = {"content": "old", "path_or_url": "files/old.pdf", "embedding": [1.0, 0.1]}
    es.search.return_value = {"hits": {"hits": [{"_index": "kb", "_id": "native-key", "_score": 2.0, "_source": source}]}}
    hits, revisions = native_knowledge.search_native_knowledge(actor, [grant], "old", (1.0, 0.1), 3, 0.5, False, context=context)
    assert hits[0]["document"] == {"id": "native-key", "content": "old", "path_or_url": "files/old.pdf"}
    assert len(revisions[1]) == 64
    assert [call.kwargs["index"] for call in es.search.call_args_list] == ["kb", "kb"]
    assert es.search.call_args.kwargs["body"]["knn"]["field"] == "embedding"
    assert owner.call_count == 2
    es.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_rejects_foreign_document_even_with_authorized_index(fixture):
    es, _, _, context = fixture
    search = native_knowledge._NativeHybrid(es, {"kb": "tenant"}, context)
    es.search.return_value = {"hits": {"hits": [
        {"_index": "kb", "_id": "id", "_source": {"metadata": {"tenant_id": "other"}}},
    ]}}
    with pytest.raises(ScopeDenied):
        search.exec_query("kb", {})


@pytest.mark.parametrize(("media", "vector_field"), [("text", "embedding"), ("image", "multi_embedding")])
def test_create_preserves_native_identity_and_source_fields(fixture, media, vector_field):
    es, actor, grant, context = fixture
    writes = native_knowledge.NativeDocumentCreation(es, actor, grant, 2)
    key = VectorKey("kb", "new-native-key")
    payload = {"knowledge_id": 1, "content": "some content", "media_kind": media,
               "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "display", "path_or_url": "files/new.pdf"}}}
    row = VectorRecord(key, (1., 0.1), payload, Revision("generation"))
    es.index.return_value = {"_index": "kb", "result": "created"}
    assert writes.put(row, expected_generation=None, context=context).matched
    options = es.index.call_args.kwargs
    assert (options["index"], options["id"], options["op_type"]) == ("kb", "new-native-key", "create")
    assert options["document"][vector_field] == (1.0, 0.1)
    assert options["document"]["path_or_url"] == "files/new.pdf"
    assert options["document"]["id"] == "display"
    assert options["document"]["content"] == "some content"
    assert "payload" not in options["document"]
    es.indices.put_mapping.assert_not_called()
    es.indices.create.assert_not_called()
    with pytest.raises(Conflict):
        writes.put(row, expected_generation=Revision("previous"), context=context)
    es.index.assert_called_once()


def test_write_refuses_alias(fixture):
    es, actor, grant, context = fixture
    writes = native_knowledge.NativeDocumentCreation(es, actor, grant, 2)
    es.indices.get_mapping.return_value = {"other": {"mappings": {}}}
    with pytest.raises(ScopeDenied):
        writes.ensure_collection("kb", context=context)
    es.index.assert_not_called()
