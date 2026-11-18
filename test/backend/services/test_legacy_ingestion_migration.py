# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit migration composes live edit DAC, source evidence and standard AgentOS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import KnowledgeBaseState
from contracts.knowledge_maintenance import SourceFinding, SourceInspectionPage
from management.services.knowledge_base.legacy_migration import LegacyMigrationService
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import FieldPatch, OperationContext

from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records as records,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
async def migration(setup):
    s=setup
    await run_blocking('fixture',s.port.patch,'knowledge_ingestion_files',s.value.file_id,
        FieldPatch(set_values={'status':'COMPLETED','stage':'COMPLETE','file_size':10}),context=context(),lane='control-io')
    s.client.get_model.return_value=ModelMetadata(model_id=2,model_type='embedding',display_name='embed',revision='model-v1',embedding_dimensions=2)
    s.client.inspect_knowledge_base=AsyncMock()
    sources=Mock()
    service=LegacyMigrationService(ports=s.ports,client=s.client,sources=sources,parser_version=s.value.parser_version)
    _,resource=await run_blocking('fixture',service._selected,1,s.value.file_id,s.actor,context(),lane='control-io')
    sources.page.side_effect=lambda *args,**kwargs: SourceInspectionPage(knowledge_id=1,index_name='kb-one',tenant_id='tenant-a',actor_id='user-a',
        knowledge_revision=resource.revision,files=[SourceFinding(file_id=s.value.file_id,lifecycle_revision=s.row()['version'],
        source_generation=0,candidate_source=s.value.source)])
    s.client.inspect_knowledge_base.return_value=KnowledgeBaseState(knowledge_id=1,knowledge_revision=resource.revision,
        manifest_revision='a'*64,embedding_model_id=2,files=[])
    return SimpleNamespace(s=s,service=service,source=sources)


async def test_plan_admit_repeat_and_pre_execution_restore_use_existing_lifecycle(migration):
    m=migration;s=m.s
    plan=await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=context())
    assert plan.legacy_snapshot.previous.status=='COMPLETED' and plan.source==s.value.source
    admitted=await m.service.admit(plan,s.actor,context=context())
    assert admitted['stage']=='INGEST_ACCEPTED' and admitted['ingestion_request']['legacy_snapshot']['previous']['status']=='COMPLETED'
    before=s.client.get_model.await_count
    repeated=await m.service.admit(plan,s.actor,context=context())
    assert repeated==admitted and s.client.get_model.await_count==before
    restored=await m.service.restore(plan,s.actor,context=context())
    assert restored['status']=='COMPLETED' and restored['ingestion_request'] is None and restored['process_task_id'] is None
    s.cleanse.submit.assert_not_called();s.client.upload_knowledge_file.assert_not_awaited()


async def test_live_source_change_or_old_task_reference_prevents_plan(migration):
    m=migration;s=m.s
    await run_blocking('fixture',s.port.patch,'knowledge_ingestion_files',s.value.file_id,
        FieldPatch(set_values={'process_task_id':'old-task'}),context=context(),lane='control-io')
    with pytest.raises(Conflict):await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=context())
    assert s.row()['ingestion_request'] is None


async def test_resource_permission_revocation_prevents_apply(migration):
    m=migration;s=m.s
    plan=await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=context())
    s.update('cleanse_memberships',delete_flag='Y')
    with pytest.raises(ScopeDenied):await m.service.admit(plan,s.actor,context=context())
    assert s.row()['ingestion_request'] is None


async def test_execute_uses_existing_coordinator_and_never_resubmits_a_reserved_child(migration):
    m=migration;s=m.s
    plan=await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=context())
    s.cleanse.submit.side_effect=lambda *args,**kwargs:s.child('queued')
    s.cleanse.inspect.side_effect=lambda *args,**kwargs:s.child('queued')
    first=await m.service.execute(plan,s.actor,context=context(),coordinator=s.coordinator)
    assert first['stage']=='CLEANSE_PENDING'
    await m.service.execute(plan,s.actor,context=context(),coordinator=s.coordinator)
    assert s.cleanse.submit.call_count==1 and s.cleanse.inspect.call_count==1
    assert s.row()['ingestion_request']['legacy_snapshot']==plan.legacy_snapshot.model_dump(mode='json')
    with pytest.raises(Conflict):await m.service.restore(plan,s.actor,context=context())
    s.client.upload_knowledge_file.assert_not_awaited()


async def test_model_wait_is_bounded_and_does_not_admit_or_retry(migration):
    import asyncio
    from time import monotonic
    m=migration;s=m.s;closed=[]
    async def blocked(*args,**kwargs):
        try:await asyncio.Event().wait()
        finally:closed.append(True)
    s.client.get_model.side_effect=blocked
    operation=OperationContext('owned-migration-timeout',monotonic()+0.05)
    with pytest.raises(DeadlineExceeded) as error:
        await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=operation)
    assert error.value.operation_id==operation.operation_id and closed==[True]
    assert s.client.get_model.await_count==1 and s.row()['ingestion_request'] is None


async def test_receipt_inspection_is_read_only_without_model_or_source_requests(migration):
    m=migration;s=m.s
    plan=await m.service.plan(1,s.value.file_id,s.actor,legacy_quiesced=True,context=context())
    await m.service.admit(plan,s.actor,context=context())
    before=s.row();calls=s.client.get_model.await_count;source_calls=m.source.page.call_count
    m.service.parser_version='new-parser-version'
    s.update('cleanse_knowledge',embedding_model_id=None)
    observed=await m.service.inspect(plan,s.actor,context=context())
    assert observed['version']==before['version'] and s.row()==before
    assert s.client.get_model.await_count==calls and m.source.page.call_count==source_calls
