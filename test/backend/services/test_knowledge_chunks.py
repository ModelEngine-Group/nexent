# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Published chunk windows require current grants and never invoke a model."""

from dataclasses import replace

import pytest
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Page,
    PageRequest,
    RecordQuery,
    StorageScope,
)
from pydantic import ValidationError

from infrastructure.rdb.knowledge_jobs import FILES, JOBS
from test.backend.services.test_knowledge_sample import (
    sample as sample,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_sample import (
    setup as setup,  # noqa: PLC0414
)


@pytest.mark.parametrize('updates', [
    {'offset': -1}, {'limit': 0}, {'limit': 1001},
    {'file_refs': [{'knowledge_id': 2, 'file_id': 'a' * 32, 'file_version': 0}]},
    {'file_refs': [{'knowledge_id': 1, 'file_id': 'a' * 32, 'file_version': 0}] * 2},
])
def test_chunk_request_rejects_invalid_windows_and_file_scope(updates):
    from contracts.agentos_knowledge import KnowledgeChunks

    with pytest.raises(ValidationError):
        KnowledgeChunks(**{'knowledge_id': 1, 'expected_revision': 'a' * 64, **updates})


@pytest.fixture
def browse(sample):
    from contracts.agentos_knowledge import KnowledgeChunks
    from runtime.knowledge_base.chunks import KnowledgeChunksService

    s, original, grant, record, samples = sample
    s.vectors.scope = StorageScope('runtime',s.actor.tenant_id,s.actor.user_id,{'kb'})
    request = KnowledgeChunks(knowledge_id=original.knowledge_id,expected_revision=original.expected_revision,limit=1)
    return s,request,grant,record,KnowledgeChunksService(s.client,s.models,ports=samples.ports)


async def test_window_returns_only_published_content_and_total_without_vectors(browse):
    s,request,_,_,service = browse
    result = await service.chunks(request,s.actor)
    assert result.total==1 and result.next_offset is None
    assert result.chunks[0].file_id==s.request.file_id and result.chunks[0].content=='published text'
    assert result.chunks[0].chunk_index==0 and result.chunks[0].filename=='source.txt'
    assert 'embedding' not in result.chunks[0].model_dump()
    s.models.invoke.assert_not_awaited()
    assert s.closed==[True] and s.client.authorize_knowledge_search.await_count==2


async def test_window_beyond_total_does_not_scan_physical_vectors(browse):
    s,request,_,_,service = browse
    result = await service.chunks(request.model_copy(update={'offset':10}),s.actor)
    assert result.total==1 and result.chunks==[]
    s.vectors.scan.assert_not_called()


async def test_middle_window_filters_chunk_range_and_returns_next_offset(browse):
    s,request,_,record,service = browse
    await s.db(s.records.patch,JOBS,s.state.job_id,FieldPatch(set_values={'chunk_count':3}),context=s.context)
    s.vectors.scan.return_value=Page((replace(record,payload={**record.payload,'chunk_index':1,'content':'middle'}),))
    result=await service.chunks(request.model_copy(update={'offset':1}),s.actor)
    assert result.total==3 and result.next_offset==2 and [chunk.content for chunk in result.chunks]==['middle']
    where=s.vectors.scan.call_args.args[1]
    assert Comparison('chunk_index','gte',1) in where.terms and Comparison('chunk_index','lt',2) in where.terms


async def test_empty_exact_file_selection_is_deny_all(browse):
    s,request,_,_,service=browse
    result=await service.chunks(request.model_copy(update={'file_refs':[]}),s.actor)
    assert result.total==0 and result.chunks==[]
    s.vectors.scan.assert_not_called()


async def test_unpublished_generation_cannot_enter_the_window(browse):
    s,request,_,record,service=browse
    from nexent.storage.models import Revision

    stale=replace(record,generation=Revision('0'*32),payload={**record.payload,'content':'stale'})
    s.vectors.scan.return_value=Page((stale,record))
    assert [chunk.content for chunk in (await service.chunks(request,s.actor)).chunks]==['published text']


async def test_publication_change_during_read_discards_content(browse):
    s,request,_,record,service=browse
    def changed(*args,**kwargs):
        row=s.records.query(FILES,RecordQuery(),PageRequest(),context=s.context).items[0]
        s.records.patch(FILES,row['record_id'],FieldPatch(set_values={
            'visible_version':None,'visible_generation':None,'visible_job_id':None}),context=s.context)
        return Page((record,))
    s.vectors.scan.side_effect=changed
    with pytest.raises(Conflict): await service.chunks(request,s.actor)


async def test_revoked_grant_does_not_return_the_read_window(browse):
    s,request,grant,_,service=browse
    s.client.authorize_knowledge_search.side_effect=[grant,grant.model_copy(update={'knowledge_bases':[]})]
    with pytest.raises(ScopeDenied): await service.chunks(request,s.actor)


@pytest.mark.parametrize('kind',['missing','duplicate','foreign'])
async def test_corrupt_window_never_returns_partial_success(browse,kind):
    s,request,_,record,service = browse
    if kind=='missing': items=()
    elif kind=='duplicate': items=(record,record)
    else: items=(replace(record,payload={**record.payload,'knowledge_id':2}),)
    s.vectors.scan.return_value=Page(items)
    with pytest.raises((Conflict,ScopeDenied)): await service.chunks(request,s.actor)
    s.models.invoke.assert_not_awaited()


async def test_changed_data_revision_is_rejected_before_vector_reads(browse):
    s,request,_,_,service = browse
    with pytest.raises(Conflict):
        await service.chunks(request.model_copy(update={'expected_data_revision':'0'*64}),s.actor)
    s.vectors.scan.assert_not_called()


async def test_stalled_model_metadata_read_obeys_total_deadline(browse):
    import asyncio

    s,request,_,_,service = browse
    cancelled=[]
    async def stalled(*args):
        try: await asyncio.Event().wait()
        finally: cancelled.append(True)
    s.models.get.side_effect=stalled
    service.operation_seconds=0.02
    with pytest.raises(DeadlineExceeded): await service.chunks(request,s.actor)
    assert cancelled==[True]
    s.vectors.scan.assert_not_called()
