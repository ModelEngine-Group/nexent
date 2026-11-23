# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext, Revision, VectorKey, VectorRecord

from infrastructure.vdb import native_knowledge
from infrastructure.vdb.native_file_cleanup import (
    _delete,
    _delete_legacy,
    _delete_legacy_sources,
    _legacy_target,
    _native_target,
)


@pytest.fixture
def fixture():
    es = Mock()
    es.options.return_value = es
    es.indices.get_settings.return_value = {"kb": {"settings": {"index": {"uuid": "old-uuid"}}}}
    es.indices.stats.return_value = {"_shards": {"failed": 0}, "indices": {"kb": {"uuid": "old-uuid", "shards": {
        "0": [{"routing": {"primary": True, "node": "p1"}, "seq_no": {"max_seq_no": 3},
               "docs": {"count": 4, "deleted": 0}}],
    }}}}
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


@pytest.mark.parametrize(("mode", "calls"), [("accurate", 1), ("semantic", 1), ("hybrid", 2)])
def test_native_fixed_file_query_only_admits_its_published_generation(monkeypatch, fixture, mode, calls):
    es, actor, grant, context = fixture
    monkeypatch.setattr(native_knowledge, "_configured_client", lambda _: es)
    monkeypatch.setattr(native_knowledge, "record_engine", lambda _: Mock())
    monkeypatch.setattr(native_knowledge, "require_index_owner", Mock())
    older, selected, foreign = "a" * 32, "b" * 32, "c" * 32
    file_id = "f" * 32
    lookup = Mock(side_effect=lambda *args, file_versions=None, **kwargs: (
        frozenset({older, selected, foreign}) if file_versions is None else frozenset({selected})))
    monkeypatch.setattr(native_knowledge, "_published_generations", lookup)
    marker = native_knowledge.INGEST_GENERATION
    es.indices.get_mapping.return_value["kb"]["mappings"]["properties"][marker] = {"type": "keyword"}
    identity = native_knowledge.native_file_document_id(file_id, 2, selected, 0)
    es.search.return_value = {"hits": {"hits": [{"_index": "kb", "_id": identity, "_score": 2.0,
        "_source": {"id": identity, "content": "allowed", marker: selected}}]}}
    hits, revisions = native_knowledge.search_native_knowledge(
        actor, [grant], "term", None if mode == "accurate" else (1., 0.1), 3, .5, False,
        file_versions={file_id: 2}, mode=mode, context=context,
    )
    assert hits[0]["file"] == {"file_id": file_id, "file_version": 2, "chunk_index": 0}
    assert hits[0]["document"] == {"id": identity, "content": "allowed"}
    assert es.search.call_count == calls
    for call in es.search.call_args_list:
        query = call.kwargs["body"]
        assert selected in str(query) and older not in str(query) and foreign not in str(query)
        assert "must_not" not in str(query)
    assert native_knowledge.native_search_revisions(actor, [grant], context=context) == revisions


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


def test_native_source_groups_protect_aggregation_and_omit_bodies(monkeypatch, fixture):
    es, actor, grant, context = fixture
    engine, owner = Mock(), Mock()
    monkeypatch.setattr(native_knowledge, "_configured_client", lambda _: es)
    monkeypatch.setattr(native_knowledge, "record_engine", lambda _: engine)
    monkeypatch.setattr(native_knowledge, "bind_legacy_index_owner", owner)
    owner.return_value.get.return_value = {"owner_count": 1, "selected_owner_count": 1}
    source = {"path_or_url": "files/old.pdf", "filename": "old.pdf", "file_size": 10}
    es.search.return_value = {"timed_out": False, "_shards": {"failed": 0}, "aggregations": {"sources": {"buckets": [
        {"key": "files/old.pdf", "doc_count": 3,
         "sample": {"hits": {"hits": [{"_index": "kb", "_source": source}]}}},
    ]}}}
    present, groups = native_knowledge.native_source_groups(actor, grant, 2, context=context)
    assert present and groups[0].count == 3
    assert groups[0].sample == {"path": "files/old.pdf", "filename": "old.pdf", "size": 10}
    options = es.search.call_args.kwargs
    assert options["index"] == "kb" and options["size"] == 0
    assert {"term": {"nexent_read_owned": True}} in options["query"]["bool"]["filter"]
    assert native_knowledge.legacy_document_filter() in options["query"]["bool"]["filter"][1]["bool"]["should"]
    assert options["runtime_mappings"]["nexent_read_owned"]["script"]["params"] == {"tenant": "tenant"}
    aggregation = options["aggregations"]["sources"]
    assert aggregation["terms"]["field"] == "path_or_url"
    assert "content" not in aggregation["aggs"]["sample"]["top_hits"]["_source"]
    assert owner.call_count == 2
    source["metadata"] = {"tenant_id": "other"}
    with pytest.raises(ScopeDenied):
        native_knowledge.native_source_groups(actor, grant, 2, context=context)


