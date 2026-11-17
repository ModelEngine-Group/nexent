# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management's domain journal fences child submissions and late results."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeJobState, knowledge_job_id
from contracts.knowledge_cleanse import KnowledgeCleanseState, cleanse_job_id
from contracts.knowledge_ingestion import INGESTION_DATASET
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import WriteOutcome, WriteReceipt

from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_contract import intent


@pytest.fixture
def setup(records):  # noqa: F811
    port, engine, table = records
    value = intent()
    journal = IngestionJournal(port)
    row = port.get(INGESTION_DATASET, value.file_id, context=context())
    return journal, value, row, engine, table


def test_admission_is_durable_idempotent_and_rejects_changed_snapshot(setup):
    journal, value, row, _, _ = setup
    admitted = journal.admit(value, row, context=context())
    assert admitted["stage"] == "INGEST_ACCEPTED" and admitted["status"] == "UPLOADED"
    assert admitted["processing_attempt"] == 1
    assert admitted["process_task_id"] == cleanse_job_id(
        value.cleanse_request(), "tenant-a", "user-a"
    )
    assert admitted["ingestion_request"] == value.model_dump(mode="json")
    assert journal.admit(value, admitted, context=context()) == admitted
    with pytest.raises(Conflict):
        journal.admit(
            value.model_copy(update={"chunking_strategy": "none"}),
            admitted,
            context=context(),
        )
    with pytest.raises(Conflict):
        journal.admit(value, row, context=context())


def test_stages_reserve_each_child_once_and_preserve_its_identity(setup):
    journal, value, row, _, _ = setup
    admitted = journal.admit(value, row, context=context())
    submitting = journal.begin_cleanse(admitted, context=context())
    with pytest.raises(Conflict):
        journal.begin_cleanse(admitted, context=context())
    child = KnowledgeCleanseState(
        **value._reference(), job_id=submitting["process_task_id"], status="queued"
    )
    pending = journal.observe_cleanse(submitting, child, context=context())
    assert pending["stage"] == "CLEANSE_PENDING"
    assert journal.observe_cleanse(pending, child, context=context()) == pending
    completed = child.model_copy(
        update={"status": "completed", "artifact": value.source}
    )
    forwarding, request = journal.begin_runtime(pending, completed, context=context())
    assert (
        forwarding["stage"] == "RUNTIME_SUBMITTING"
        and forwarding["status"] == "FORWARDING"
    )
    assert forwarding["forward_task_id"] == knowledge_job_id(
        request, "tenant-a", "user-a"
    )
    with pytest.raises(Conflict):
        journal.begin_runtime(pending, completed, context=context())
    runtime = KnowledgeJobState(
        **value._reference(), job_id=forwarding["forward_task_id"], status="queued"
    )
    accepted = journal.observe_runtime(forwarding, runtime, context=context())
    assert accepted["stage"] == "RUNTIME_PENDING"
    final = journal.observe_runtime(
        accepted, runtime.model_copy(update={"status": "completed"}), context=context()
    )
    assert final["status"] == "COMPLETED" and final["completed_at"]


def test_foreign_actor_child_or_replaced_source_cannot_advance(setup):
    journal, value, row, engine, table = setup
    with pytest.raises(ScopeDenied):
        journal.admit(
            value.model_copy(update={"user_id": "foreign"}), row, context=context()
        )
    admitted = journal.begin_cleanse(
        journal.admit(value, row, context=context()), context=context()
    )
    child = KnowledgeCleanseState(
        **value._reference(), job_id="f" * 32, status="queued"
    )
    with pytest.raises(ScopeDenied):
        journal.observe_cleanse(admitted, child, context=context())
    with engine.begin() as conn:
        conn.execute(
            table.update().values(source_generation=1, version=table.c.version + 1)
        )
    replaced = journal.records.get(INGESTION_DATASET, value.file_id, context=context())
    with pytest.raises(Conflict):
        journal.observe_cleanse(
            replaced,
            child.model_copy(update={"job_id": admitted["process_task_id"]}),
            context=context(),
        )


def test_delete_and_unknown_write_do_not_allow_late_projection(setup):
    journal, value, row, engine, table = setup
    admitted = journal.admit(value, row, context=context())
    with engine.begin() as conn:
        conn.execute(
            table.update().values(
                status="DELETE_REQUESTED", version=table.c.version + 1
            )
        )
    with pytest.raises(Conflict):
        journal.begin_cleanse(admitted, context=context())
    journal.records.patch = Mock(
        return_value=WriteReceipt("unknown", False, outcome=WriteOutcome.UNKNOWN)
    )
    with pytest.raises(OutcomeUnknown):
        journal.begin_cleanse(admitted, context=context())
    assert journal.records.patch.call_count == 1


def test_failed_child_is_projected_without_retrying_or_exposing_raw_error(setup):
    journal, value, row, _, _ = setup
    submitting = journal.begin_cleanse(
        journal.admit(value, row, context=context()), context=context()
    )
    child = KnowledgeCleanseState(
        **value._reference(),
        job_id=submitting["process_task_id"],
        status="failed",
        error_code="PARSER_FAILED",
    )
    final = journal.observe_cleanse(submitting, child, context=context())
    assert final["status"] == "FAILED" and final["error_code"] == "PARSER_FAILED"
    assert final["failed_at"] and final["error_stage"] == "PROCESS"
    assert final["error_message"] is None
    with pytest.raises(Conflict):
        journal.begin_cleanse(final, context=context())
