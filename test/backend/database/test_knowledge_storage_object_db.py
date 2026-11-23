"""Unit tests for the knowledge-base source-object storage ledger DAL."""

from contextlib import nullcontext
import sys
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.database.db_models import KnowledgeStorageObject


client_module = types.ModuleType("backend.database.client")
client_module.as_dict = MagicMock(name="as_dict")
client_module.get_db_session = MagicMock(name="get_db_session")
previous_client_module = sys.modules.get("backend.database.client")
sys.modules["backend.database.client"] = client_module

from backend.database import knowledge_storage_object_db as storage_db

if previous_client_module is None:
    sys.modules.pop("backend.database.client", None)
else:
    sys.modules["backend.database.client"] = previous_client_module


def _row(**overrides):
    values = {
        "storage_object_id": 1,
        "tenant_id": "tenant-a",
        "knowledge_id": 10,
        "index_name": "index-a",
        "bucket_name": "bucket",
        "object_name": "knowledge_base/source.pdf",
        "raw_bytes": 300,
        "status": storage_db.COMMITTED_STATUS,
        "delete_flag": "N",
        "created_by": "user-a",
        "updated_by": "user-a",
        "create_time": None,
        "update_time": None,
    }
    values.update(overrides)
    return KnowledgeStorageObject(**values)


def _as_dict(row):
    return {
        column.name: getattr(row, column.name, None)
        for column in KnowledgeStorageObject.__table__.columns
    }


@pytest.fixture(autouse=True)
def patch_serializer(monkeypatch):
    monkeypatch.setattr(storage_db, "as_dict", _as_dict)


def _patch_session(monkeypatch, session):
    get_db_session = MagicMock(return_value=nullcontext(session))
    monkeypatch.setattr(storage_db, "get_db_session", get_db_session)
    return get_db_session


def _query_session(first=None):
    session = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.group_by.return_value = query
    query.order_by.return_value = query
    query.first.return_value = first
    session.query.return_value = query
    return session, query


def test_model_has_identity_constraint_and_active_indexes():
    table = KnowledgeStorageObject.__table__
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    indexes = {index.name: index for index in table.indexes}

    assert table.schema == "nexent"
    assert unique_constraints["uq_knowledge_storage_object_bucket_object"] == (
        "bucket_name",
        "object_name",
    )
    assert set(indexes) == {
        "idx_knowledge_storage_object_tenant_active",
        "idx_knowledge_storage_object_kb_active",
    }
    assert [column.name for column in indexes["idx_knowledge_storage_object_kb_active"].columns] == [
        "tenant_id",
        "knowledge_id",
    ]


def test_commit_storage_object_inserts_committed_row(monkeypatch):
    session, _ = _query_session()

    def assign_id(row):
        row.storage_object_id = 99

    session.add.side_effect = assign_id
    _patch_session(monkeypatch, session)

    result = storage_db.commit_storage_object(
        "tenant-a",
        10,
        "index-a",
        "bucket",
        "knowledge_base/source.pdf",
        300,
        created_by="user-a",
    )

    assert result["storage_object_id"] == 99
    assert result["status"] == "COMMITTED"
    assert result["raw_bytes"] == 300
    assert result["updated_by"] == "user-a"
    session.add.assert_called_once()
    session.flush.assert_called_once()


def test_commit_storage_object_replay_is_idempotent(monkeypatch):
    existing = _row()
    session, _ = _query_session(existing)
    _patch_session(monkeypatch, session)

    result = storage_db.commit_storage_object(
        "tenant-a",
        10,
        "index-a",
        "bucket",
        "knowledge_base/source.pdf",
        300,
    )

    assert result["storage_object_id"] == 1
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_different_object_names_are_committed_independently(monkeypatch):
    session, _ = _query_session()
    _patch_session(monkeypatch, session)

    first = storage_db.commit_storage_object(
        "tenant-a", 10, "index-a", "bucket", "knowledge_base/source.pdf", 300
    )
    second = storage_db.commit_storage_object(
        "tenant-a", 10, "index-a", "bucket", "knowledge_base/source-1.pdf", 300
    )

    assert first["object_name"] != second["object_name"]
    assert first["raw_bytes"] == second["raw_bytes"] == 300
    assert session.add.call_count == 2


