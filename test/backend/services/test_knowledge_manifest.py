# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime manifests are read evidence with current DAC and revision-bound pagination."""

from contextlib import contextmanager

import pytest
from contracts.agentos_knowledge import KnowledgeBaseInspect
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery, StorageScope
from runtime.knowledge_base.manifest import KnowledgeManifestService

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_jobs import FILES, bind_knowledge_manifest
from test.backend.services.test_knowledge_sample import (
    sample as sample,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_worker import (
    setup as setup,  # noqa: PLC0414
)


@pytest.fixture
def manifest(sample):
    s, _, _, _, _ = sample
    @contextmanager
    def ports(*args, **kwargs):
        try: yield s.records
        finally: s.closed.append(True)
    return s, KnowledgeManifestService(s.client, ports=ports), KnowledgeBaseInspect(knowledge_id=1, expected_revision='a'*64)


async def test_manifest_reports_registered_visibility_without_model_or_vector_io(manifest):
    s, service, request = manifest
    s.vectors.reset_mock()
    result = await service.inspect(request, s.actor, context=s.context)
    assert result.knowledge_id == 1 and result.embedding_model_id == 2 and len(result.manifest_revision) == 64
    row, = result.files
    assert row.file_id == s.request.file_id and row.visible_version == 0 and row.tombstone_version == -1
    assert row.visible_generation and row.record_revision > 0 and row.upload_job_reference_present
    assert result.next_cursor is None and s.closed == [True]
    s.models.get.assert_not_awaited(); s.models.invoke.assert_not_awaited()
    s.vectors.scan.assert_not_called()
    assert s.client.authorize_knowledge_search.await_count == 2


async def test_pagination_is_bound_to_all_manifests_and_current_actor(manifest):
    s, service, request = manifest
    page = await s.db(s.records.query, FILES, RecordQuery(), PageRequest(), context=s.context)
    original, = page.items
    second = {key: value for key, value in original.items() if key not in {
        'revision', 'created_by', 'create_time', 'updated_by', 'update_time', 'delete_flag'}}
    second.update(record_id='f'*32, file_id='e'*32, visible_job_id=None, visible_version=None,
                  visible_generation=None, active_job_id=None)
    await s.db(s.records.create, FILES, second, context=s.context)
    first = await service.inspect(request.model_copy(update={'page_size': 1}), s.actor, context=s.context)
    assert first.next_cursor and len(first.files) == 1
    second_page = await service.inspect(request.model_copy(update={'page_size': 1, 'cursor': first.next_cursor}), s.actor, context=s.context)
    assert second_page.next_cursor is None and second_page.manifest_revision == first.manifest_revision
    assert second_page.files[0].file_id != first.files[0].file_id
    with pytest.raises(ScopeDenied):
        await service.inspect(request.model_copy(update={'cursor': first.next_cursor}), ServicePrincipal('other',s.actor.tenant_id), context=s.context)
    await s.db(s.records.patch, FILES, 'f'*32, FieldPatch(set_values={'latest_version': 1}), context=s.context)
    with pytest.raises(Conflict):
        await service.inspect(request.model_copy(update={'cursor': first.next_cursor}), s.actor, context=s.context)


async def test_resource_revision_change_is_rejected_before_manifest_read(manifest):
    s, service, request = manifest
    with pytest.raises(Conflict):
        await service.inspect(request.model_copy(update={'expected_revision': 'b'*64}), s.actor, context=s.context)
    assert not s.closed


async def test_authorization_revoked_after_scan_discards_result(manifest):
    s, service, request = manifest
    grant = s.client.authorize_knowledge_search.return_value
    s.client.authorize_knowledge_search.side_effect = [grant, ScopeDenied()]
    with pytest.raises(ScopeDenied): await service.inspect(request, s.actor, context=s.context)
    assert s.closed == [True]


async def test_change_between_full_reads_discards_manifest_without_retry(manifest, monkeypatch):
    s, service, request=manifest
    original=s.records.query;calls=[]
    def changed(*args, **kwargs):
        result=original(*args, **kwargs);calls.append(True)
        if len(calls)==1:
            s.records.patch(FILES,result.items[0]['record_id'],FieldPatch(set_values={'latest_version':1}),context=s.context)
        return result
    monkeypatch.setattr(s.records,'query',changed)
    with pytest.raises(Conflict): await service.inspect(request,s.actor,context=s.context)
    assert len(calls)==2 and s.closed==[True]


async def test_total_deadline_cancels_stalled_authorization(manifest):
    import asyncio
    s, service, request=manifest;closed=[]
    async def blocked(*args):
        try: await asyncio.Event().wait()
        finally: closed.append(True)
    s.client.authorize_knowledge_search.side_effect=blocked
    service.operation_seconds=0.02
    with pytest.raises(DeadlineExceeded): await service.inspect(request,s.actor)
    assert closed==[True] and not s.closed


async def test_manifest_port_is_read_only_and_physically_bound_to_selected_kb(manifest):
    s, _, _=manifest
    initial=await s.db(s.records.query,FILES,RecordQuery(),PageRequest(),context=s.context)
    row={key:value for key,value in initial.items[0].items() if key not in {
        'revision','created_by','create_time','updated_by','update_time','delete_flag'}}
    row.update(record_id='f'*32,file_id='e'*32,knowledge_id=2,visible_job_id=None,visible_version=None,
               visible_generation=None,active_job_id=None)
    await s.db(s.records.create,FILES,row,context=s.context)
    port=bind_knowledge_manifest(StorageScope('runtime',s.actor.tenant_id,s.actor.user_id,{FILES}),1,s.engine)
    try:
        page=await s.db(port.query,FILES,RecordQuery(),PageRequest(),context=s.context)
        assert len(page.items)==1 and page.items[0]['knowledge_id']==1
        with pytest.raises(ScopeDenied):
            await s.db(port.patch,FILES,page.items[0]['record_id'],FieldPatch(set_values={'latest_version':7}),context=s.context)
    finally: port.close()
