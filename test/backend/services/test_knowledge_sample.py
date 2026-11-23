# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Summary samples expose only complete published generations to the actual reader."""

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos_knowledge import KnowledgeSample, KnowledgeSearchGrant
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import (
    FieldPatch,
    Page,
    PageRequest,
    RecordQuery,
    Revision,
    VectorKey,
    VectorRecord,
)
from runtime.knowledge_base.sample import KnowledgeSampleService

from infrastructure.rdb.knowledge_jobs import FILES, JOBS
from test.backend.services.test_knowledge_worker import (
    setup as setup,  # noqa: PLC0414
)


@pytest.fixture
async def sample(setup):
    s = setup
    await s.worker.process(s.lookup, s.actor, owner_id='writer', context=s.context)
    job = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    s.models.invoke.reset_mock()
    s.models.get.reset_mock()
    grant = KnowledgeSearchGrant(knowledge_bases=[{
        'knowledge_id': 1, 'collection': 'kb', 'resource_tenant_id': s.actor.tenant_id, 'embedding_model_id': 2, 'revision': 'a' * 64,
    }])
    s.client.authorize_knowledge_search = AsyncMock(return_value=grant)
    s.models.get.return_value = type('Metadata', (), {'model_id': 2, 'model_type': 'embedding', 'revision': 'v1'})()
    record = VectorRecord(VectorKey('kb', 'chunk'), (1.0, 0.5), {
        'knowledge_id': 1, 'file_id': s.request.file_id, 'file_version': 0,
        'content': 'published text', 'filename': 'source.txt', 'chunk_index': 0,
        'embedding_model_id': 2, 'embedding_revision': 'v1', 'location': {},
    }, Revision(job['attempt_id']))
    assert job['chunk_count'] == 1
    s.vectors.scan.return_value = Page((record,))
    s.closed.clear()

    @contextmanager
    def ports(*args, **kwargs):
        try:
            yield {1: s.records}, {'kb': s.vectors}
        finally:
            s.closed.append(True)

    return s, KnowledgeSample(knowledge_id=1, expected_revision='a' * 64), grant, record, KnowledgeSampleService(
        s.client, s.models, ports=ports)


async def test_sample_returns_stored_embeddings_without_model_inference(sample):
    s, request, _, _, service = sample
    result = await service.sample(request, s.actor)
    assert result.knowledge_id == 1 and result.knowledge_revision == 'a' * 64
    assert len(result.data_revision) == 64 and len(result.documents) == 1
    document = result.documents[0]
    assert document.file_ref.file_id == s.request.file_id and document.file_ref.file_version == 0
    assert document.chunks[0].embedding == [1.0, 0.5]
    assert document.chunks[0].content == 'published text' and document.filename == 'source.txt'
    assert s.closed == [True] and s.client.authorize_knowledge_search.await_count == 2
    assert all(c.args[1:] == ('user', 'tenant') for c in s.client.authorize_knowledge_search.call_args_list)
    s.models.invoke.assert_not_awaited()
    assert s.vectors.scan.call_args.args[0] == 'kb'


async def test_unpublished_generations_are_excluded(sample):
    s, request, _, record, service = sample
    s.vectors.scan.return_value = Page((replace(record, generation=Revision('old')), record))
    result = await service.sample(request, s.actor)
    assert len(result.documents[0].chunks) == 1


@pytest.mark.parametrize('change', ['foreign-file', 'foreign-kb', 'model', 'missing', 'duplicate'])
async def test_incomplete_or_mismatched_sample_is_refused(sample, change):
    s, request, _, record, service = sample
    patches = {'foreign-file': {'file_id': 'f' * 32}, 'foreign-kb': {'knowledge_id': 2},
               'model': {'embedding_revision': 'other'}}
    if change == 'missing':
        items = ()
    elif change == 'duplicate':
        items = (record, record)
    else:
        items = (replace(record, payload={**record.payload, **patches[change]}),)
    s.vectors.scan.return_value = Page(items)
    with pytest.raises((Conflict, ScopeDenied)):
        await service.sample(request, s.actor)
    assert s.closed == [True]
    s.models.invoke.assert_not_awaited()


