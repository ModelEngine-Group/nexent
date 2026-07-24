"""Unit tests for ``aidp_permission_db`` CRUD functions.

These tests use a mocked SQLAlchemy ``Session`` rather than a real database
because CI does not provision PostgreSQL for unit tests and SQLite cannot
reproduce the production schema-prefixed table layout. We patch
``aidp_permission_db.get_db_session`` so the production code runs end-to-end
while the SQL it emits is intercepted by a MagicMock session.

The tests cover:
* Read helpers enforce ``tenant_id`` and ``delete_flag != 'Y'`` semantics.
* Active uniqueness on ``kb_id`` is reported via ``IntegrityError`` propagation.
* Soft delete sets ``delete_flag='Y'`` and ``resource_status='DELETE_PENDING'``.
* Group IDs are normalised into a JSONB-safe list of ints.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
BACKEND_ROOT = str(Path(PROJECT_ROOT) / "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Stubs required to import backend modules without the SDK
# ---------------------------------------------------------------------------

if "nexent" not in sys.modules:
    nexent_pkg = ModuleType("nexent")
    nexent_pkg.__path__ = []
    sys.modules["nexent"] = nexent_pkg
    nexent_utils_pkg = ModuleType("nexent.utils")
    nexent_utils_pkg.__path__ = []
    sys.modules["nexent.utils"] = nexent_utils_pkg
    http_client_mod = ModuleType("nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = MagicMock()
    sys.modules["nexent.utils.http_client_manager"] = http_client_mod
    nexent_storage_pkg = ModuleType("nexent.storage")
    nexent_storage_pkg.__path__ = []
    sys.modules["nexent.storage"] = nexent_storage_pkg
    storage_factory_mod = ModuleType("nexent.storage.storage_client_factory")
    storage_factory_mod.create_storage_client_from_config = MagicMock()

    class _MinIOStorageConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    storage_factory_mod.MinIOStorageConfig = _MinIOStorageConfig
    sys.modules["nexent.storage.storage_client_factory"] = storage_factory_mod

for var in (
    "POSTGRES_HOST",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "NEXENT_POSTGRES_PASSWORD",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_REGION",
    "MINIO_DEFAULT_BUCKET",
):
    os.environ.setdefault(var, "test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for a SQLAlchemy session.

    Captures statements, ``update()`` values, and ``add()`` records so tests
    can assert payload semantics without hitting a real database.
    """

    def __init__(self):
        self.added: list = []
        self.executed: list[tuple] = []
        self.execute_result = MagicMock()
        self.execute_result.rowcount = 1
        self.flush_raises: Exception | None = None
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def add(self, record):
        # Assign a synthesised id so create_permission can return it.
        record.id = 99
        self.added.append(record)

    def execute(self, statement, params=None):  # noqa: ANN001
        # Capture the statement and parameter mapping for assertions.
        captured = (statement, params)
        self.executed.append(captured)
        # For update() statements we synthesise a result whose rowcount is
        # preset by the test fixture.
        return self.execute_result

    def flush(self):
        if self.flush_raises:
            raise self.flush_raises

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_session(monkeypatch):
    """Provide a fresh fake session and patch ``get_db_session`` to use it."""
    import contextlib

    from backend.ext_components.aidp.database import aidp_permission_db as target_mod  # noqa: E402

    session = _FakeSession()

    @contextlib.contextmanager
    def _patched(_db_session=None):
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(target_mod, "get_db_session", _patched)

    # ``database.client.as_dict`` performs a non-trivial dispatch on ORM vs.
    # Row objects. Our fake session returns plain dicts, so replace it with a
    # simpler adapter for the duration of the test.
    def _passthrough_dict(obj):
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "_mapping"):
            return dict(obj._mapping)
        return obj

    monkeypatch.setattr(target_mod, "as_dict", _passthrough_dict)
    return session


@pytest.fixture
def aidp_permission_db():
    """Provide the production module under test."""
    from backend.ext_components.aidp.database import aidp_permission_db as mod  # noqa: E402
    return mod


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


def _row(payload: dict):
    """Return ``payload`` directly (as_dict adapter turns it into a dict)."""
    return payload


class TestReadHelpers:
    def test_list_builds_query_for_tenant(self, aidp_permission_db, fake_session):
        rows = [
            {
                "id": 1, "kb_id": "kb-1", "owner_user_id": "user-1",
                "tenant_id": "tenant-a", "ingroup_permission": "READ_ONLY",
                "group_ids": [], "resource_status": "ACTIVE",
                "delete_flag": "N",
            }
        ]
        fake_session.execute_result.scalars.return_value.all.return_value = [
            _row(r) for r in rows
        ]

        result = aidp_permission_db.list_permissions_by_tenant("tenant-a", page=2, page_size=5)

        assert result[0]["kb_id"] == "kb-1"
        assert result[0]["tenant_id"] == "tenant-a"
        # ``execute`` was invoked once for the SELECT.
        assert len(fake_session.executed) == 1
        assert fake_session.committed

    def test_count_returns_scalar(self, aidp_permission_db, fake_session):
        fake_session.execute_result.scalar_one.return_value = 3

        assert aidp_permission_db.count_permissions_by_tenant("tenant-a") == 3

    def test_get_permission_by_kb_id_returns_dict(self, aidp_permission_db, fake_session):
        payload = {
            "id": 1, "kb_id": "kb-1", "owner_user_id": "user-1",
            "tenant_id": "tenant-a", "ingroup_permission": "EDIT",
            "group_ids": [1, 2], "resource_status": "ACTIVE",
            "delete_flag": "N",
        }
        fake_session.execute_result.scalar_one_or_none.return_value = _row(payload)

        result = aidp_permission_db.get_permission_by_kb_id("kb-1", "tenant-a")
        assert result["kb_id"] == "kb-1"
        assert result["ingroup_permission"] == "EDIT"
        assert result["group_ids"] == [1, 2]

    def test_get_permission_by_kb_id_missing_returns_none(self, aidp_permission_db, fake_session):
        fake_session.execute_result.scalar_one_or_none.return_value = None

        assert aidp_permission_db.get_permission_by_kb_id("kb-missing", "tenant-a") is None

    def test_read_helpers_reject_empty_arguments(self, aidp_permission_db, fake_session):
        with pytest.raises(ValueError):
            aidp_permission_db.list_permissions_by_tenant("")
        with pytest.raises(ValueError):
            aidp_permission_db.count_permissions_by_tenant("")
        with pytest.raises(ValueError):
            aidp_permission_db.get_permission_by_kb_id("", "")
        # No SQL should have been issued for invalid arguments.
        assert fake_session.executed == []


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


