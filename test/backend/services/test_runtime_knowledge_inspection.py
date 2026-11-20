# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Maintenance uses current Management edit DAC and only typed AgentOS Runtime reads."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import KnowledgeBaseState
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionsDescribed
from management.services.knowledge_base.runtime_inspection import (
    RuntimeKnowledgeInspector,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture(autouse=True)
def shared_sqlite(monkeypatch, tmp_path):
    original = sa.create_engine
    monkeypatch.setattr(sa, 'create_engine', lambda *args, **kwargs: original('sqlite:///' + str(tmp_path/'scope.db'),
        connect_args={'check_same_thread': False}))


@pytest.fixture
async def inspection(resources):
    _, update, engine, _ = resources
    update('cleanse_knowledge', embedding_model_id=2)
    @contextmanager
    def ports(tenant_id, user_id, *, context):
        records = cleanse_resources.bind_cleanse_resources(StorageScope('management', tenant_id, user_id,
            set(cleanse_resources.TABLES)), engine)
        try: yield records
        finally: records.close()
    manager = ThreadManager(service_name='runtime-inspection-ut', lane_policies={'control-io': LanePolicy('control-io',1,0)})
    manager.start(); set_default_thread_manager(manager)
    try:
        actor = ServicePrincipal('user-a','tenant-a')
        client = SimpleNamespace(get_model=AsyncMock(return_value=ModelMetadata(model_id=2, model_type='embedding',
            display_name='Embedding', revision='v1', embedding_dimensions=2)), inspect_knowledge_base=AsyncMock())
        service = RuntimeKnowledgeInspector(client=client, resources=ports)
        resource = await run_blocking('scope',service._resolve,1,actor,context=context(),lane='control-io')
        state = KnowledgeBaseState(knowledge_id=1, knowledge_revision=resource.revision, manifest_revision='a'*64,
            embedding_model_id=2, files=[])
        client.inspect_knowledge_base.return_value = state
        yield SimpleNamespace(service=service, client=client, state=state, actor=actor, update=update, frames=[])
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


async def scan(s):
    return await s.service.scan(1,s.actor,s.frames.append,page_size=2,context=context())


async def test_report_uses_standard_runtime_and_model_reads_without_guessed_dimensions(inspection):
    s=inspection; result=await scan(s)
    assert result['files']==0 and result['embedding_dimensions']==2 and not result['issues']
    assert s.frames[0].actor_id=='user-a' and s.frames[0].manifest_revision=='a'*64
    assert s.client.get_model.await_count==2
    assert all(call.args[1:]==('user-a','tenant-a') for call in s.client.inspect_knowledge_base.await_args_list)


async def test_report_gets_vector_media_over_agentos_with_current_resource_revision(inspection):
    s = inspection
    s.client.describe_knowledge_collections = AsyncMock(return_value=KnowledgeCollectionsDescribed(items=[{
        "knowledge_id": 1, "expected_revision": s.state.knowledge_revision, "present": True, "metric": "cosine",
        "vector_media": {"text": 2, "image": 3, "unclassified": 4},
    }]))
    result = await s.service.scan(1, s.actor, s.frames.append, include_vector_media=True, context=context())
    assert result["vector_collection_present"] and result["vector_media"]["unclassified"] == 4
    query, user, tenant = s.client.describe_knowledge_collections.await_args.args
    assert query.include_vector_media and query.expected_revisions == {1: s.state.knowledge_revision}
    assert (user, tenant) == (s.actor.user_id, s.actor.tenant_id)


async def test_missing_dimensions_remain_unknown_and_do_not_select_another_model(inspection):
    s=inspection; s.client.get_model.return_value.embedding_dimensions=None
    result=await scan(s)
    assert result['embedding_dimensions'] is None and 'MODEL_DIMENSIONS_UNKNOWN' in result['issues']
    assert all(call.args[0]==2 for call in s.client.get_model.await_args_list)


async def test_permissions_revoked_before_request_prevent_runtime_reads(inspection):
    s=inspection; s.update('cleanse_memberships',delete_flag='Y')
    with pytest.raises(ScopeDenied): await scan(s)
    s.client.get_model.assert_not_awaited();s.client.inspect_knowledge_base.assert_not_awaited()


async def test_model_revision_changed_after_page_does_not_finish_scan(inspection):
    s=inspection; metadata=s.client.get_model.return_value
    s.client.get_model.side_effect=[metadata,metadata.model_copy(update={'revision':'v2'})]
    with pytest.raises(Conflict): await scan(s)


async def test_runtime_manifest_revision_changes_do_not_restart_traversal(inspection):
    s=inspection
    s.client.inspect_knowledge_base.side_effect=[s.state.model_copy(update={'next_cursor':'next'}),
                                               s.state.model_copy(update={'manifest_revision':'b'*64})]
    with pytest.raises(Conflict): await scan(s)
    assert len(s.frames)==1 and s.client.inspect_knowledge_base.await_count==2


async def test_stalled_model_call_obeys_total_context_and_cancels(inspection):
    import asyncio
    from time import monotonic
    s=inspection;closed=[]
    async def blocked(*args):
        try: await asyncio.Event().wait()
        finally: closed.append(True)
    s.client.get_model.side_effect=blocked
    operation=OperationContext('owned-runtime-inspection-timeout',monotonic()+0.1)
    with pytest.raises(DeadlineExceeded) as error:
        await s.service.scan(1,s.actor,s.frames.append,context=operation)
    assert error.value.operation_id==operation.operation_id and closed==[True]
    s.client.get_model.assert_awaited_once();s.client.inspect_knowledge_base.assert_not_awaited()


async def test_explicit_model_not_found_is_reported_without_guessing_a_replacement(inspection):
    s=inspection
    s.client.get_model.side_effect=RuntimeUpstreamError(404,b'{"code":"MODEL_NOT_FOUND"}',{})
    result=await scan(s)
    assert result['embedding_model'] is None and result['embedding_dimensions'] is None
    assert result['issues']==['MODEL_NOT_FOUND'] and s.client.get_model.await_count==2


async def test_unrecognized_404_is_not_treated_as_a_missing_model(inspection):
    s=inspection
    s.client.get_model.side_effect=RuntimeUpstreamError(404,b'{"code":"AGENTOS_OPERATION_NOT_FOUND"}',{})
    with pytest.raises(RuntimeUpstreamError): await scan(s)
    assert not s.frames
    s.client.inspect_knowledge_base.assert_not_awaited()