async def test_stale_resource_revision_is_refused_before_storage(sample):
    s, request, _, _, service = sample
    with pytest.raises(Conflict):
        await service.sample(request.model_copy(update={'expected_revision': 'b' * 64}), s.actor)
    assert s.closed == []
    s.vectors.scan.assert_not_called()


async def test_resource_grant_change_discards_all_content(sample):
    s, request, grant, _, service = sample
    changed = grant.model_copy(update={'knowledge_bases': []})
    s.client.authorize_knowledge_search.side_effect = [grant, changed]
    with pytest.raises(ScopeDenied):
        await service.sample(request, s.actor)
    assert s.closed == [True]


async def test_manifest_change_during_vector_read_discards_content(sample):
    s, request, _, record, service = sample
    def changed(*args, **kwargs):
        rows = s.records.query(FILES, RecordQuery(), PageRequest(), context=s.context)
        row = rows.items[0]
        s.records.patch(FILES, row['record_id'], FieldPatch(set_values={
            'visible_job_id': None, 'visible_version': None, 'visible_generation': None,
        }), context=s.context)
        return Page((record,))
    s.vectors.scan.side_effect = changed
    with pytest.raises(Conflict):
        await service.sample(request, s.actor)
    assert s.vectors.scan.call_count == 1


async def test_all_chunk_pages_are_consumed_and_sorted(sample):
    s, request, _, record, service = sample
    await s.db(s.records.patch, JOBS, s.state.job_id, FieldPatch(set_values={'chunk_count': 2}), context=s.context)
    second = replace(record, key=VectorKey('kb', 'chunk-2'), payload={**record.payload, 'chunk_index': 1})
    s.vectors.scan.side_effect = [Page((second,), 'next'), Page((record,))]
    result = await service.sample(request, s.actor)
    assert [c.chunk_index for c in result.documents[0].chunks] == [0, 1]
    assert s.vectors.scan.call_args.args[2].cursor == 'next'


async def test_deadline_cancels_metadata_query_without_storage_or_retry(sample):
    import asyncio

    s, request, _, _, service = sample
    cancelled = []
    async def blocked(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    s.models.get.side_effect = blocked
    service.operation_seconds = 0.1
    with pytest.raises(DeadlineExceeded):
        await service.sample(request, s.actor)
    assert cancelled == [True] and s.closed == []
    s.models.get.assert_awaited_once()
    s.vectors.scan.assert_not_called()


@pytest.mark.parametrize("changed", [False, True])
async def test_native_sample_uses_original_layout_and_rechecks_data_revision(sample, mocker, changed):
    s, request, grant, _, service = sample
    sample_native = mocker.patch("runtime.knowledge_base.sample.sample_native_knowledge", return_value=("b" * 64, []))
    revision = mocker.patch("runtime.knowledge_base.sample.native_search_revisions",
                            return_value={1: ("c" if changed else "b") * 64})
    request = request.model_copy(update={"native_documents": True})
    if changed:
        with pytest.raises(Conflict):
            await service.sample(request, s.actor)
    else:
        assert (await service.sample(request, s.actor)).data_revision == "b" * 64
    assert sample_native.call_args.args[:2] == (s.actor, grant.knowledge_bases[0])
    assert revision.call_args.args == (s.actor, grant.knowledge_bases)
    s.vectors.scan.assert_not_called()
    s.models.invoke.assert_not_awaited()


def test_native_sample_reservoir_stays_bounded_when_random_slot_equals_limit(monkeypatch):
    from infrastructure.vdb import native_sample

    records = [(str(i), {"path_or_url": f"document/{i}", "content": str(i), "embedding": [0.5]})
               for i in range(5)]
    monkeypatch.setattr(native_sample.random, "randrange", lambda size: 2)

    def scan(fields, selected=None):
        if selected is None:
            return iter(records)
        paths = selected["bool"]["should"][0]["terms"]["nexent_sample_path"]
        return (row for row in records if row[1]["path_or_url"] in paths)

    result = native_sample._samples(scan, type("Resource", (), {"knowledge_id": 1})(), 1, 2)
    assert [doc.path_or_url for doc in result] == ["document/0", "document/1"]