def test_native_chunk_window_closes_latest_pit_and_projects_only_requested_rows(fixture):
    es, _, grant, context = fixture
    es.open_point_in_time.return_value = {"id": "pit-1"}
    es.search.return_value = {"timed_out": False, "_shards": {"failed": 0}, "pit_id": "pit-2",
        "hits": {"total": {"relation": "eq", "value": 2}, "hits": [
            {"_index": "kb", "_id": "first", "_source": {}, "sort": [0, 0]},
            {"_index": "kb", "_id": "second", "_source": {"content": "old", "embedding": [1, 0]}, "sort": [1, 1]},
        ]}}
    total, rows = native_knowledge._native_window(es, grant, "source", 1, 1, context)
    assert total == 2 and rows == [("second", {"id": "second", "content": "old"})]
    assert {"term": {"path_or_url": "source"}} in es.search.call_args.kwargs["query"]["bool"]["filter"]
    es.close_point_in_time.assert_called_once_with(id="pit-2")


def test_native_chunk_window_skips_a_full_page_without_loading_chunk_bodies(fixture):
    es, _, grant, context = fixture
    es.open_point_in_time.return_value = {"id": "pit"}
    response = {"timed_out": False, "_shards": {"failed": 0}}
    total = {"relation": "eq", "value": 1001}
    es.search.side_effect = [
        response | {"hits": {"total": total, "hits": [{"sort": [i, i]} for i in range(1000)]}},
        response | {"hits": {"total": total, "hits": [
            {"_index": "kb", "_id": "kept", "_source": {"content": "visible"}, "sort": [1000, 1000]},
        ]}},
    ]
    total, rows = native_knowledge._native_window(es, grant, None, 1000, 1, context)
    assert total == 1001 and rows[0][0] == "kept"
    first, second = es.search.call_args_list
    assert first.kwargs["source"] is False
    assert second.kwargs["source"] is True and second.kwargs["search_after"] == [999, 999]


def test_native_staged_generation_is_scoped_to_original_index_and_does_not_look_published(fixture):
    es, actor, grant, context = fixture
    values = es.indices.get_mapping.return_value["kb"]["mappings"]["properties"]
    values[native_knowledge.INGEST_GENERATION] = {"type": "keyword"}
    grant.file_id, grant.file_version, grant.filename = "f" * 32, 2, "source.txt"
    grant.source = SimpleNamespace(key="files/source.txt")
    generation = "a" * 32
    authorize = Mock()
    writer = native_knowledge.NativeFileGenerationWriter(es, actor, grant, 2, grant, authorize=authorize)
    record = VectorRecord(VectorKey("kb", "logical"), (1., 0.1), {
        "knowledge_id": 1, "file_id": grant.file_id, "file_version": 2, "chunk_index": 0, "media_kind": "text",
        "content": "body", "location": {"path_or_url": grant.source.key, "file_size": 17},
    }, Revision(generation))
    es.bulk.return_value = {"items": [{"index": {"status": 201, "_index": "kb"}}]}
    assert writer.upsert((record,), context=context)[0].matched
    action, source = es.bulk.call_args.kwargs["operations"]
    assert action["index"]["_index"] == "kb"
    assert source["id"] == action["index"]["_id"] and source["path_or_url"] == "files/source.txt"
    assert source["content"] == "body" and source["embedding"] == (1., 0.1)
    authorize.assert_called_once_with(context=context)
    assert not native_knowledge._visible_generation(source, ())
    assert native_knowledge._visible_generation(source, {generation})
    assert native_knowledge._visible_generation({"content": "historical"}, ())
    es.indices.put_mapping.assert_not_called()
    record.payload["media_kind"] = "image"
    with pytest.raises(InvalidInput):
        writer.upsert((record,), context=context)
    es.bulk.assert_called_once()


