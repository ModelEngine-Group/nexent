"""Focused tests for the durable NL2AGENT session repository."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from database import nl2agent_session_db
from database.db_models import Nl2AgentSession


@contextmanager
def _session_context(session):
    yield session


def test_create_session_uses_caller_transaction(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda db_session=None: _session_context(db_session or session),
    )
    monkeypatch.setattr(
        nl2agent_session_db,
        "as_dict",
        lambda record: {
            "tenant_id": record.tenant_id,
            "draft_agent_id": record.draft_agent_id,
            "workflow_revision": record.workflow_revision,
        },
    )

    result = nl2agent_session_db.create_nl2agent_session(
        tenant_id="tenant-a",
        user_id="user-a",
        runner_agent_id=7,
        draft_agent_id=11,
        conversation_id=22,
        workflow_schema_version=2,
        workflow_state={"revision": 0},
        session_catalogs={"tool_catalog": []},
        db_session=session,
    )

    assert result == {
        "tenant_id": "tenant-a",
        "draft_agent_id": 11,
        "workflow_revision": 0,
    }
    session.add.assert_called_once()
    created = session.add.call_args.args[0]
    assert created.runner_agent_id == 7
    assert created.session_catalogs == {"tool_catalog": []}
    session.flush.assert_called_once()


def test_get_session_can_enforce_owner(monkeypatch):
    record = SimpleNamespace(session_id=1)
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = record
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    monkeypatch.setattr(
        nl2agent_session_db, "as_dict", lambda value: {"session_id": value.session_id}
    )

    assert nl2agent_session_db.get_nl2agent_session(
        "tenant-a", 11, user_id="user-a"
    ) == {"session_id": 1}
    assert query.filter.call_count == 2


def test_get_session_snapshot_reads_inline_catalog(monkeypatch):
    record = SimpleNamespace(
        session_id=1,
        session_catalogs={"tool_catalog": [{"tool_id": 1}]},
    )
    session_query = MagicMock()
    session_query.filter.return_value = session_query
    session_query.first.return_value = record
    session = MagicMock()
    session.query.return_value = session_query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    monkeypatch.setattr(
        nl2agent_session_db,
        "as_dict",
        lambda value: vars(value),
    )

    result = nl2agent_session_db.get_nl2agent_session_snapshot("tenant-a", 11)

    assert result == {
        "session_id": 1,
        "session_catalogs": {"tool_catalog": [{"tool_id": 1}]},
        "catalog_snapshot": {"tool_catalog": [{"tool_id": 1}]},
    }
    assert session.query.call_count == 1


def test_get_session_by_conversation_is_owner_and_status_scoped(monkeypatch):
    record = SimpleNamespace(session_id=1)
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = record
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    monkeypatch.setattr(
        nl2agent_session_db,
        "as_dict",
        lambda value: {"session_id": value.session_id},
    )

    result = nl2agent_session_db.get_nl2agent_session_by_conversation(
        "tenant-a",
        "user-a",
        22,
    )

    assert result == {"session_id": 1}
    assert query.filter.call_count == 2


def test_list_sessions_enforces_owner_status_order_and_limit(monkeypatch):
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = [SimpleNamespace(session_id=1)]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    monkeypatch.setattr(
        nl2agent_session_db,
        "as_dict",
        lambda value: {"session_id": value.session_id},
    )

    assert nl2agent_session_db.list_nl2agent_sessions(
        "tenant-a", "user-a", limit=1000
    ) == [{"session_id": 1}]
    query.limit.assert_called_once_with(100)


@pytest.mark.parametrize("updated_count, expected", [(1, True), (0, False)])
def test_workflow_update_is_revision_guarded(monkeypatch, updated_count, expected):
    query = MagicMock()
    query.filter.return_value = query
    query.update.return_value = updated_count
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )

    assert (
        nl2agent_session_db.update_nl2agent_workflow_state(
            tenant_id="tenant-a",
            draft_agent_id=11,
            expected_revision=3,
            workflow_schema_version=2,
            workflow_state={"revision": 4},
            user_id="user-a",
        )
        is expected
    )
    values = query.update.call_args.args[0]
    assert values["workflow_revision"] == 4
    assert values["workflow_state"] == {"revision": 4}


def test_workflow_update_rejects_revision_jump():
    with pytest.raises(ValueError, match="advance exactly once"):
        nl2agent_session_db.update_nl2agent_workflow_state(
            tenant_id="tenant-a",
            draft_agent_id=11,
            expected_revision=3,
            workflow_schema_version=2,
            workflow_state={"revision": 5},
            user_id="user-a",
        )


def test_status_update_only_accepts_terminal_states(monkeypatch):
    with pytest.raises(ValueError, match="must be terminal"):
        nl2agent_session_db.update_nl2agent_session_status(
            tenant_id="tenant-a",
            draft_agent_id=11,
            status="active",
            user_id="user-a",
        )

    query = MagicMock()
    query.filter.return_value = query
    query.update.return_value = 1
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    assert nl2agent_session_db.update_nl2agent_session_status(
        tenant_id="tenant-a",
        draft_agent_id=11,
        status=nl2agent_session_db.NL2AGENT_SESSION_COMPLETED,
        user_id="user-a",
    )


@pytest.mark.parametrize("updated_count, expected", [(1, True), (0, False)])
def test_resume_session_only_updates_completed_owner_session(
    monkeypatch, updated_count, expected
):
    query = MagicMock()
    query.filter.return_value = query
    query.update.return_value = updated_count
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )

    assert (
        nl2agent_session_db.resume_nl2agent_session(
            tenant_id="tenant-a",
            draft_agent_id=11,
            user_id="user-a",
            expected_revision=3,
            workflow_schema_version=2,
            workflow_state={"revision": 4, "revision_mode": True},
        )
        is expected
    )
    values = query.update.call_args.args[0]
    assert values["status"] == nl2agent_session_db.NL2AGENT_SESSION_ACTIVE
    assert values["workflow_revision"] == 4
    assert values["workflow_state"]["revision_mode"] is True
    assert values["updated_by"] == "user-a"


def test_cleanup_soft_deletes_only_selected_abandoned_roots(monkeypatch):
    records = [
        SimpleNamespace(
            tenant_id="tenant-a",
            draft_agent_id=11,
            conversation_id=21,
            catalog_snapshot_id="digest-a",
            delete_flag="N",
        ),
        SimpleNamespace(
            tenant_id="tenant-a",
            draft_agent_id=12,
            conversation_id=22,
            catalog_snapshot_id="digest-b",
            delete_flag="N",
        ),
    ]
    session_query = MagicMock()
    for method_name in ("filter", "order_by", "with_for_update", "limit"):
        getattr(session_query, method_name).return_value = session_query
    session_query.all.return_value = records
    mutation_queries = [MagicMock() for _ in range(9)]
    for query in mutation_queries:
        query.filter.return_value = query
    live_reference_query = MagicMock()
    live_reference_query.filter.return_value = live_reference_query
    live_reference_query.exists.return_value = True
    snapshot_query = MagicMock()
    snapshot_query.filter.return_value = snapshot_query
    snapshot_query.update.return_value = 2
    session = MagicMock()
    session.query.side_effect = [
        session_query,
        *mutation_queries,
    ]
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )

    count = nl2agent_session_db.cleanup_abandoned_nl2agent_sessions(
        abandoned_before=datetime(2026, 6, 1),
        limit=20,
    )

    assert count == 2
    session_query.with_for_update.assert_called_once_with(skip_locked=True)
    session_query.limit.assert_called_once_with(20)
    assert all(query.update.call_count == 1 for query in mutation_queries)
    assert all(record.delete_flag == "Y" for record in records)
    session.flush.assert_called_once()


def test_stale_active_sessions_are_abandoned_in_a_bounded_batch(monkeypatch):
    records = [SimpleNamespace(status="active", updated_by="user-a")]
    query = MagicMock()
    for method_name in ("filter", "order_by", "with_for_update", "limit"):
        getattr(query, method_name).return_value = query
    query.all.return_value = records
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )

    count = nl2agent_session_db.abandon_stale_active_nl2agent_sessions(
        active_before=datetime(2026, 6, 1),
        limit=1000,
    )

    assert count == 1
    assert records[0].status == nl2agent_session_db.NL2AGENT_SESSION_ABANDONED
    assert records[0].updated_by == "nl2agent_cleanup"
    query.limit.assert_called_once_with(500)


def test_completed_cleanup_soft_deletes_selected_sessions(monkeypatch):
    record = SimpleNamespace(
        tenant_id="tenant-a",
        catalog_snapshot_id="digest",
        delete_flag="N",
        updated_by="user-a",
    )
    session_query = MagicMock()
    for method_name in ("filter", "order_by", "with_for_update", "limit"):
        getattr(session_query, method_name).return_value = session_query
    session_query.all.return_value = [record]
    session = MagicMock()
    session.query.return_value = session_query
    monkeypatch.setattr(
        nl2agent_session_db,
        "get_db_session",
        lambda: _session_context(session),
    )

    count = nl2agent_session_db.cleanup_completed_nl2agent_sessions(
        completed_before=datetime(2026, 6, 1),
        limit=20,
    )

    assert count == 1
    assert record.delete_flag == "Y"
    session.flush.assert_called_once()


def test_model_and_fresh_init_match_incremental_migration():
    assert Nl2AgentSession.__table__.schema == "nexent"
    root = Path(__file__).resolve().parents[3]
    session_migration = (
        root / "deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql"
    ).read_text(encoding="utf-8")
    fresh_init = (root / "deploy/sql/init.sql").read_text(encoding="utf-8")
    for sql in (session_migration, fresh_init):
        assert "nl2agent_session_t" in sql
        assert "workflow_state" in sql
        assert "session_catalogs" in sql
        assert "nl2agent_installation_operation_t" in sql
        assert "workflow_revision" in sql


def test_nl2agent_migration_is_safe_to_reapply():
    root = Path(__file__).resolve().parents[3]
    session_migration = (
        root / "deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql"
    ).read_text(encoding="utf-8")
    assert session_migration.count("CREATE TABLE nexent.nl2agent_") == 2
    assert "DROP TABLE IF EXISTS nexent.nl2agent_catalog_snapshot_t" in session_migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in session_migration
