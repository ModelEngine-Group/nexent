"""Unit tests for the document tag projection persistence layer."""

from contextlib import nullcontext

from database import document_tag_projection_db as projection_db
from database.db_models import DocumentTagProjection


class _Query:
    """Stand-in SQLAlchemy query object that records chained calls."""

    def __init__(self, one=None, all_rows=None, deleted=None):
        self.one = one
        self.all_rows = all_rows if all_rows is not None else []
        self.deleted = deleted
        self.filters = []
        self.joined = None
        self.grouped = None
        self.having_condition = None
        self.limit_value = None
        self.order_col = None
        self.asc_order = False

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def join(self, target, condition):
        self.joined = (target, condition)
        return self

    def group_by(self, *columns):
        self.grouped = columns
        return self

    def having(self, condition):
        self.having_condition = condition
        return self

    def order_by(self, column):
        self.order_col = column
        self.asc_order = True
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def first(self):
        return self.one

    def all(self):
        return self.all_rows

    def delete(self, synchronize_session=None):
        return self.deleted


class _Session:
    """Fake session exposing the ORM surface used by the projection db module."""

    def __init__(self, query):
        self.query_result = query
        self.added = []
        self.flushed = False

    def query(self, model):
        return self.query_result

    def add(self, record):
        self.added.append(record)

    def flush(self):
        self.flushed = True


def _record(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "provider": "local",
        "knowledge_base_id": "kb-1",
        "provider_document_id": "doc-a",
        "resource_id": "res-1",
        "status": "synced",
        "version": 2,
        "payload": [{"definition_id": 1, "value_id": 2}],
        "retry_count": 0,
        "last_error": None,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "create_time": None,
        "update_time": None,
        "created_by": "user-a",
        "updated_by": "user-a",
    }
    values.update(overrides)
    return type("Record", (), values)()


def test_state_data_projection_shape():
    record = _record()

    state = projection_db._state_data(record)

    assert state["tenant_id"] == "tenant-a"
    assert state["provider"] == "local"
    assert state["knowledge_base_id"] == "kb-1"
    assert state["resource_id"] == "res-1"
    assert state["status"] == "synced"
    assert state["version"] == 2
    assert state["payload"] == [{"definition_id": 1, "value_id": 2}]


def test_get_projection_state_returns_none_when_absent(monkeypatch):
    query = _Query(one=None)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.get_projection_state("tenant-a", "local", "kb-1", "doc-a")

    assert result is None
    assert query.filters[0].right.value == "tenant-a"


def test_get_projection_state_returns_state_when_present(monkeypatch):
    query = _Query(one=_record(status="failed", retry_count=3, last_error="boom"))
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.get_projection_state("tenant-a", "local", "kb-1", "doc-a")

    assert result is not None
    assert result["status"] == "failed"
    assert result["retry_count"] == 3
    assert result["last_error"] == "boom"


def test_upsert_projection_state_creates_new_record(monkeypatch):
    query = _Query(one=None)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.upsert_projection_state(
        tenant_id="tenant-a",
        provider="local",
        knowledge_base_id="kb-1",
        provider_document_id="doc-a",
        resource_id="res-1",
        status="pending",
        version=1,
        payload=[],
        actor_id="user-a",
    )

    assert result["status"] == "pending"
    assert result["version"] == 1
    assert len(session.added) == 1
    assert session.flushed is True


def test_upsert_projection_state_updates_existing_record(monkeypatch):
    existing = _record()
    query = _Query(one=existing)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.upsert_projection_state(
        tenant_id="tenant-a",
        provider="local",
        knowledge_base_id="kb-1",
        provider_document_id="doc-a",
        resource_id="res-1",
        status="synced",
        version=3,
        payload=[{"definition_id": 1, "value_id": 5}],
        retry_count=1,
        actor_id="user-b",
    )

    assert result["version"] == 3
    assert result["payload"] == [{"definition_id": 1, "value_id": 5}]
    assert result["retry_count"] == 1
    assert result["updated_by"] == "user-b"
    assert session.added == []