def test_native_image_uses_image_vector_and_keeps_reference_out_of_public_chunks(fixture):
    es, actor, grant, context = fixture
    props = es.indices.get_mapping.return_value["kb"]["mappings"]["properties"]
    props[native_knowledge.INGEST_GENERATION] = {"type": "keyword"}
    grant.file_id, grant.file_version, grant.filename = "f" * 32, 3, "slides.pdf"
    grant.source = SimpleNamespace(key="files/slides.pdf")
    image_ref = {"key": "cleanse/private/slide.png", "space": "files", "version": "etag:v1", "sha256": "a" * 64}
    writer = native_knowledge.NativeFileGenerationWriter(es, actor, grant, 2, grant, authorize=Mock())
    es.bulk.return_value = {"items": [{"index": {"status": 201, "_index": "kb"}}]}
    es.indices.put_mapping.return_value = {"acknowledged": True}
    generation = "b" * 32
    record = VectorRecord(VectorKey("kb", "image"), (1., 0.1), {
        "knowledge_id": 1, "file_id": grant.file_id, "file_version": 3, "chunk_index": 2, "media_kind": "image",
        "content": "raw reference is not projected",
        "location": {"path_or_url": grant.source.key, "image_ref": image_ref, "page_number": 7},
    }, Revision(generation))
    assert writer.upsert((record,), context=context)[0].matched
    source = es.bulk.call_args.kwargs["operations"][1]
    assert source["multi_embedding"] == (1., 0.1) and "embedding" not in source
    assert source["process_source"] == "UniversalImageExtractor"
    assert image_ref["key"] not in source["content"]
    assert es.indices.put_mapping.call_args.kwargs["properties"] == {
        native_knowledge.INGEST_IMAGE: {"type": "object", "enabled": False},
    }
    image = native_knowledge._native_image(source[native_knowledge.INGEST_IMAGE], grant.knowledge_id, source)
    assert image["image_ref"].model_dump() == image_ref and image["file_version"] == 3
    assert image["location"] == {"page_number": 7, "chunk_index": 2}
    _, public = native_knowledge._native_chunk({"_id": source["id"], "_index": "kb", "_source": source}, grant, {generation})
    assert native_knowledge.INGEST_IMAGE not in public and "multi_embedding" not in public


def test_native_generation_filter_pins_each_published_batch_to_its_index(fixture):
    es, _, _, context = fixture
    reader = native_knowledge._NativeHybrid(es, {"kb": "tenant", "other": "tenant"}, context)
    reader.generations = {"kb": frozenset({"a" * 32}), "other": frozenset()}
    es.search.return_value = {"hits": {"hits": [{"_index": "other", "_id": "leaked", "_score": 1.0,
        "_source": {native_knowledge.INGEST_GENERATION: "a" * 32}}]}}
    with pytest.raises(Conflict):
        reader.exec_query("kb,other", {"query": {"match_all": {}}})
    filter_ = es.search.call_args.kwargs["body"]["query"]["bool"]["filter"]["bool"]["should"]
    assert filter_[1]["bool"]["filter"][0] == {"term": {"_index": "kb"}}


def test_historical_document_cannot_supply_native_image_ticket_context(fixture):
    es, _, _, context = fixture
    reader = native_knowledge._NativeHybrid(es, {"kb": "tenant"}, context)
    es.search.return_value = {"hits": {"hits": [{"_index": "kb", "_id": "historical", "_score": 1.0,
        "_source": {"content": "historical", native_knowledge.INGEST_IMAGE: {"image_ref": "forged"}}}]}}
    result = reader.exec_query("kb", {"query": {"match_all": {}}})
    assert result[0]["document"] == {"id": "historical", "content": "historical"}


def test_native_file_cleanup_uses_generation_scope_and_per_document_revision(fixture):
    es, actor, grant, context = fixture
    generation = "a" * 32
    grant.file_id = "f" * 32
    identity = native_knowledge.native_file_document_id(grant.file_id, 2, generation, 0)
    marker = native_knowledge.INGEST_GENERATION
    es.indices.get_mapping.return_value["kb"]["mappings"]["properties"][marker] = {"type": "keyword"}
    es.open_point_in_time.return_value = {"id": "pit"}
    es.search.side_effect = [{"hits": {"hits": [{"_index": "kb", "_id": identity, "_seq_no": 2, "_primary_term": 1,
        "_source": {marker: generation, "id": identity, "index": 0}, "sort": [0]}]}}, {"hits": {"hits": []}}]
    es.bulk.return_value = {"items": [{"delete": {"_index": "kb", "status": 200}}]}
    es.count.return_value = {"count": 0, "_shards": {"failed": 0}}
    assert _delete(es, grant, actor.tenant_id, {generation: 2}, context=context) == 1
    assert es.count.call_args.kwargs["query"] == {"terms": {marker: [generation]}}
    assert es.bulk.call_args.kwargs["operations"] == [
        {"delete": {"_index": "kb", "_id": identity, "if_seq_no": 2, "if_primary_term": 1}},
    ]


