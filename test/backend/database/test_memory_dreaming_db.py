"""Unit tests for memory_dreaming_db CRUD and audit functions."""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from database import memory_dreaming_db
from database.db_models import (
    MemoryDreamingAudit,
    MemoryDreamingDecision,
    MemoryDreamingSchedule,
    MemoryLongTermVersion,
)


def _mock_session(monkeypatch):
    session = MagicMock()

    @contextmanager
    def _ctx():
        yield session

    monkeypatch.setattr(memory_dreaming_db, "get_db_session", _ctx)
    return session



# ---------------------------------------------------------------------------
# try_scope_lock
# ---------------------------------------------------------------------------


def test_try_scope_lock_acquired(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar.return_value = True

    with memory_dreaming_db.try_scope_lock("t", "u", "a") as acquired:
        assert acquired is True

    session.commit.assert_called_once()


def test_try_scope_lock_not_acquired(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar.return_value = False

    with memory_dreaming_db.try_scope_lock("t", "u", "a") as acquired:
        assert acquired is False

    session.commit.assert_called_once()


def test_try_scope_lock_rollback_on_exception(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar.return_value = True

    with pytest.raises(ValueError), memory_dreaming_db.try_scope_lock("t", "u", "a"):
        raise ValueError("boom")

    session.rollback.assert_called_once()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# create_audit
# ---------------------------------------------------------------------------


def test_create_audit_default(monkeypatch):
    session = _mock_session(monkeypatch)

    added_row = None

    def capture_add(row):
        nonlocal added_row
        added_row = row
        row.run_id = 42

    session.add.side_effect = capture_add

    result = memory_dreaming_db.create_audit("t", "u", "a")

    assert result == 42
    assert added_row.tenant_id == "t"
    assert added_row.user_id == "u"
    assert added_row.agent_id == "a"
    assert added_row.trigger_source == "manual"
    assert added_row.status == "running"
    assert added_row.current_phase == "light"
    session.commit.assert_called_once()


def test_create_audit_queued_status(monkeypatch):
    session = _mock_session(monkeypatch)

    added_row = None

    def capture_add(row):
        nonlocal added_row
        added_row = row
        row.run_id = 99

    session.add.side_effect = capture_add

    result = memory_dreaming_db.create_audit(
        "t", "u", "a", trigger_source="scheduler", status="queued"
    )

    assert result == 99
    assert added_row.trigger_source == "scheduler"
    assert added_row.status == "queued"
    assert added_row.current_phase is None


# ---------------------------------------------------------------------------
# schedules
# ---------------------------------------------------------------------------


def test_ac037_upsert_schedule_replaces_soft_deleted_row(monkeypatch):
    session = _mock_session(monkeypatch)
    old_row = MagicMock(spec=MemoryDreamingSchedule)
    old_row.schedule_id = 2
    old_row.agent_id = "__user__"
    old_row.delete_flag = "Y"
    old_row.fire_count = 9
    old_row.last_fire_at = datetime(2026, 7, 27, 2, 56)
    (
        session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value
    ) = old_row

    def capture_add(row):
        row.schedule_id = 3
        row.fire_count = 0
        row.last_fire_at = None

    session.add.side_effect = capture_add
    start_at = datetime(2026, 7, 28, 10, 56)
    next_fire_at = datetime(2026, 7, 28, 2, 56)

    result = memory_dreaming_db.upsert_schedule(
        "t",
        "u",
        "__user__",
        enabled=True,
        rule_type="cron",
        timezone_name="Asia/Shanghai",
        start_at=start_at,
        cron_expr="56 10 * * *",
        interval_seconds=None,
        next_fire_at=next_fire_at,
        actor_user_id="u",
    )

    assert result["schedule_id"] == 3
    assert result["fire_count"] == 0
    assert result["last_fire_at"] is None
    session.delete.assert_called_once_with(old_row)
    session.add.assert_called_once()
    assert session.flush.call_count == 2


def test_ac037_delete_history_physically_deletes_schedule(monkeypatch):
    session = _mock_session(monkeypatch)
    query = session.query.return_value
    query.filter.return_value = query
    query.with_for_update.return_value.all.return_value = []

    memory_dreaming_db.delete_user_dreaming_history("t", "u")

    assert session.query.call_args_list[0].args == (MemoryDreamingSchedule,)
    assert query.delete.call_count == 2
    assert session.query.call_count == 3


def test_delete_history_retires_dreamed_version_and_restores_latest_manual(monkeypatch):
    session = _mock_session(monkeypatch)
    schedule_query = MagicMock()
    audit_query = MagicMock()
    version_query = MagicMock()
    manual_old = MagicMock(version_id=1, version_no=1, source="manual", is_active=False, delete_flag="N")
    manual_new = MagicMock(version_id=3, version_no=3, source="manual", is_active=False, delete_flag="N")
    dreamed = MagicMock(version_id=4, version_no=4, source="dreaming", is_active=True, delete_flag="N")
    version_query.filter.return_value.with_for_update.return_value.all.return_value = [manual_old, manual_new, dreamed]
    session.query.side_effect = [schedule_query, audit_query, version_query]
    schedule_query.filter.return_value.delete.return_value = 1
    audit_query.filter.return_value.delete.return_value = 2

    memory_dreaming_db.delete_user_dreaming_history("t", "u")

    assert dreamed.delete_flag == "Y"
    assert dreamed.is_active is False
    assert manual_new.is_active is True
    session.add.assert_not_called()
    session.flush.assert_called_once_with()



def test_update_audit_success(monkeypatch):
    session = _mock_session(monkeypatch)
    row = MagicMock(spec=MemoryDreamingAudit)
    row.run_id = 42
    session.query.return_value.filter.return_value.first.return_value = row

    result = memory_dreaming_db.update_audit(
        42, {"status": "completed", "light_count": 5}
    )

    assert result is True
    assert row.status == "completed"
    assert row.light_count == 5
    session.commit.assert_called_once()


def test_update_audit_not_found(monkeypatch):
    session = _mock_session(monkeypatch)
    session.query.return_value.filter.return_value.first.return_value = None

    result = memory_dreaming_db.update_audit(999, {"status": "failed"})

    assert result is False
    session.commit.assert_not_called()


def test_update_audit_ignores_disallowed_keys(monkeypatch):
    session = _mock_session(monkeypatch)
    row = MagicMock(spec=MemoryDreamingAudit)
    session.query.return_value.filter.return_value.first.return_value = row

    result = memory_dreaming_db.update_audit(
        42, {"status": "completed", "tenant_id": "hacked"}
    )

    assert result is True
    assert row.status == "completed"
    assert not hasattr(row, "tenant_id") or row.tenant_id != "hacked"


def test_ac076_update_audit_replaces_normalized_decisions(monkeypatch):
    session = _mock_session(monkeypatch)
    audit_query = MagicMock()
    decision_query = MagicMock()
    row = MagicMock(spec=MemoryDreamingAudit)
    session.query.side_effect = [audit_query, decision_query]
    audit_query.filter.return_value.first.return_value = row
    decision_query.filter.return_value.delete.return_value = 2
    decisions = [{
        "memory_id": 64,
        "score": 0.91,
        "noise": False,
        "signal_count": 5,
        "context_diversity": 3,
        "evidence_ids": ["64"],
        "event": "SELECT",
        "reason": "eligible",
        "archive_suggested": False,
    }]

    assert memory_dreaming_db.update_audit(42, {"decisions": decisions}) is True

    inserted = list(session.add_all.call_args.args[0])
    assert len(inserted) == 1
    assert isinstance(inserted[0], MemoryDreamingDecision)
    assert inserted[0].run_id == 42
    assert inserted[0].decision_order == 0
    assert inserted[0].memory_id == 64
    assert inserted[0].score == 0.91
    assert inserted[0].event == "SELECT"
    decision_query.filter.return_value.delete.assert_called_once_with(
        synchronize_session=False
    )
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# finish_audit
# ---------------------------------------------------------------------------


def test_finish_audit_completed(monkeypatch):
    mock_update = MagicMock(return_value=True)
    monkeypatch.setattr(memory_dreaming_db, "update_audit", mock_update)

    result = memory_dreaming_db.finish_audit(
        42, status="completed", light_count=3, rem_count=2
    )

    assert result is True
    call_values = mock_update.call_args[0][1]
    assert call_values["status"] == "completed"
    assert call_values["light_count"] == 3
    assert call_values["current_phase"] is None
    assert "finished_at" in call_values


def test_finish_audit_failed(monkeypatch):
    mock_update = MagicMock(return_value=True)
    monkeypatch.setattr(memory_dreaming_db, "update_audit", mock_update)

    result = memory_dreaming_db.finish_audit(
        42, status="failed", error="something broke"
    )

    assert result is True
    call_values = mock_update.call_args[0][1]
    assert call_values["status"] == "failed"
    assert call_values["error"] == "something broke"
    # Failed status should NOT clear current_phase
    assert "current_phase" not in call_values


# ---------------------------------------------------------------------------
# list_audits
# ---------------------------------------------------------------------------


def test_list_audits_with_filters(monkeypatch):
    session = _mock_session(monkeypatch)
    audit_row = MagicMock()
    audit_row.run_id = 1
    audit_row.tenant_id = "t"
    audit_row.user_id = "u"
    audit_row.agent_id = "a"
    audit_row.trigger_source = "manual"
    audit_row.status = "completed"
    audit_row.current_phase = None
    audit_row.started_at = datetime(2026, 7, 25)
    audit_row.finished_at = datetime(2026, 7, 25, 1)
    audit_row.light_count = 3
    audit_row.rem_count = 2
    audit_row.promoted_count = 1
    audit_row.deferred_count = 1
    audit_row.published_version_id = 7
    audit_row.reason = None
    audit_row.error = None

    audit_query = MagicMock()
    audit_query.filter.return_value = audit_query
    audit_query.order_by.return_value = audit_query
    audit_query.limit.return_value = audit_query
    audit_query.all.return_value = [audit_row]
    decision = MagicMock(
        run_id=1, memory_id=64, score=0.91, noise=False, signal_count=5,
        context_diversity=3, evidence_ids=["64"], event="SELECT",
        reason="eligible", archive_suggested=False,
    )
    decision_query = MagicMock()
    decision_query.filter.return_value = decision_query
    decision_query.order_by.return_value = decision_query
    decision_query.all.return_value = [decision]
    session.query.side_effect = [audit_query, decision_query]

    result = memory_dreaming_db.list_audits(
        "t", "u", agent_id="a", run_id=1, limit=50
    )

    assert len(result) == 1
    assert result[0]["run_id"] == 1
    assert result[0]["status"] == "completed"
    assert result[0]["started_at"] == "2026-07-25T00:00:00Z"
    assert result[0]["finished_at"] == "2026-07-25T01:00:00Z"
    assert result[0]["decisions"] == [{
        "memory_id": 64, "score": 0.91, "noise": False,
        "signal_count": 5, "context_diversity": 3,
        "evidence_ids": ["64"], "event": "SELECT",
        "reason": "eligible", "archive_suggested": False,
    }]
    assert result[0]["published_version_id"] == 7
    assert "result" not in result[0]


def test_list_audits_no_optional_filters(monkeypatch):
    session = _mock_session(monkeypatch)
    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = []

    result = memory_dreaming_db.list_audits("t", "u")

    assert result == []


def test_list_audits_none_datetime_fields(monkeypatch):
    session = _mock_session(monkeypatch)
    audit_row = MagicMock()
    audit_row.run_id = 1
    audit_row.tenant_id = "t"
    audit_row.user_id = "u"
    audit_row.agent_id = "a"
    audit_row.trigger_source = "manual"
    audit_row.status = "queued"
    audit_row.current_phase = None
    audit_row.started_at = None
    audit_row.finished_at = None
    audit_row.light_count = 0
    audit_row.rem_count = 0
    audit_row.promoted_count = 0
    audit_row.deferred_count = 0
    audit_row.published_version_id = None
    audit_row.reason = None
    audit_row.error = None

    query_chain = MagicMock()
    session.query.side_effect = [query_chain, MagicMock()]
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = [audit_row]

    result = memory_dreaming_db.list_audits("t", "u")

    assert result[0]["started_at"] is None
    assert result[0]["finished_at"] is None
