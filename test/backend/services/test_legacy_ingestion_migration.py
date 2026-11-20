# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit migration composes live edit DAC, source evidence and standard AgentOS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import KnowledgeBaseState, KnowledgeJobState
from contracts.knowledge_ingestion import (
    INGESTION_DATASET,
    LEGACY_FILE_ID_OCCUPANCY,
    KnowledgeIngestionIntent,
    canonical_legacy_file_id,
)
from contracts.knowledge_maintenance import SourceFinding, SourceInspectionPage
from management.services.knowledge_base.legacy_migration import LegacyMigrationService
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, OperationContext
from pydantic import ValidationError

from infrastructure.rdb.knowledge_ingestion import (
    activate_legacy_file_identity,
    bind_legacy_file_id_occupancy,
    reserve_legacy_file_identity,
    restore_legacy_file_identity,
)
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


@pytest.mark.parametrize("evidence", ["current", "no-publication", "different-count", "different-job"])
async def test_publication_verification_needs_the_current_runtime_generation(migration, evidence):
    m = migration
    s = m.s
    plan = await m.service.plan(1, s.value.file_id, s.actor, legacy_quiesced=True, context=context())
    await m.service.admit(plan, s.actor, context=context())
    await run_blocking("fixture", s.port.patch, INGESTION_DATASET, plan.file_id, FieldPatch(set_values={
        "status": "COMPLETED", "stage": "COMPLETE", "runtime_status": "completed",
        "forward_task_id": "e" * 32, "processed_chunks": 2, "total_chunks": 2,
    }), context=context(), lane="control-io")
    before = s.row()
    s.client.inspect_knowledge_file.return_value = KnowledgeJobState(
        **plan._reference(), job_id=("f" if evidence == "different-job" else "e") * 32,
        status="completed", writer_ended=True, reconcile_required=False,
        processed_chunks=2, total_chunks=3 if evidence == "different-count" else 2,
        publication_confirmed=evidence != "no-publication",
    )
    if evidence == "current":
        verified = await m.service.verify_publication(plan, s.actor, context=context())
        assert verified["version"] == before["version"] and verified["ingestion_request"] == before["ingestion_request"]
    else:
        with pytest.raises(Conflict):
            await m.service.verify_publication(plan, s.actor, context=context())
    lookup, user, tenant = s.client.inspect_knowledge_file.await_args.args
    assert lookup.confirm_publication and lookup.job_id == "e" * 32
    assert (user, tenant) == (s.actor.user_id, s.actor.tenant_id)
    assert s.row() == before


@pytest.fixture
def historical(migration, records):
    s = migration.s
    port, engine, table = records
    old_id = 'archive-file-001'
    target_id = canonical_legacy_file_id(s.actor.tenant_id, 1, old_id)
    baseline = migration.source.page.side_effect()
    with engine.begin() as conn:
        conn.execute(table.update().where(table.c.file_id == s.value.file_id).values(file_id=old_id))
    row = port.get(INGESTION_DATASET, old_id, context=context())
    migration.source.page.side_effect = None
    migration.source.page.return_value = baseline.model_copy(update={'files': [baseline.files[0].model_copy(
        update={'file_id': old_id, 'issues': ['FILE_ID_NONCANONICAL']},
    )]})

    def occupied(actor, file_id, *, context):
        store = bind_legacy_file_id_occupancy(actor.user_id, file_id, engine)
        try:
            return store.get(LEGACY_FILE_ID_OCCUPANCY, file_id, context=context)['count'] > 0
        finally:
            store.close()

    migration.service.file_id_occupied = Mock(side_effect=occupied)
    return SimpleNamespace(m=migration, old_id=old_id, target_id=target_id, row=row, port=port, engine=engine, table=table)


async def test_historical_id_plan_keeps_the_ledger_and_produces_a_strict_runtime_reference(historical):
    h = historical
    s = h.m.s
    arguments = {'legacy_quiesced': True, 'map_legacy_file_id': True}
    plan = await h.m.service.plan(1, h.old_id, s.actor, context=context(), **arguments)

    assert plan.legacy_snapshot.previous_file_id == h.old_id
    assert plan.legacy_snapshot.lifecycle_revision == h.row['version']
    assert plan.cleanse_request().file_id == h.target_id
    assert h.m.service.file_id_occupied.call_count == 2
    with h.engine.connect() as conn:
        saved = conn.execute(h.table.select()).mappings().one()
        assert saved['file_id'] == h.old_id and saved['ingestion_request'] is None and saved['version'] == h.row['version']
    assert await h.m.service.plan(1, h.old_id, s.actor, context=context(), **arguments) == plan
    different_tenant = canonical_legacy_file_id('different-tenant', 1, h.old_id)
    assert different_tenant != h.target_id
    forged = {**plan.model_dump(mode='json'), 'file_id': different_tenant}
    with pytest.raises(ValidationError):
        KnowledgeIngestionIntent.model_validate(forged)
    with pytest.raises(Conflict):
        await h.m.service.execute(plan, s.actor, context=context(), coordinator=s.coordinator)
    s.cleanse.submit.assert_not_called()