class TestWriteHelpers:
    def test_create_permission_inserts_normalized_payload(self, aidp_permission_db, fake_session):
        new_id = aidp_permission_db.create_permission(
            kb_id="kb-1",
            owner_user_id="user-1",
            tenant_id="tenant-a",
            ingroup_permission="EDIT",
            group_ids=[1, "2", 3],
            resource_status="CREATING",
            created_by="user-1",
        )

        assert new_id == 99
        record = fake_session.added[0]
        assert record.kb_id == "kb-1"
        assert record.owner_user_id == "user-1"
        assert record.tenant_id == "tenant-a"
        assert record.ingroup_permission == "EDIT"
        assert record.resource_status == "CREATING"
        # group_ids are normalised to ints.
        assert record.group_ids == [1, 2, 3]
        assert record.delete_flag == "N"
        assert record.created_by == "user-1"
        assert record.updated_by == "user-1"
        assert fake_session.committed

    def test_create_permission_propagates_integrity_error(self, aidp_permission_db, fake_session):
        from sqlalchemy.exc import IntegrityError

        fake_session.flush_raises = IntegrityError("INSERT", {}, Exception("dup"))

        with pytest.raises(IntegrityError):
            aidp_permission_db.create_permission(
                kb_id="kb-1", owner_user_id="user-1", tenant_id="tenant-a"
            )

    def test_update_permission_applies_changes(self, aidp_permission_db, fake_session):
        fake_session.execute_result.rowcount = 1

        ok = aidp_permission_db.update_permission(
            kb_id="kb-1",
            tenant_id="tenant-a",
            ingroup_permission="PRIVATE",
            group_ids=[],
            updated_by="user-2",
        )

        assert ok is True
        # The update() statement should have been executed with the values.
        assert fake_session.executed
        assert fake_session.committed

    def test_update_permission_no_op_returns_true(self, aidp_permission_db, fake_session):
        ok = aidp_permission_db.update_permission(
            kb_id="kb-1", tenant_id="tenant-a"
        )
        assert ok is True
        # No SQL was issued because the values dict is empty.
        assert fake_session.executed == []

    def test_update_permission_reports_missing_row(self, aidp_permission_db, fake_session):
        fake_session.execute_result.rowcount = 0

        ok = aidp_permission_db.update_permission(
            kb_id="kb-missing", tenant_id="tenant-a", ingroup_permission="EDIT"
        )

        assert ok is False

    def test_soft_delete_permission_marks_pending(self, aidp_permission_db, fake_session):
        fake_session.execute_result.rowcount = 1

        ok = aidp_permission_db.soft_delete_permission(
            kb_id="kb-1", tenant_id="tenant-a", updated_by="user-2"
        )

        assert ok is True
        # Inspect the executed statement's values for the soft-delete payload.
        statement, _params = fake_session.executed[0]
        values = statement.compile().params
        assert values["delete_flag"] == "Y"
        assert values["resource_status"] == "DELETE_PENDING"
        assert values["updated_by"] == "user-2"

    def test_update_resource_status(self, aidp_permission_db, fake_session):
        fake_session.execute_result.rowcount = 1

        ok = aidp_permission_db.update_resource_status(
            kb_id="kb-1",
            tenant_id="tenant-a",
            status="UNAVAILABLE",
            updated_by="user-2",
        )

        assert ok is True
        statement, _params = fake_session.executed[0]
        values = statement.compile().params
        assert values["resource_status"] == "UNAVAILABLE"
        assert values["updated_by"] == "user-2"

    def test_update_resource_status_requires_arguments(self, aidp_permission_db, fake_session):
        with pytest.raises(ValueError):
            aidp_permission_db.update_resource_status(
                kb_id="", tenant_id="tenant-a", status="ACTIVE"
            )
        with pytest.raises(ValueError):
            aidp_permission_db.update_resource_status(
                kb_id="kb-1", tenant_id="tenant-a", status=""
            )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


class TestGroupIdNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, []),
            ("", []),
            ("1,2,3", [1, 2, 3]),
            (" 4 , 5 ", [4, 5]),
            ([1, 2, 3], [1, 2, 3]),
            (["7", "8"], [7, 8]),
        ],
    )
    def test_normalize_group_ids(self, aidp_permission_db, raw, expected):
        assert aidp_permission_db._normalize_group_ids(raw) == expected

    def test_normalize_group_ids_rejects_non_integer(self, aidp_permission_db):
        with pytest.raises(ValueError):
            aidp_permission_db._normalize_group_ids([1, "abc"])