@pytest.mark.parametrize(
    ("overrides", "call_overrides"),
    [
        ({"tenant_id": "tenant-b"}, {}),
        ({"knowledge_id": 11}, {}),
        ({"index_name": "index-b"}, {}),
        ({"raw_bytes": 301}, {}),
    ],
)
def test_commit_storage_object_rejects_different_ownership_or_size(
    monkeypatch,
    overrides,
    call_overrides,
):
    session, _ = _query_session(_row(**overrides))
    _patch_session(monkeypatch, session)
    payload = {
        "tenant_id": "tenant-a",
        "knowledge_id": 10,
        "index_name": "index-a",
        "bucket_name": "bucket",
        "object_name": "knowledge_base/source.pdf",
        "raw_bytes": 300,
        **call_overrides,
    }

    with pytest.raises(storage_db.StorageObjectConflictError):
        storage_db.commit_storage_object(**payload)


def test_commit_storage_object_resolves_concurrent_identical_insert(monkeypatch):
    first_session, _ = _query_session()
    first_session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    second_session, _ = _query_session(_row())
    get_db_session = MagicMock(
        side_effect=[nullcontext(first_session), nullcontext(second_session)]
    )
    monkeypatch.setattr(storage_db, "get_db_session", get_db_session)

    result = storage_db.commit_storage_object(
        "tenant-a",
        10,
        "index-a",
        "bucket",
        "knowledge_base/source.pdf",
        300,
    )

    assert result["storage_object_id"] == 1
    assert get_db_session.call_count == 2


def test_commit_storage_object_reraises_unresolved_integrity_error(monkeypatch):
    first_session, _ = _query_session()
    first_session.flush.side_effect = IntegrityError("insert", {}, Exception("failure"))
    second_session, _ = _query_session()
    monkeypatch.setattr(
        storage_db,
        "get_db_session",
        MagicMock(side_effect=[nullcontext(first_session), nullcontext(second_session)]),
    )

    with pytest.raises(IntegrityError):
        storage_db.commit_storage_object(
            "tenant-a",
            10,
            "index-a",
            "bucket",
            "knowledge_base/source.pdf",
            300,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", ""),
        ("index_name", " "),
        ("bucket_name", None),
        ("object_name", ""),
        ("knowledge_id", "10"),
        ("knowledge_id", True),
        ("raw_bytes", -1),
        ("raw_bytes", 1.5),
        ("raw_bytes", True),
    ],
)
def test_commit_storage_object_validates_input(field, value):
    payload = {
        "tenant_id": "tenant-a",
        "knowledge_id": 10,
        "index_name": "index-a",
        "bucket_name": "bucket",
        "object_name": "knowledge_base/source.pdf",
        "raw_bytes": 300,
    }
    payload[field] = value

    with pytest.raises(ValueError):
        storage_db.commit_storage_object(**payload)


def test_get_storage_object_filters_active_tenant_row(monkeypatch):
    row = _row()
    session, query = _query_session(row)
    _patch_session(monkeypatch, session)

    result = storage_db.get_storage_object(
        "tenant-a", "bucket", "knowledge_base/source.pdf"
    )

    assert result["tenant_id"] == "tenant-a"
    assert query.filter.call_count == 2


def test_get_storage_object_can_include_deleted_and_returns_none(monkeypatch):
    session, query = _query_session()
    _patch_session(monkeypatch, session)

    result = storage_db.get_storage_object(
        "tenant-a",
        "bucket",
        "knowledge_base/source.pdf",
        include_deleted=True,
    )

    assert result is None
    query.filter.assert_called_once()


def test_get_storage_object_by_identity_filters_active_row(monkeypatch):
    row = _row()
    session, query = _query_session(row)
    _patch_session(monkeypatch, session)

    result = storage_db.get_storage_object_by_identity(
        "bucket",
        "knowledge_base/source.pdf",
    )

    assert result["knowledge_id"] == 10
    assert result["tenant_id"] == "tenant-a"
    assert query.filter.call_count == 2


def test_get_storage_object_by_identity_can_include_deleted(monkeypatch):
    session, query = _query_session()
    _patch_session(monkeypatch, session)

    assert storage_db.get_storage_object_by_identity(
        "bucket",
        "knowledge_base/source.pdf",
        include_deleted=True,
    ) is None
    query.filter.assert_called_once()


def test_aggregate_committed_bytes_by_kb(monkeypatch):
    session, query = _query_session()
    query.all.return_value = [(10, 300), (11, 700), (12, None)]
    _patch_session(monkeypatch, session)

    result = storage_db.aggregate_committed_bytes_by_kb("tenant-a", [10, 11, 12])

    assert result == {10: 300, 11: 700, 12: 0}
    assert query.filter.call_count == 2
    query.group_by.assert_called_once()