async def test_target_present_in_deleted_foreign_row_is_unavailable(historical):
    h = historical
    with h.engine.begin() as conn:
        conn.execute(h.table.insert().values(
            file_id=h.target_id, tenant_id='another-tenant', delete_flag='Y', knowledge_id=2,
            index_name='another-kb', original_filename='other.txt', status='DELETED',
            source_generation=0, processing_attempt=0, version=0,
        ))
    with pytest.raises(Conflict):
        await h.m.service.plan(1, h.old_id, h.m.s.actor, legacy_quiesced=True,
            map_legacy_file_id=True, context=context())
    h.m.s.client.inspect_knowledge_base.assert_not_awaited()


async def test_mapping_checks_current_permission_and_never_accepts_implicit_or_late_collision(historical):
    h = historical
    s = h.m.s
    with pytest.raises(InvalidInput):
        await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, context=context())
    h.m.service.file_id_occupied.side_effect = [False, True]
    with pytest.raises(Conflict):
        await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True,
            map_legacy_file_id=True, context=context())
    assert h.m.service.file_id_occupied.call_count == 2
    s.update('cleanse_memberships', delete_flag='Y')
    h.m.service.file_id_occupied.reset_mock()
    with pytest.raises(ScopeDenied):
        await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True,
            map_legacy_file_id=True, context=context())
    h.m.service.file_id_occupied.assert_not_called()



@pytest.fixture
def reservation(historical, monkeypatch):
    from infrastructure.rdb import knowledge_ingestion

    h = historical
    table = knowledge_ingestion.legacy_file_identities.to_metadata(h.table.metadata, schema=None)
    monkeypatch.setattr(knowledge_ingestion, 'legacy_file_identities', table)
    table.create(h.engine)
    h.m.service.reserve_identity = lambda actor, plan, *, context: reserve_legacy_file_identity(
        actor, plan, h.engine, context=context,
    )
    h.m.service.activate_identity = lambda actor, plan, apply, *, context: activate_legacy_file_identity(
        actor, plan, apply, h.engine, context=context,
    )
    h.m.service.restore_identity = lambda actor, plan, restore, *, context: restore_legacy_file_identity(
        actor, plan, restore, h.engine, context=context,
    )
    return h, table


async def test_reservation_is_repeatable_and_cannot_start_ingestion(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    first = await h.m.service.reserve_file_id(plan, s.actor, context=context())
    assert await h.m.service.reserve_file_id(plan, s.actor, context=context()) == first
    assert first['original_file_id'] == h.old_id and first['standard_file_id'] == h.target_id

    with h.engine.connect() as connection:
        assert connection.execute(identities.select()).mappings().one()['created_by'] == s.actor.user_id
        assert connection.execute(h.table.select()).mappings().one()['ingestion_request'] is None
    s.cleanse.submit.assert_not_called()
    s.client.upload_knowledge_file.assert_not_awaited()


async def test_reservation_revalidates_after_a_stale_plan_and_accepts_fresh_evidence(reservation):
    h, identities = reservation
    s = h.m.s
    async def make_plan():
        return await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
            context=context())
    prior = await make_plan()
    original = await h.m.service.reserve_file_id(prior, s.actor, context=context())
    next_version = h.row['version'] + 1
    with h.engine.begin() as connection:
        connection.execute(h.table.update().where(h.table.c.file_id == h.old_id).values(version=next_version))
    h.m.source.page.return_value.files[0].lifecycle_revision = next_version
    with pytest.raises(Conflict):
        await h.m.service.reserve_file_id(prior, s.actor, context=context())
    fresh = await make_plan()
    updated = await h.m.service.reserve_file_id(fresh, s.actor, context=context())
    assert updated['standard_file_id'] == original['standard_file_id']
    assert updated['create_time'] == original['create_time']
    assert updated['lifecycle_revision'] == next_version and updated['plan_sha256'] != original['plan_sha256']
    with h.engine.connect() as connection:
        assert connection.execute(identities.select()).mappings().one()['lifecycle_revision'] == next_version


