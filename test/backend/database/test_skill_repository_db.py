"""Focused unit tests for skill repository database helpers."""

import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest


agent_repository_consts = MagicMock()
agent_repository_consts.STATUS_NOT_SHARED = "not_shared"
sys.modules["consts.agent_repository"] = agent_repository_consts

client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock(side_effect=lambda record: record.payload)
client_mock.filter_property = MagicMock(side_effect=lambda payload, _model: payload)
sys.modules["database.client"] = client_mock


class _SkillRepositoryModel:
    skill_repository_id = MagicMock(name="skill_repository_id")
    publisher_tenant_id = MagicMock(name="publisher_tenant_id")
    publisher_user_id = MagicMock(name="publisher_user_id")
    skill_id = MagicMock(name="skill_id")
    name = MagicMock(name="name")
    description = MagicMock(name="description")
    source = MagicMock(name="source")
    submitted_by = MagicMock(name="submitted_by")
    category_id = MagicMock(name="category_id")
    tags = MagicMock(name="tags")
    icon = MagicMock(name="icon")
    downloads = MagicMock(name="downloads")
    status = MagicMock(name="status")
    delete_flag = MagicMock(name="delete_flag")
    create_time = MagicMock(name="create_time")
    update_time = MagicMock(name="update_time")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.skill_repository_id = kwargs.get("skill_repository_id", 1)


db_models_mock = MagicMock()
db_models_mock.SkillRepository = _SkillRepositoryModel
sys.modules["database.db_models"] = db_models_mock

from backend.database import skill_repository_db as repo_db


def _session_context(session):
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = None
    return context


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(repo_db, "get_db_session", lambda: _session_context(session))


def _patch_update(monkeypatch):
    statement = MagicMock()
    statement.where.return_value = statement
    statement.values.return_value = statement
    monkeypatch.setattr(repo_db, "update", lambda _model: statement)
    return statement


@pytest.fixture
def mock_session():
    session = MagicMock()
    query = MagicMock()
    session.query.return_value = query
    return session, query


def test_insert_repository_record_applies_defaults(monkeypatch, mock_session):
    session, _ = mock_session
    _patch_session(monkeypatch, session)

    repository_id = repo_db.insert_skill_repository_record(
        {"skill_id": 8, "name": "Skill A", "status": None},
        "tenant-1",
        "user-1",
    )

    assert repository_id == 1
    inserted = session.add.call_args.args[0]
    assert inserted.status == "not_shared"
    assert inserted.publisher_tenant_id == "tenant-1"
    assert inserted.created_by == "user-1"
    session.flush.assert_called_once()


def test_get_repository_by_id_and_publisher(monkeypatch, mock_session):
    session, query = mock_session
    record = MagicMock(payload={"skill_repository_id": 3})
    query.filter.return_value.first.return_value = record
    _patch_session(monkeypatch, session)

    assert repo_db.get_skill_repository_by_id_and_publisher(3, "tenant-1") == {
        "skill_repository_id": 3
    }


def test_get_repository_by_skill_id_with_optional_tenant(monkeypatch, mock_session):
    session, query = mock_session
    record = MagicMock(payload={"skill_id": 8})
    query.filter.return_value = query
    query.first.return_value = record
    _patch_session(monkeypatch, session)

    assert repo_db.get_skill_repository_by_skill_id(
        8,
        publisher_tenant_id="tenant-1",
    ) == {"skill_id": 8}
    assert query.filter.call_count == 2


def test_list_repository_summaries_with_filters(monkeypatch, mock_session):
    session, query = mock_session
    created_at = datetime(2026, 1, 2, 3, 4, 5)
    row = MagicMock(
        skill_repository_id=1,
        skill_id=8,
        submitted_by="dev@example.com",
        name="Skill A",
        description="description",
        source="custom",
        status="shared",
        category_id=2,
        tags=["tag"],
        icon="skill",
        downloads=4,
        create_time=created_at,
    )
    query.filter.return_value = query
    query.count.return_value = 1
    query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        row
    ]
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "or_", MagicMock())
    monkeypatch.setattr(repo_db.func, "array_to_string", MagicMock())

    result = repo_db.list_skill_repository_summaries(
        "tenant-1",
        status="shared",
        skill_id=8,
        category_id=2,
        page=2,
        page_size=5,
        search="tag",
        sort_by_update_time=True,
    )

    assert result["items"][0]["created_at"] == created_at.isoformat()
    assert result["pagination"] == {
        "page": 2,
        "page_size": 5,
        "total": 1,
        "total_pages": 1,
    }


def test_update_repository_returns_zero_without_allowed_fields():
    assert repo_db.update_skill_repository_by_id(
        repository_id=1,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
        updates={"unknown": "value"},
    ) == 0


def test_update_repository_executes_allowed_fields(monkeypatch, mock_session):
    session, _ = mock_session
    session.execute.return_value.rowcount = 1
    _patch_session(monkeypatch, session)
    statement = _patch_update(monkeypatch)

    affected = repo_db.update_skill_repository_by_id(
        repository_id=1,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
        updates={"name": "Updated", "unknown": "ignored"},
    )

    assert affected == 1
    values = statement.values.call_args.kwargs
    assert values == {"name": "Updated", "updated_by": "user-1"}


def test_update_repository_status_applies_optional_values(monkeypatch, mock_session):
    session, _ = mock_session
    session.execute.return_value.rowcount = 1
    _patch_session(monkeypatch, session)
    statement = _patch_update(monkeypatch)

    affected = repo_db.update_skill_repository_status_by_id(
        repository_id=1,
        status="pending_review",
        user_id="user-1",
        filter_publisher_tenant_id="tenant-1",
        publisher_tenant_id="tenant-2",
        publisher_user_id="user-2",
        submitted_by="dev@example.com",
    )

    assert affected == 1
    assert statement.values.call_args.kwargs["publisher_tenant_id"] == "tenant-2"


def test_increment_downloads_updates_audit_user(monkeypatch, mock_session):
    session, _ = mock_session
    session.execute.return_value.rowcount = 1
    _patch_session(monkeypatch, session)
    statement = _patch_update(monkeypatch)
    monkeypatch.setattr(repo_db.func, "coalesce", MagicMock(return_value=0))

    affected = repo_db.increment_skill_repository_downloads(
        repository_id=1,
        user_id="user-1",
        increment=2,
    )

    assert affected == 1
    assert statement.values.call_args.kwargs["updated_by"] == "user-1"


def test_list_repository_by_skill_ids_handles_empty_input():
    assert repo_db.list_skill_repository_by_skill_ids(
        [],
        statuses={"shared"},
        publisher_tenant_id="tenant-1",
    ) == []


def test_list_repository_by_skill_ids_maps_rows(monkeypatch, mock_session):
    session, query = mock_session
    created_at = datetime(2026, 1, 1)
    row = MagicMock(
        skill_repository_id=1,
        skill_id=8,
        status="shared",
        create_time=created_at,
    )
    query.filter.return_value.order_by.return_value.all.return_value = [row]
    _patch_session(monkeypatch, session)

    assert repo_db.list_skill_repository_by_skill_ids(
        [8],
        statuses={"shared"},
        publisher_tenant_id="tenant-1",
    ) == [{
        "skill_repository_id": 1,
        "skill_id": 8,
        "status": "shared",
        "create_time": created_at,
    }]