def test_native_file_cleanup_rejects_other_identity_even_with_matching_generation(fixture):
    _, actor, grant, _ = fixture
    generation = "a" * 32
    grant.file_id = "f" * 32
    identity = native_knowledge.native_file_document_id("b" * 32, 2, generation, 0)
    with pytest.raises(ScopeDenied):
        _native_target({"_index": "kb", "_id": identity, "_source": {
            native_knowledge.INGEST_GENERATION: generation, "id": identity, "index": 0,
        }}, grant, actor.tenant_id, {generation: 2})


def test_legacy_source_delete_excludes_new_generations_and_checks_exact_absence(fixture):
    es, actor, grant, context = fixture
    grant.file_id, grant.file_version, grant.legacy_sources = "a" * 32, 3, ["files/old.txt"]
    es.indices.get_mapping.return_value["kb"]["mappings"]["properties"]["path_or_url"] = {"type": "keyword"}
    es.open_point_in_time.return_value = {"id": "pit"}
    es.search.side_effect = [{"hits": {"hits": [{"_index": "kb", "_id": "legacy", "_seq_no": 2, "_primary_term": 1,
        "_source": {"path_or_url": "files/old.txt"}, "sort": [0]}]}}, {"hits": {"hits": []}}]
    es.bulk.return_value = {"items": [{"delete": {"_index": "kb", "status": 200}}]}
    es.count.return_value = {"count": 0, "_shards": {"failed": 0}}
    assert _delete_legacy(es, grant, actor.tenant_id, context=context) == 1
    assert es.count.call_args.kwargs["query"]["bool"]["filter"] == [
        native_knowledge.legacy_document_filter(), {"terms": {"path_or_url": ["files/old.txt"]}},
    ]
    assert es.bulk.call_args.kwargs["operations"] == [
        {"delete": {"_index": "kb", "_id": "legacy", "if_seq_no": 2, "if_primary_term": 1}},
    ]


@pytest.mark.parametrize(("extra", "error"), [
    ({native_knowledge.INGEST_GENERATION: "b" * 32}, ScopeDenied),
    ({"metadata": {"file_id": "c" * 32}}, ScopeDenied),
    ({"file_version": 4}, Conflict),
])
def test_legacy_source_delete_rejects_conflicting_lineage(fixture, extra, error):
    _, actor, grant, _ = fixture
    grant.file_id, grant.file_version, grant.legacy_sources = "a" * 32, 3, ["files/old.txt"]
    with pytest.raises(error):
        _legacy_target({"_index": "kb", "_source": {"path_or_url": "files/old.txt", **extra}},
                       grant.collection, actor.tenant_id, grant.legacy_sources, file_id=grant.file_id,
                       file_version=grant.file_version)


@pytest.mark.parametrize("claim", [None, {"file_id": "explicit"}])
def test_untracked_source_validates_all_pages_before_writing(fixture, claim):
    es, actor, grant, context = fixture
    address = "files/untracked.txt"
    es.indices.get_mapping.return_value["kb"]["mappings"]["properties"]["path_or_url"] = {"type": "keyword"}
    es.open_point_in_time.return_value = {"id": "pit"}
    es.search.side_effect = [
        {"hits": {"hits": [{"_index": "kb", "_id": "first", "_seq_no": 2, "_primary_term": 1, "sort": [0],
                           "_source": {"path_or_url": address}}]}},
        {"hits": {"hits": [{"_index": "kb", "_id": "second", "_seq_no": 3, "_primary_term": 1, "sort": [1],
                           "_source": {"path_or_url": address, "metadata": claim}}]}},
        {"hits": {"hits": []}},
    ]
    es.bulk.return_value = {"items": [{"delete": {"_index": "kb", "status": 200}}]}
    es.count.return_value = {"count": 0, "_shards": {"failed": 0}}
    if claim:
        with pytest.raises(ScopeDenied):
            _delete_legacy_sources(es, grant.collection, actor.tenant_id, [address], context=context)
        es.bulk.assert_not_called()
    else:
        assert _delete_legacy_sources(es, grant.collection, actor.tenant_id, [address], context=context) == 2
        assert es.bulk.call_count == 2