def test_upsert_preserves_existing_retry_and_actor_when_not_provided(monkeypatch):
    existing = _record(retry_count=7, updated_by="original")
    query = _Query(one=existing)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.upsert_projection_state(
        tenant_id="tenant-a",
        provider="local",
        knowledge_base_id="kb-1",
        provider_document_id="doc-a",
        resource_id="res-1",
        status="failed",
        version=4,
        payload=[],
    )

    assert result["retry_count"] == 7
    assert result["updated_by"] == "original"


def test_delete_projection_state_returns_bool(monkeypatch):
    query = _Query(deleted=2)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    assert projection_db.delete_projection_state("tenant-a", "local", "kb-1", "doc-a") is True


def test_delete_projection_state_returns_false_for_zero(monkeypatch):
    query = _Query(deleted=0)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    assert projection_db.delete_projection_state("tenant-a", "local", "kb-1", "doc-a") is False


def test_delete_projection_states_for_knowledge_base(monkeypatch):
    query = _Query(deleted=4)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.delete_projection_states_for_knowledge_base("tenant-a", "local", "kb-1")

    assert result == 4


def test_delete_projection_states_for_knowledge_base_zero(monkeypatch):
    query = _Query(deleted=0)
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    assert (
        projection_db.delete_projection_states_for_knowledge_base("tenant-a", "local", "kb-1")
        == 0
    )


def test_list_projection_states_for_knowledge_base_keyed_by_document(monkeypatch):
    query = _Query(
        all_rows=[_record(provider_document_id="doc-a"), _record(provider_document_id="doc-b")]
    )
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.list_projection_states_for_knowledge_base("tenant-a", "local", "kb-1")

    assert set(result) == {"doc-a", "doc-b"}
    assert result["doc-a"]["resource_id"] == "res-1"


def test_list_due_projection_states_applies_tenant_filter_when_given(monkeypatch):
    query = _Query(all_rows=[_record(status="pending")])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.list_due_projection_states(tenant_id="tenant-a", limit=10)

    assert result[0]["status"] == "pending"
    assert query.limit_value == 10
    assert query.order_col is not None
    assert query.asc_order is True


def test_list_due_projection_states_without_tenant(monkeypatch):
    query = _Query(all_rows=[])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    assert projection_db.list_due_projection_states() == []


def test_list_synced_document_ids_returns_resource_ids(monkeypatch):
    query = _Query(all_rows=[("res-1",), ("res-2",)])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.list_synced_document_ids("tenant-a", "local", "kb-1")

    assert result == ["res-1", "res-2"]


def test_filter_document_ids_without_predicates_delegates_to_synced(monkeypatch):
    query = _Query(all_rows=[("res-1",)])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.filter_document_ids_by_predicates(
        "tenant-a", "local", "kb-1", [{"definition_id": 1, "value_ids": []}]
    )

    assert result == ["res-1"]


def test_filter_document_ids_joins_and_groups_assignments(monkeypatch):
    query = _Query(all_rows=[("res-1",)])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.filter_document_ids_by_predicates(
        "tenant-a",
        "local",
        "kb-1",
        [
            {"definition_id": 5, "value_ids": [1, 2]},
            {"definition_id": 9, "value_ids": [3]},
        ],
    )

    assert result == ["res-1"]
    assert query.joined is not None
    assert query.joined[0] is DocumentTagProjection
    assert query.grouped is not None
    assert query.having_condition is not None
    assert query.filters[0].right.value == "tenant-a"


def test_filter_document_ids_skips_empty_predicates_in_group_count(monkeypatch):
    query = _Query(all_rows=[])
    session = _Session(query)
    monkeypatch.setattr(
        "database.document_tag_projection_db.get_db_session",
        lambda: nullcontext(session),
    )

    result = projection_db.filter_document_ids_by_predicates(
        "tenant-a",
        "local",
        "kb-1",
        [{"definition_id": 5, "value_ids": [1]}, {"definition_id": 9, "value_ids": []}],
    )

    assert result == []
    assert query.grouped is not None
