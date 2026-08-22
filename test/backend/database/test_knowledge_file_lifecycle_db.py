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
maintenance = importlib.import_module("backend.services.knowledge_file_maintenance")


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


def test_delete_tombstone_updates_existing_row(monkeypatch):
    existing = {"file_id": "fid-2", "status": "FAILED"}
    transition = MagicMock(return_value={"file_id": "fid-2", "status": "DELETED"})
    monkeypatch.setattr(lifecycle_db, "get_file_record", MagicMock(return_value=existing))
    monkeypatch.setattr(lifecycle_db, "transition_file_record", transition)

    result = lifecycle_db.create_delete_tombstone(
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        object_name="knowledge_base/object.pdf",
        requested_by="user-1",
    )

    assert result["status"] == "DELETED"
    transition.assert_called_once()
    assert transition.call_args.kwargs["delete_requested_by"] == "user-1"


def test_new_file_id_is_opaque_and_stable_length():
    file_id = lifecycle_db.new_file_id()
    assert len(file_id) == 32
    assert file_id.isalnum()


def test_cleanup_uses_advisory_lock_and_removes_terminal_cache_rows(monkeypatch):
    session = MagicMock()
    session.execute.return_value.scalar.return_value = True
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    row = MagicMock()
    query.all.return_value = [row]
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    result = lifecycle_db.cleanup_expired_file_records(retention_days=30, batch_size=1)

    assert result == 1
    session.delete.assert_called_once_with(row)
    session.execute.assert_called_once()


def test_cleanup_skips_when_another_worker_holds_advisory_lock(monkeypatch):
    session = MagicMock()
    session.execute.return_value.scalar.return_value = False
    monkeypatch.setattr(lifecycle_db, "get_db_session", _session_context(session))

    assert lifecycle_db.cleanup_expired_file_records() == 0
    session.query.assert_not_called()


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


def test_delete_tombstone_creates_and_finalizes_missing_row(monkeypatch):
    monkeypatch.setattr(lifecycle_db, "get_file_record", MagicMock(return_value=None))
    created = {"file_id": "fid-6", "status": "DELETED"}
    monkeypatch.setattr(lifecycle_db, "create_file_record", MagicMock(return_value=created))
    transition = MagicMock(return_value={"file_id": "fid-6", "status": "DELETED"})
    monkeypatch.setattr(lifecycle_db, "transition_file_record", transition)

    result = lifecycle_db.create_delete_tombstone(
        tenant_id="tenant-1",
        knowledge_id=10,
        index_name="kb-1",
        object_name="knowledge_base/missing.txt",
        original_filename="missing.txt",
        requested_by="user-1",
    )

    assert result == {"file_id": "fid-6", "status": "DELETED"}
    transition.assert_called_once()
    assert transition.call_args.args == ("fid-6",)


def test_maintenance_loop_start_stop_and_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(maintenance, "cleanup_expired_file_records", lambda **kwargs: calls.append(kwargs) or 1)
    monkeypatch.setattr(maintenance.time, "sleep", lambda _seconds: setattr(maintenance, "_running", False))
    maintenance._running = True
    maintenance._run_loop()
    assert calls == [{"retention_days": maintenance.KB_FILE_LIFECYCLE_RETENTION_DAYS}]

    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs)

    monkeypatch.setattr(maintenance.threading, "Thread", FakeThread)
    maintenance._running = False
    maintenance._thread = None
    maintenance.start()
    maintenance.start()
    assert len(started) == 1
    maintenance.stop()
    assert maintenance._running is False


def test_maintenance_loop_logs_database_failure(monkeypatch):
    monkeypatch.setattr(maintenance, "cleanup_expired_file_records", MagicMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(maintenance.time, "sleep", lambda _seconds: setattr(maintenance, "_running", False))
    logger = MagicMock()
    monkeypatch.setattr(maintenance, "logger", logger)
    maintenance._running = True
    maintenance._run_loop()
    logger.warning.assert_called_once()