def test_get_committed_source_bytes_by_object_names(monkeypatch):
    session, query = _query_session()
    query.all.return_value = [
        ("knowledge_base/source.pdf", 300),
        ("knowledge_base/source-1.pdf", 450),
    ]
    _patch_session(monkeypatch, session)

    result = storage_db.get_committed_source_bytes_by_object_names(
        tenant_id="tenant-a",
        knowledge_id=10,
        bucket_name="bucket",
        object_names=["knowledge_base/source.pdf", "knowledge_base/source-1.pdf"],
    )

    assert result == {
        "knowledge_base/source.pdf": 300,
        "knowledge_base/source-1.pdf": 450,
    }


def test_aggregate_committed_bytes_by_kb_empty_filter_avoids_database(monkeypatch):
    get_db_session = MagicMock()
    monkeypatch.setattr(storage_db, "get_db_session", get_db_session)

    assert storage_db.aggregate_committed_bytes_by_kb("tenant-a", []) == {}
    get_db_session.assert_not_called()


def test_get_tenant_committed_bytes(monkeypatch):
    session, query = _query_session()
    query.scalar.return_value = 1000
    _patch_session(monkeypatch, session)

    assert storage_db.get_tenant_committed_bytes("tenant-a") == 1000


def test_get_tenant_committed_bytes_normalizes_null(monkeypatch):
    session, query = _query_session()
    query.scalar.return_value = None
    _patch_session(monkeypatch, session)

    assert storage_db.get_tenant_committed_bytes("tenant-a") == 0


def test_list_committed_storage_objects_with_kb_filter(monkeypatch):
    rows = [_row(), _row(storage_object_id=2, object_name="knowledge_base/other.pdf")]
    session, query = _query_session()
    query.all.return_value = rows
    _patch_session(monkeypatch, session)

    result = storage_db.list_committed_storage_objects("tenant-a", knowledge_id=10)

    assert [item["storage_object_id"] for item in result] == [1, 2]
    assert query.filter.call_count == 2
    query.order_by.assert_called_once()


def test_list_committed_storage_objects_without_kb_filter(monkeypatch):
    session, query = _query_session()
    query.all.return_value = []
    _patch_session(monkeypatch, session)

    assert storage_db.list_committed_storage_objects("tenant-a") == []
    query.filter.assert_called_once()


def test_mark_storage_object_deleted(monkeypatch):
    row = _row()
    session, _ = _query_session(row)
    _patch_session(monkeypatch, session)

    assert storage_db.mark_storage_object_deleted(
        "tenant-a",
        "bucket",
        "knowledge_base/source.pdf",
        updated_by="user-b",
    )
    assert row.status == "DELETED"
    assert row.delete_flag == "Y"
    assert row.updated_by == "user-b"
    session.flush.assert_called_once()


@pytest.mark.parametrize(
    "row",
    [
        _row(status="DELETED", delete_flag="Y"),
        _row(status="COMMITTED", delete_flag="Y"),
    ],
)
def test_mark_storage_object_deleted_replay_is_idempotent(monkeypatch, row):
    session, _ = _query_session(row)
    _patch_session(monkeypatch, session)

    assert storage_db.mark_storage_object_deleted(
        "tenant-a", "bucket", "knowledge_base/source.pdf"
    )
    session.flush.assert_not_called()


def test_mark_storage_object_deleted_does_not_cross_tenants(monkeypatch):
    session, _ = _query_session()
    _patch_session(monkeypatch, session)

    assert not storage_db.mark_storage_object_deleted(
        "tenant-b", "bucket", "knowledge_base/source.pdf"
    )
    session.flush.assert_not_called()


def test_update_storage_object_raw_bytes(monkeypatch):
    row = _row()
    session, _ = _query_session(row)
    _patch_session(monkeypatch, session)

    assert storage_db.update_storage_object_raw_bytes(
        "tenant-a",
        "bucket",
        "knowledge_base/source.pdf",
        450,
        updated_by="repair-job",
    )
    assert row.raw_bytes == 450
    assert row.updated_by == "repair-job"
    session.flush.assert_called_once()


def test_update_storage_object_raw_bytes_replay_is_idempotent(monkeypatch):
    row = _row()
    session, _ = _query_session(row)
    _patch_session(monkeypatch, session)

    assert storage_db.update_storage_object_raw_bytes(
        "tenant-a", "bucket", "knowledge_base/source.pdf", 300
    )
    session.flush.assert_not_called()


def test_update_storage_object_raw_bytes_missing_row(monkeypatch):
    session, _ = _query_session()
    _patch_session(monkeypatch, session)

    assert not storage_db.update_storage_object_raw_bytes(
        "tenant-a", "bucket", "knowledge_base/source.pdf", 300
    )


def test_update_storage_object_raw_bytes_rejects_negative_size():
    with pytest.raises(ValueError):
        storage_db.update_storage_object_raw_bytes(
            "tenant-a", "bucket", "knowledge_base/source.pdf", -1
        )
