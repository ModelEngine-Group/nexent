# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for durable knowledge-base file lifecycle persistence."""

import contextlib
import importlib
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

lifecycle_db = importlib.import_module("management.db.knowledge_base.file_lifecycle")


def _session_context(session):
    @contextlib.contextmanager
    def _context():
        yield session

    return _context


def test_get_file_record_by_id_applies_tenant_index_and_visibility_filters(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    row = MagicMock(file_id="fid-3")
    query.first.return_value = row
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(lifecycle_db, "as_dict", lambda value: {"file_id": value.file_id})

    result = lifecycle_db.get_file_record(
        file_id="fid-3",
        tenant_id="tenant-1",
        index_name="kb-1",
        include_hidden=False,
    )

    assert result == {"file_id": "fid-3"}
    assert query.filter.call_count == 4


def test_get_file_record_by_legacy_object_and_empty_lookup(monkeypatch):
    assert lifecycle_db.get_file_record() is None

    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.first.return_value = None
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.get_file_record(object_name="knowledge_base/a.txt", include_hidden=True) is None
    assert query.filter.call_count == 1


def test_list_file_records_applies_tenant_and_hides_deleted_rows(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [MagicMock(file_id="fid-4")]
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(lifecycle_db, "as_dict", lambda value: {"file_id": value.file_id})

    assert lifecycle_db.list_file_records(index_name="kb-1", tenant_id="tenant-1") == [{"file_id": "fid-4"}]
    assert query.filter.call_count == 3

    query.filter.reset_mock()
    query.order_by.return_value.all.return_value = []
    assert lifecycle_db.list_file_records(index_name="kb-1", include_hidden=True) == []
    assert query.filter.call_count == 1


def test_fail_interrupted_file_tasks_reuses_failed_state(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.with_for_update.return_value = query
    processing = types.SimpleNamespace(
        file_id="processing",
        status="PROCESSING",
        stage="PROCESS",
        process_task_id="process-1",
        forward_task_id=None,
        version=1,
    )
    forwarding = types.SimpleNamespace(
        file_id="forwarding",
        status="FORWARDING",
        stage="FORWARD",
        process_task_id="process-2",
        forward_task_id="forward-2",
        version=4,
    )
    query.all.return_value = [processing, forwarding]
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(
        lifecycle_db,
        "as_dict",
        lambda value: {
            "file_id": value.file_id,
            "process_task_id": value.process_task_id,
            "forward_task_id": value.forward_task_id,
        },
    )

    records = lifecycle_db.fail_interrupted_file_tasks()

    assert [record["file_id"] for record in records] == ["processing", "forwarding"]
    assert processing.status == "FAILED"
    assert processing.error_stage == "PROCESS"
    assert processing.version == 2
    assert forwarding.status == "FAILED"
    assert forwarding.error_stage == "FORWARD"
    assert forwarding.version == 5
    _, ownership_filter, recovery_filter = query.filter.call_args.args
    assert ownership_filter.compare(lifecycle_db.KnowledgeFileLifecycle.ingestion_request.is_(None))
    assert "forward_task_id IS NOT NULL" in str(recovery_filter)


def test_list_uploading_files_created_before_scopes_recovery_to_owner(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [types.SimpleNamespace(file_id="uploading")]
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(lifecycle_db, "as_dict", lambda value: {"file_id": value.file_id})

    rows = lifecycle_db.list_uploading_files_created_before(
        datetime(2026, 9, 1),
        "nexent-config",
    )

    assert rows == [{"file_id": "uploading"}]
    query.order_by.assert_called_once()
    owner_filter = next(
        argument
        for argument in query.filter.call_args.args
        if getattr(argument.left, "name", None) == "upload_owner_service"
    )
    assert owner_filter.right.value == "nexent-config"


@pytest.mark.parametrize("upload_owner_service", [None, ""])
def test_list_uploading_files_created_before_rejects_missing_owner(
    monkeypatch,
    upload_owner_service,
):
    session = MagicMock()
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    with pytest.raises(ValueError, match="upload_owner_service is required"):
        lifecycle_db.list_uploading_files_created_before(
            datetime(2026, 9, 1),
            upload_owner_service,
        )

    session.query.assert_not_called()


def test_transition_file_record_updates_allowed_fields_and_version(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.with_for_update.return_value = query
    row = MagicMock(file_id="fid-5", version=2)
    query.first.return_value = row
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(lifecycle_db, "as_dict", lambda value: {"file_id": value.file_id, "version": value.version})

    result = lifecycle_db.transition_file_record(
        "fid-5",
        status="FAILED",
        stage="PROCESS",
        expected_statuses=("PROCESSING",),
        expected_version=2,
        updated_by="user-1",
        original_filename="renamed.pdf",
        error_code="PARSE_FAILED",
        error_message="bad input",
        ignored_field="must not be assigned",
    )

    assert result == {"file_id": "fid-5", "version": 3}
    assert row.status == "FAILED"
    assert row.stage == "PROCESS"
    assert row.error_code == "PARSE_FAILED"
    assert row.error_message == "bad input"
    assert row.updated_by == "user-1"
    assert row.original_filename == "renamed.pdf"
    assert "ignored_field" not in row.__dict__
    session.flush.assert_called_once()


def test_transition_file_record_returns_none_for_stale_row(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = None
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))
    monkeypatch.setattr(
        lifecycle_db,
        "as_dict",
        lambda value: {"file_id": value.file_id, "version": value.version},
    )

    assert lifecycle_db.transition_file_record("missing", expected_version=9) is None
    session.flush.assert_not_called()

    row = MagicMock(file_id="fid-7", version=0)
    query.first.return_value = row
    assert lifecycle_db.transition_file_record("fid-7") == {"file_id": "fid-7", "version": 1}
    assert row.version == 1


def test_delete_file_record_physically_removes_matching_row(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.delete.return_value = 1
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.delete_file_record(
        "fid-delete",
        expected_statuses=("DELETE_REQUESTED", "DELETED"),
    ) is True
    query.delete.assert_called_once_with(synchronize_session=False)


def test_delete_file_record_is_idempotent_when_row_is_missing(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.delete.return_value = 0
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.delete_file_record("fid-missing") is False


def test_delete_file_records_for_knowledge_base_only_removes_eligible_statuses(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.delete.return_value = 3
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.delete_file_records_for_knowledge_base(
        index_name="kb-1",
        tenant_id="tenant-1",
        knowledge_id=10,
    ) == 3
    assert query.filter.call_count == 3
    query.delete.assert_called_once_with(synchronize_session=False)
