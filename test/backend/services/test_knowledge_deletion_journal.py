# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-INTENT-02/03: actual SI CAS, scope and child confirmation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.knowledge_deletion import DELETION_DATASET
from contracts.knowledge_ingestion import INGESTION_DATASET
from management.services.knowledge_base.deletion_journal import DeletionJournal
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import StorageScope, WriteOutcome, WriteReceipt

from infrastructure.rdb import knowledge_deletion as module
from infrastructure.rdb import knowledge_ingestion as ingestion
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_contract import intent
from test.backend.services.test_knowledge_ingestion_contract import (
    intent as upload_intent,
)


@pytest.fixture
def setup(monkeypatch):
    original = module.files
    table = sa.Table("deletion_files", sa.MetaData(), *[
        sa.Column(c.name, sa.JSON(none_as_null=True) if isinstance(c.type, sa.JSON) else c.type,
                  primary_key=c.primary_key, nullable=c.nullable)
        for c in original.c
    ])
    engine = sa.create_engine("sqlite://")
    table.create(engine)
    monkeypatch.setattr(module, "files", table)
    monkeypatch.setattr(ingestion, "files", table)
    value = intent()
    with engine.begin() as c:
        c.execute(table.insert(), {
            "file_id": value.file_id, "tenant_id": "tenant-a", "knowledge_id": 1,
            "index_name": value.index_name, "original_filename": value.filename,
            "object_name": value.object_name, "source_generation": value.file_version,
            "source_space": value.source.space, "source_key": value.source.key,
            "source_revision": value.source.version, "source_sha256": value.source.sha256,
            "status": "COMPLETED", "stage": "COMPLETE", "processing_attempt": 0,
            "version": 3, "delete_flag": "N",
        })
    owned = []

    def port(user="user-a", tenant="tenant-a", role="management"):
        record = module.bind_deletion_records(StorageScope(role, tenant, user, {DELETION_DATASET}), engine)
        owned.append(record)
        return record

    records = port()
    try:
        yield SimpleNamespace(records=records, port=port, journal=DeletionJournal(records), intent=value,
                              table=table, engine=engine,
                              row=lambda: records.get(DELETION_DATASET, value.file_id, context=context()))
    finally:
        for record in owned:
            record.close()
        engine.dispose()


def test_admission_is_immutable_idempotent_and_owned_by_current_actor(setup):
    s = setup
    original = s.row()
    admitted = s.journal.admit(s.intent, original, context=context())
    assert (admitted["status"], admitted["stage"], admitted["version"]) == ("DELETE_REQUESTED", "DELETE_ACCEPTED", 4)
    assert admitted["deletion_request"] == s.intent.model_dump(mode="json")
    assert admitted["updated_by"] == "user-a" and admitted["update_time"]
    assert s.journal.admit(s.intent, admitted, context=context()) == admitted
    with pytest.raises(Conflict):
        s.journal.admit(s.intent, original, context=context())
    with pytest.raises(Conflict):
        s.journal.admit(intent(scope="source_only"), admitted, context=context())
    with pytest.raises(ScopeDenied):
        DeletionJournal(s.port(user="other-user")).request(admitted)
    assert s.port(tenant="other").get(DELETION_DATASET, s.intent.file_id, context=context()) is None


def test_runtime_submission_and_source_cleanup_each_have_one_cas_owner(setup):
    s = setup
    admitted = s.journal.admit(s.intent, s.row(), context=context())
    pending, request = s.journal.begin_runtime(admitted, context=context())
    assert request == s.intent.runtime_request()
    with pytest.raises(Conflict):
        s.journal.begin_runtime(admitted, context=context())
    with pytest.raises(Conflict):
        s.journal.begin_source(pending, context=context())
    child = KnowledgeJobState(**s.intent.runtime_lookup("tenant-a").model_dump(), status="cleanup_pending")
    observed = s.journal.observe_runtime(pending, child, context=context())
    assert observed["stage"] == "DELETE_RUNTIME_PENDING"
    assert s.journal.observe_runtime(observed, child, context=context()) == observed
    with pytest.raises(ScopeDenied):
        s.journal.observe_runtime(observed, child.model_copy(update={"job_id": "f" * 32}), context=context())
    incomplete = child.model_copy(update={"status": "deleted"})
    assert s.journal.observe_runtime(observed, incomplete, context=context()) == observed
    runtime_done = s.journal.observe_runtime(observed, incomplete.model_copy(update={"physical_cleanup_complete": True,
                                                                                'processed_chunks': 0, 'total_chunks': 0}), context=context())
    assert runtime_done["stage"] == "DELETE_CLEANSE_PENDING"
    with pytest.raises(Conflict):
        s.journal.begin_source(runtime_done, context=context())
    with pytest.raises(Conflict):
        s.journal.confirm_cleanse_drained(runtime_done, physical_completion_confirmed=False, context=context())
    ready = s.journal.confirm_cleanse_drained(runtime_done, physical_completion_confirmed=True, context=context())
    deleting = s.journal.begin_source(ready, context=context())
    with pytest.raises(Conflict):
        s.journal.begin_source(ready, context=context())
    with pytest.raises(Conflict):
        s.journal.finish_source(deleting, physical_absence_confirmed=False, context=context())
    done = s.journal.finish_source(deleting, physical_absence_confirmed=True, context=context())
    assert done["status"] == "DELETED" and done["stage"] == "DELETE_DONE" and done["deleted_at"]
    assert s.journal.request(done) == s.intent
    with pytest.raises(Conflict):
        s.journal.observe_runtime(done, child, context=context())


