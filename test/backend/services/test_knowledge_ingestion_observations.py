# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management persists child observations so read-only callers need no owner impersonation."""

import pytest
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.knowledge_cleanse import KnowledgeCleanseState
from nexent.storage.errors import Conflict

from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_journal import setup  # noqa: F401


def runtime_phase(s):
    journal, value, row, _, _ = s
    row = journal.begin_cleanse(
        journal.admit(value, row, context=context()), context=context()
    )
    child = KnowledgeCleanseState(
        **value._reference(), job_id=row["process_task_id"], status="queued"
    )
    row = journal.observe_cleanse(row, child, context=context())
    assert row["cleanse_status"] == "queued"
    row = journal.observe_cleanse(
        row, child.model_copy(update={"status": "running"}), context=context()
    )
    assert row["cleanse_status"] == "running"
    row, _ = journal.begin_runtime(
        row,
        child.model_copy(update={"status": "completed", "artifact": value.source}),
        context=context(),
    )
    return journal, value, row


def test_child_observation_is_persistent_and_identical_observation_has_no_write(setup):  # noqa: F811
    journal, value, row = runtime_phase(setup)
    child = KnowledgeJobState(
        **value._reference(),
        job_id=row["forward_task_id"],
        status="running",
        processed_chunks=1,
        total_chunks=3,
    )
    observed = journal.observe_runtime(row, child, context=context())
    assert (
        observed["cleanse_status"] == "completed"
        and observed["runtime_status"] == "running"
    )
    assert (observed["processed_chunks"], observed["total_chunks"]) == (1, 3)
    assert (
        journal.observe_runtime(observed, child, context=context())["version"]
        == observed["version"]
    )
    done = journal.observe_runtime(
        observed,
        child.model_copy(update={"status": "completed", "processed_chunks": 3}),
        context=context(),
    )
    assert (
        done["status"] == "COMPLETED"
        and done["runtime_status"] == "completed"
        and done["processed_chunks"] == 3
    )


def test_stale_progress_cannot_replace_newer_snapshot(setup):  # noqa: F811
    journal, value, row = runtime_phase(setup)
    child = KnowledgeJobState(
        **value._reference(),
        job_id=row["forward_task_id"],
        status="running",
        processed_chunks=2,
        total_chunks=3,
    )
    observed = journal.observe_runtime(row, child, context=context())
    with pytest.raises(Conflict):
        journal.observe_runtime(
            observed,
            child.model_copy(update={"processed_chunks": 1}),
            context=context(),
        )
    current = journal.record(row["file_id"], context=context())
    assert (
        current["processed_chunks"] == 2 and current["version"] == observed["version"]
    )


def test_failure_preserves_confirmed_counts_and_terminal_state(setup):  # noqa: F811
    journal, value, row = runtime_phase(setup)
    child = KnowledgeJobState(
        **value._reference(),
        job_id=row["forward_task_id"],
        status="running",
        processed_chunks=1,
        total_chunks=3,
    )
    observed = journal.observe_runtime(row, child, context=context())
    with pytest.raises(Conflict):
        journal.observe_runtime(
            observed, child.model_copy(update={"status": "queued"}), context=context()
        )
    failed = journal.observe_runtime(
        observed,
        child.model_copy(
            update={"status": "failed", "error_code": "VECTOR_WRITE_FAILED"}
        ),
        context=context(),
    )
    assert failed["status"] == "FAILED" and failed["runtime_status"] == "failed"
    assert failed["processed_chunks"] == 1 and failed["error_stage"] == "FORWARD"
    with pytest.raises(Conflict):
        journal.observe_runtime(
            failed,
            child.model_copy(update={"status": "completed", "processed_chunks": 3}),
            context=context(),
        )
