# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy admission stores the original state atomically before standard ingestion."""

import pytest
from contracts.knowledge_ingestion import INGESTION_DATASET, LegacyIngestionSnapshot
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import FieldPatch
from pydantic import ValidationError

from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records as records,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_contract import intent


@pytest.fixture
def legacy(records):
    port,_,_=records
    value=intent();journal=IngestionJournal(port)
    port.patch(INGESTION_DATASET,value.file_id,FieldPatch(set_values={'status':'COMPLETED','stage':'COMPLETE',
        'error_message':'original failure details','processed_chunks':3,'total_chunks':3}),context=context())
    row=journal.record(value.file_id,context=context())
    snapshot=LegacyIngestionSnapshot.capture(row,resource_revision='a'*64,legacy_quiesced=True)
    plan=value.model_copy(update={'legacy_snapshot':snapshot})
    return journal,plan,row


def test_completed_legacy_record_enters_standard_pipeline_with_original_snapshot(legacy):
    journal,plan,row=legacy
    admitted=journal.admit_legacy(plan,row,context=context())
    assert admitted['stage']=='INGEST_ACCEPTED' and admitted['processing_attempt']==1
    stored=journal.request(admitted)
    assert stored.legacy_snapshot.previous.error_message=='original failure details'
    assert stored.legacy_snapshot.previous.processed_chunks==3
    assert admitted['error_message'] is None and admitted['file_id']==row['file_id']
    assert journal.admit_legacy(plan,admitted,context=context())==admitted
    with pytest.raises(Conflict):journal.admit_legacy(plan,row,context=context())


@pytest.mark.parametrize('field,value',[('process_task_id','old-task'),('forward_task_id','old-task'),
    ('parent_task_id','old-task'),('deletion_request',{'scope':'full'})])
def test_unarchived_tasks_or_deletion_prevent_legacy_admission(legacy,field,value):
    journal,plan,row=legacy
    journal.records.patch(INGESTION_DATASET,row['file_id'],FieldPatch(set_values={field:value}),context=context())
    current=journal.record(row['file_id'],context=context())
    plan=plan.model_copy(update={'legacy_snapshot':LegacyIngestionSnapshot.capture(current,resource_revision='a'*64,legacy_quiesced=True)})
    with pytest.raises((Conflict,ScopeDenied)):journal.admit_legacy(plan,current,context=context())
    assert journal.record(row['file_id'],context=context())['ingestion_request'] is None


def test_original_user_and_exact_legacy_revision_are_required(legacy):
    journal,plan,row=legacy
    with pytest.raises(ScopeDenied):journal.admit_legacy(plan.model_copy(update={'user_id':'owner'}),row,context=context())
    altered=plan.model_copy(update={'legacy_snapshot':plan.legacy_snapshot.model_copy(update={'lifecycle_revision':999})})
    with pytest.raises(Conflict):journal.admit_legacy(altered,row,context=context())


def test_restoration_is_idempotent_and_retains_raw_original_error(legacy):
    journal,plan,row=legacy
    admitted=journal.admit_legacy(plan,row,context=context())
    assert admitted['error_message'] is None
    restored=journal.restore_legacy(plan,admitted,context=context())
    assert restored['error_message']=='original failure details' and restored['processed_chunks']==3
    assert restored['created_by']==row['created_by'] and restored['updated_by']=='user-a'
    assert journal.restore_legacy(plan,restored,context=context())==restored


def test_reservation_of_child_execution_forbids_sql_only_restoration(legacy):
    journal,plan,row=legacy
    admitted=journal.admit_legacy(plan,row,context=context())
    started=journal.begin_cleanse(admitted,context=context())
    with pytest.raises(Conflict):journal.restore_legacy(plan,started,context=context())
    assert journal.record(row['file_id'],context=context())['stage']==started['stage']


def test_oversize_archive_is_rejected_without_truncation_or_writes(legacy):
    journal,plan,row=legacy
    previous=plan.legacy_snapshot.previous.model_copy(update={'error_message':'x'*17000})
    snapshot=plan.legacy_snapshot.model_copy(update={'previous':previous})
    with pytest.raises(ValidationError):
        journal.admit_legacy(plan.model_copy(update={'legacy_snapshot':snapshot}),row,context=context())
    assert journal.record(row['file_id'],context=context())['ingestion_request'] is None


def test_absent_archive_preserves_normal_shape_and_never_enters_child_requests(legacy):
    _,plan,_=legacy
    assert 'legacy_snapshot' not in intent().model_dump()
    assert plan.legacy_snapshot.previous.error_message=='original failure details'
    assert 'task_archive_sha256' not in plan.legacy_snapshot.model_dump()
    assert 'task_references' not in plan.legacy_snapshot.model_dump()
    for request in (plan.cleanse_request(),plan.runtime_request(plan.source)):
        serialized=request.model_dump_json()
        assert 'legacy_snapshot' not in serialized and 'original failure details' not in serialized