def test_source_only_preserves_vectors_and_clears_only_live_source_pointer(setup):
    s = setup
    value = intent(scope="source_only")
    admitted = s.journal.admit(value, s.row(), context=context())
    assert admitted["status"] == "COMPLETED"
    with pytest.raises(Conflict):
        s.journal.begin_runtime(admitted, context=context())
    deleting = s.journal.begin_source(admitted, context=context())
    final = s.journal.finish_source(deleting, physical_absence_confirmed=True, context=context())
    assert final["status"] == "COMPLETED" and final["stage"] == "SOURCE_DELETED"
    assert final["source_key"] is None and final["object_name"] == value.object_name
    assert final["deletion_request"]["source"] == value.source.model_dump(mode="json")
    assert s.journal.admit(value, final, context=context()) == final


def test_source_only_fence_rejects_late_ingestion_even_while_file_is_completed(setup):
    s = setup
    scope = StorageScope("management", "tenant-a", "user-a", {INGESTION_DATASET})
    port = ingestion.bind_ingestion_records(scope, s.engine)
    try:
        s.journal.admit(intent(scope="source_only"), s.row(), context=context())
        row = port.get(INGESTION_DATASET, s.intent.file_id, context=context())
        with pytest.raises(Conflict):
            IngestionJournal(port).admit(upload_intent(), row, context=context())
    finally:
        port.close()


def test_unknown_write_does_not_replay_or_return_a_successful_phase(setup, monkeypatch):
    s = setup
    patch = Mock(return_value=WriteReceipt("unknown", False, outcome=WriteOutcome.UNKNOWN))
    monkeypatch.setattr(s.records, "patch", patch)
    with pytest.raises(OutcomeUnknown):
        s.journal.admit(s.intent, s.row(), context=context())
    assert patch.call_count == 1
    assert s.row()["deletion_request"] is None


@pytest.mark.parametrize("field,value", [("source_generation", 1), ("object_name", "other"), ("source_revision", "v2")])
def test_stale_generation_or_source_snapshot_cannot_install_fence(setup, field, value):
    s = setup
    with s.engine.begin() as c:
        c.execute(s.table.update().values({field: value}))
    with pytest.raises(Conflict):
        s.journal.admit(s.intent, s.row(), context=context())
    assert s.row()["deletion_request"] is None



def test_runtime_role_cannot_open_or_read_management_deletion_dataset(setup):
    with pytest.raises(ScopeDenied):
        port = setup.port(role="runtime")
        port.get(DELETION_DATASET, setup.intent.file_id, context=context())



def test_completed_source_only_can_be_followed_by_full_deletion_owned_by_another_authorized_editor(setup):
    s = setup
    source = s.journal.admit(intent(scope="source_only"), s.row(), context=context())
    deleting = s.journal.begin_source(source, context=context())
    final = s.journal.finish_source(deleting, physical_absence_confirmed=True, context=context())
    other = DeletionJournal(s.port(user="editor-b"))
    full = intent(user_id="editor-b", source=None)
    admitted = other.admit(full, final, context=context())
    assert admitted["status"] == "DELETE_REQUESTED"
    assert other.request(admitted) == full
    _, request = other.begin_runtime(admitted, context=context())
    assert request == full.runtime_request()
    with pytest.raises(Conflict):
        s.journal.finish_source(deleting, physical_absence_confirmed=True, context=context())



def test_confirmed_write_with_lost_read_remains_unknown_and_keeps_the_fence(setup, monkeypatch):
    s = setup
    original = s.row()
    monkeypatch.setattr(s.records, "get", Mock(return_value=None))
    with pytest.raises(OutcomeUnknown):
        s.journal.admit(s.intent, original, context=context())
    with s.engine.connect() as connection:
        row = connection.execute(sa.select(s.table.c.status, s.table.c.stage)).one()
    assert tuple(row) == ("DELETE_REQUESTED", "DELETE_ACCEPTED")


@pytest.mark.parametrize("status", ["UPLOADING", "UPLOADED", "PROCESSING", "FORWARDING", "FAILED"])
def test_source_only_requires_completed_ingestion(setup, status):
    s = setup
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(status=status))
    with pytest.raises(Conflict):
        s.journal.admit(intent(scope="source_only"), s.row(), context=context())
    assert s.row()["deletion_request"] is None



@pytest.mark.parametrize("stage", ["SOURCE_UPLOAD", "SOURCE_CONFIRMED", "SOURCE_ACCOUNTED"])
def test_started_publication_keeps_its_owner_until_source_reconciliation_finishes(setup, stage):
    s = setup
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(status="UPLOADING", stage=stage))
    with pytest.raises(Conflict):
        s.journal.admit(s.intent, s.row(), context=context())
    assert s.row()["stage"] == stage and s.row()["deletion_request"] is None


def test_unstarted_upload_can_be_fenced_before_any_source_write(setup):
    s = setup
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(status="UPLOADING", stage="UPLOAD", source_space=None,
                           source_key=None, source_revision=None, source_sha256=None))
    row = s.journal.admit(intent(source=None), s.row(), context=context())
    assert row["status"] == "DELETE_REQUESTED" and row["stage"] == "DELETE_ACCEPTED"