async def test_reservation_rechecks_source_version_inside_storage_transaction(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    store = h.m.service.reserve_identity
    def changed(actor, intent, *, context):
        with h.engine.begin() as connection:
            connection.execute(h.table.update().where(h.table.c.file_id == h.old_id).values(version=h.row['version'] + 1))
        return store(actor, intent, context=context)
    h.m.service.reserve_identity = changed
    with pytest.raises(Conflict):
        await h.m.service.reserve_file_id(plan, s.actor, context=context())
    with h.engine.connect() as connection:
        assert connection.execute(identities.select()).mappings().all() == []



async def test_activation_moves_the_row_and_admits_ingestion_once(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    with pytest.raises(Conflict):
        await h.m.service.activate_file_id(plan, s.actor, context=context())
    await h.m.service.reserve_file_id(plan, s.actor, context=context())

    activated = await h.m.service.activate_file_id(plan, s.actor, context=context())
    assert activated['file_id'] == h.target_id and activated['stage'] == 'INGEST_ACCEPTED'
    assert activated['version'] == h.row['version'] + 1
    assert activated['ingestion_request'] == plan.model_dump(mode='json')
    assert await h.m.service.activate_file_id(plan, s.actor, context=context()) == activated
    assert await h.m.service.inspect(plan, s.actor, context=context()) == activated

    with h.engine.connect() as conn:
        mapping = conn.execute(identities.select()).mappings().one()
        assert mapping['activated_at'] is not None and mapping['version'] == 2
        assert conn.execute(h.table.select()).mappings().one()['file_id'] == h.target_id
    s.cleanse.submit.assert_not_called()


async def test_activation_rolls_back_rekey_when_admission_cannot_commit(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    await h.m.service.reserve_file_id(plan, s.actor, context=context())
    original = h.m.service.activate_identity

    def fail_admission(actor, plan, apply, *, context):
        def fail_after_journaling(records, row):
            applied = apply(records, row)
            assert applied['file_id'] == h.target_id and applied['stage'] == 'INGEST_ACCEPTED'
            raise Conflict()
        return original(actor, plan, fail_after_journaling, context=context)

    h.m.service.activate_identity = fail_admission
    with pytest.raises(Conflict):
        await h.m.service.activate_file_id(plan, s.actor, context=context())
    with h.engine.connect() as conn:
        mapping = conn.execute(identities.select()).mappings().one()
        assert mapping['activated_at'] is None and mapping['version'] == 1
        row = conn.execute(h.table.select()).mappings().one()
        assert row['file_id'] == h.old_id and row['ingestion_request'] is None



async def test_mapped_restore_recovers_the_original_row_and_is_idempotent(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    await h.m.service.reserve_file_id(plan, s.actor, context=context())
    with pytest.raises(Conflict):
        await h.m.service.restore_file_id(plan, s.actor, context=context())
    await h.m.service.activate_file_id(plan, s.actor, context=context())
    restored = await h.m.service.restore_file_id(plan, s.actor, context=context())
    assert restored['file_id'] == h.old_id and restored['ingestion_request'] is None
    assert restored['status'] == h.row['status'] and restored['version'] == h.row['version'] + 2
    assert await h.m.service.restore_file_id(plan, s.actor, context=context()) == restored
    with h.engine.connect() as conn:
        mapping = conn.execute(identities.select()).mappings().one()
        assert mapping['activated_at'] is None and mapping['version'] == 3
        assert conn.execute(h.table.select()).mappings().one()['file_id'] == h.old_id
    s.cleanse.submit.assert_not_called()


async def test_mapped_restore_refuses_after_cleanse_reservation(reservation):
    h, identities = reservation
    s = h.m.s
    plan = await h.m.service.plan(1, h.old_id, s.actor, legacy_quiesced=True, map_legacy_file_id=True,
        context=context())
    await h.m.service.reserve_file_id(plan, s.actor, context=context())
    activated = await h.m.service.activate_file_id(plan, s.actor, context=context())
    with h.engine.begin() as conn:
        conn.execute(h.table.update().where(h.table.c.file_id == h.target_id).values(
            stage='CLEANSE_SUBMITTING', status='PROCESSING', version=activated['version'] + 1,
        ))
    with pytest.raises(Conflict):
        await h.m.service.restore_file_id(plan, s.actor, context=context())
    with h.engine.connect() as conn:
        assert conn.execute(identities.select()).mappings().one()['activated_at'] is not None
        current = conn.execute(h.table.select()).mappings().one()
        assert current['file_id'] == h.target_id and current['stage'] == 'CLEANSE_SUBMITTING'
