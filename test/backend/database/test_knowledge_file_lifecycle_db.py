"""Unit tests for durable knowledge-base file lifecycle persistence."""

import contextlib
import importlib
import sys
import types
from unittest.mock import MagicMock


def _install_storage_import_stubs() -> None:
    """Keep database tests independent from the SDK's optional model stack."""
    nexent_pkg = sys.modules.setdefault("nexent", types.ModuleType("nexent"))
    storage_pkg = sys.modules.setdefault("nexent.storage", types.ModuleType("nexent.storage"))
    storage_pkg.__path__ = []
    factory = sys.modules.setdefault(
        "nexent.storage.storage_client_factory",
        types.ModuleType("nexent.storage.storage_client_factory"),
    )
    factory.create_storage_client_from_config = lambda *_args, **_kwargs: MagicMock()
    factory.MinIOStorageConfig = type("MinIOStorageConfig", (), {})
    setattr(nexent_pkg, "storage", storage_pkg)
    setattr(storage_pkg, "storage_client_factory", factory)


_install_storage_import_stubs()
lifecycle_db = importlib.import_module("backend.database.knowledge_file_lifecycle_db")


def _session_context(session):
    @contextlib.contextmanager
    def _context():
        yield session

    return _context


def test_create_file_record_persists_uploading_row(monkeypatch):
    session = MagicMock()
    row = MagicMock(file_id="fid-1")
    monkeypatch.setattr(lifecycle_db, "KnowledgeFileLifecycle", MagicMock(return_value=row))
    monkeypatch.setattr(lifecycle_db, "as_dict", lambda value: {"file_id": value.file_id})
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    result = lifecycle_db.create_file_record(
        file_id="fid-1",
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        original_filename="broken.pdf",
        object_name="knowledge_base/object.pdf",
    )

    assert result == {"file_id": "fid-1"}
    session.add.assert_called_once_with(row)
    session.flush.assert_called_once_with()


def test_create_file_records_uses_one_transaction_for_the_whole_batch(monkeypatch):
    session = MagicMock()
    rows = [MagicMock(file_id="fid-1"), MagicMock(file_id="fid-2")]
    lifecycle_model = MagicMock(side_effect=rows)
    monkeypatch.setattr(lifecycle_db, "KnowledgeFileLifecycle", lifecycle_model)
    monkeypatch.setattr(
        lifecycle_db,
        "as_dict",
        lambda value: {"file_id": value.file_id},
    )
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    result = lifecycle_db.create_file_records([
        {
            "file_id": "fid-1",
            "tenant_id": "tenant-1",
            "knowledge_id": 10,
            "index_name": "kb-1",
            "original_filename": "a.pdf",
        },
        {
            "file_id": "fid-2",
            "tenant_id": "tenant-1",
            "knowledge_id": 10,
            "index_name": "kb-1",
            "original_filename": "b.pdf",
        },
    ])

    assert result == [{"file_id": "fid-1"}, {"file_id": "fid-2"}]
    session.add_all.assert_called_once_with(rows)
    session.add.assert_not_called()
    session.flush.assert_called_once_with()


def test_create_file_records_returns_empty_for_empty_batch(monkeypatch):
    """Empty uploads should not open a database transaction."""
    session = MagicMock()
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.create_file_records([]) == []
    session.add_all.assert_not_called()
    session.flush.assert_not_called()


def test_delete_tombstone_updates_existing_row(monkeypatch):
    existing = {"file_id": "fid-2", "status": "FAILED"}
    transition = MagicMock(return_value={"file_id": "fid-2", "status": "DELETE_REQUESTED"})
    monkeypatch.setattr(lifecycle_db, "get_file_record", MagicMock(return_value=existing))
    monkeypatch.setattr(lifecycle_db, "transition_file_record", transition)

    result = lifecycle_db.create_delete_tombstone(
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        object_name="knowledge_base/object.pdf",
        requested_by="user-1",
    )

    assert result["status"] == "DELETE_REQUESTED"
    transition.assert_called_once()
    assert transition.call_args.kwargs["updated_by"] == "user-1"
    assert "delete_requested_at" not in transition.call_args.kwargs
    assert "delete_requested_by" not in transition.call_args.kwargs


def test_delete_tombstone_keeps_existing_deleted_row(monkeypatch):
    """Repeated legacy deletion must not transition an already hidden row."""
    existing = {"file_id": "fid-deleted", "status": "DELETED"}
    transition = MagicMock()
    monkeypatch.setattr(lifecycle_db, "get_file_record", MagicMock(return_value=existing))
    monkeypatch.setattr(lifecycle_db, "transition_file_record", transition)

    result = lifecycle_db.create_delete_tombstone(
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        object_name="knowledge_base/object.pdf",
    )

    assert result == existing
    transition.assert_not_called()


def test_new_file_id_is_opaque_and_stable_length():
    file_id = lifecycle_db.new_file_id()
    assert len(file_id) == 32
    assert file_id.isalnum()


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


def test_delete_tombstone_creates_and_finalizes_missing_row(monkeypatch):
    monkeypatch.setattr(lifecycle_db, "get_file_record", MagicMock(return_value=None))
    created = {"file_id": "fid-6", "status": "DELETE_REQUESTED"}
    monkeypatch.setattr(lifecycle_db, "create_file_record", MagicMock(return_value=created))
    transition = MagicMock(return_value={"file_id": "fid-6", "status": "DELETE_REQUESTED"})
    monkeypatch.setattr(lifecycle_db, "transition_file_record", transition)

    result = lifecycle_db.create_delete_tombstone(
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        object_name="knowledge_base/missing.txt",
        original_filename="missing.txt",
        requested_by="user-1",
    )

    assert result == {"file_id": "fid-6", "status": "DELETE_REQUESTED"}
    assert lifecycle_db.create_file_record.call_args.kwargs["status"] == "DELETE_REQUESTED"
    transition.assert_called_once()
    assert transition.call_args.args == ("fid-6",)
    assert "deleted_at" not in transition.call_args.kwargs
