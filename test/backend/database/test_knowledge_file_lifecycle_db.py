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
