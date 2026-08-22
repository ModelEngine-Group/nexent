"""Coverage and contract tests for versioned long-term memory persistence."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from database import memory_long_term_db


def _row(**overrides):
    values = {
        "version_id": 1, "tenant_id": "t", "scope": "user", "subject_id": "u",
        "version_no": 1, "parent_version_id": None, "is_active": True,
        "source": "manual", "author_user_id": "u", "editor_user_id": "u",
        "authored_at": datetime(2026, 1, 1), "dreaming_run_id": None,
        "character_count": 3, "generation_audit": None, "evidence_ids": None,
        "fallback_details": None, "omission_details": None, "content": "abc",
        "raw_dreaming_input": None, "delete_flag": "N",
    }
    values.update(overrides)
    return MagicMock(**values)


def _install_session(monkeypatch, session):
    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(memory_long_term_db, "get_db_session", scope)


def test_ac078_serialize_normalizes_time_and_optional_metadata():
    aware = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    value = memory_long_term_db._serialize(_row(authored_at=aware))
    assert value["authored_at"] == "2026-01-01T00:00:00Z"
    assert value["content"] == "abc"
    assert value["generation_audit"] == {}
    assert memory_long_term_db._serialize(
        _row(authored_at=None), include_content=False
    )["authored_at"] is None


def test_ac078_read_active_version_and_history(monkeypatch):
    session = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.first.side_effect = [_row(version_id=2), None]
    query.all.return_value = [_row(version_id=2)]
    session.query.return_value = query
    _install_session(monkeypatch, session)

    assert memory_long_term_db.get_active("t", "user", "u")["version_id"] == 2
    assert memory_long_term_db.get_version("t", "user", "u", 99) is None
    history = memory_long_term_db.list_versions("t", "user", "u", limit=3)
    assert history[0]["version_id"] == 2
    assert "content" not in history[0]


def test_ac078_create_and_activate_rejects_stale_expected_version(monkeypatch):
    session = MagicMock()
    current = _row(version_id=7)
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = current
    _install_session(monkeypatch, session)

    assert memory_long_term_db.create_and_activate(
        tenant_id="t", scope="user", subject_id="u", content="new",
        source="manual", actor_user_id="u", expected_active_version_id=6,
    ) is None
    session.add.assert_not_called()


def test_ac078_create_and_activate_is_idempotent_for_dreaming_run(monkeypatch):
    session = MagicMock()
    active_query = MagicMock()
    active_query.filter.return_value.with_for_update.return_value.first.return_value = None
    existing_query = MagicMock()
    existing_query.filter.return_value.first.return_value = _row(
        version_id=9, source="dreaming", dreaming_run_id=42
    )
    session.query.side_effect = [active_query, existing_query]
    _install_session(monkeypatch, session)

    value = memory_long_term_db.create_and_activate(
        tenant_id="t", scope="user", subject_id="u", content="new",
        source="dreaming", actor_user_id="u", expected_active_version_id=None,
        dreaming_run_id=42,
    )
    assert value["version_id"] == 9
    session.add.assert_not_called()


def test_ac078_create_and_activate_persists_new_child(monkeypatch):
    session = MagicMock()
    active_query = MagicMock()
    current = _row(version_id=3)
    active_query.filter.return_value.with_for_update.return_value.first.return_value = current
    max_query = MagicMock()
    max_query.filter.return_value.scalar.return_value = 3
    session.query.side_effect = [active_query, max_query]

    def assign_id(row):
        row.version_id = 4
        row.authored_at = datetime(2026, 1, 2)

    session.add.side_effect = assign_id
    _install_session(monkeypatch, session)

    value = memory_long_term_db.create_and_activate(
        tenant_id="t", scope="user", subject_id="u", content="next",
        source="manual", actor_user_id="u", expected_active_version_id=3,
        evidence_ids=["64"],
    )
    assert value["version_id"] == 4
    assert value["parent_version_id"] == 3
    assert current.is_active is False
    session.flush.assert_called()
    session.commit.assert_called_once()
