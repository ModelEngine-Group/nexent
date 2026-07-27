"""Unit tests for memory_dreaming_db CRUD and audit functions."""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from database import memory_dreaming_db
from database.db_models import (
    MemoryDreamingActivationAudit,
    MemoryDreamingAudit,
    MemoryDreamingVersion,
)


def _mock_session(monkeypatch):
    session = MagicMock()

    @contextmanager
    def _ctx():
        yield session

    monkeypatch.setattr(memory_dreaming_db, "get_db_session", _ctx)
    return session


def _make_version_row(**overrides):
    row = MagicMock(spec=MemoryDreamingVersion)
    row.version_id = overrides.get("version_id", 1)
    row.tenant_id = overrides.get("tenant_id", "t")
    row.user_id = overrides.get("user_id", "u")
    row.agent_id = overrides.get("agent_id", "a")
    row.version_no = overrides.get("version_no", 1)
    row.parent_version_id = overrides.get("parent_version_id", None)
    row.run_id = overrides.get("run_id", 10)
    row.is_active = overrides.get("is_active", True)
    row.raw_content = overrides.get("raw_content", "raw")
    row.published_content = overrides.get("published_content", "pub")
    row.published_units = overrides.get("published_units", [])
    row.source_evidence_ids = overrides.get("source_evidence_ids", [])
    row.config_snapshot = overrides.get("config_snapshot", {})
    row.raw_char_count = overrides.get("raw_char_count", 3)
    row.published_char_count = overrides.get("published_char_count", 3)
    row.compression_status = overrides.get("compression_status", "not_needed")
    row.compression_attempts = overrides.get("compression_attempts", 0)
    row.omitted_evidence_ids = overrides.get("omitted_evidence_ids", [])
    row.mechanical_truncation = overrides.get("mechanical_truncation", False)
    row.compression_audit = overrides.get("compression_audit", [])
    row.create_time = overrides.get("create_time", datetime(2026, 7, 25))
    return row


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
# get_active_version
# ---------------------------------------------------------------------------


def test_get_active_version_returns_dict(monkeypatch):
    session = _mock_session(monkeypatch)
    row = _make_version_row(version_id=5, is_active=True)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = row

    result = memory_dreaming_db.get_active_version("t", "u", "a")

    assert result is not None
    assert result["version_id"] == 5
    assert result["is_active"] is True


def test_get_active_version_returns_none(monkeypatch):
    session = _mock_session(monkeypatch)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    result = memory_dreaming_db.get_active_version("t", "u", "a")

    assert result is None


# ---------------------------------------------------------------------------
# create_and_activate_version
# ---------------------------------------------------------------------------


def test_create_and_activate_version_returns_existing(monkeypatch):
    session = _mock_session(monkeypatch)
    existing = _make_version_row(version_id=7)
    session.query.return_value.filter.return_value.first.return_value = existing

    result = memory_dreaming_db.create_and_activate_version(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        run_id=10,
        parent_version_id=None,
        raw_content="raw",
        published_content="pub",
        published_units=[],
        source_evidence_ids=[],
        config_snapshot={},
        raw_char_count=3,
        published_char_count=3,
        compression_status="not_needed",
        compression_attempts=0,
        omitted_evidence_ids=[],
        mechanical_truncation=False,
        compression_audit=[],
    )

    assert result["version_id"] == 7
    session.add.assert_not_called()


def test_create_and_activate_version_creates_new(monkeypatch):
    session = _mock_session(monkeypatch)

    # First query: check for existing → None
    # Second query: get max version_no → 3
    query_mock = MagicMock()

    call_count = [0]

    def query_side_effect(model):
        call_count[0] += 1
        return query_mock

    session.query.side_effect = query_side_effect

    # First filter call: check existing → None
    # Second filter call: max version_no → 3
    # Third filter call: deactivate old active
    filter_count = [0]

    def filter_side_effect(*args, **kwargs):
        filter_count[0] += 1
        if filter_count[0] == 1:
            # Check for existing row
            result = MagicMock()
            result.first.return_value = None
            return result
        elif filter_count[0] == 2:
            # Max version_no
            result = MagicMock()
            result.scalar.return_value = 3
            return result
        else:
            # Deactivate old active versions
            result = MagicMock()
            return result

    query_mock.filter.side_effect = filter_side_effect

    added_row = None

    def capture_add(row):
        nonlocal added_row
        added_row = row
        row.version_id = 100
        row.version_no = 4

    session.add.side_effect = capture_add

    memory_dreaming_db.create_and_activate_version(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        run_id=10,
        parent_version_id=3,
        raw_content="raw content",
        published_content="pub content",
        published_units=[{"unit_id": "u1"}],
        source_evidence_ids=["1"],
        config_snapshot={"key": "val"},
        raw_char_count=11,
        published_char_count=11,
        compression_status="semantic",
        compression_attempts=1,
        omitted_evidence_ids=[],
        mechanical_truncation=False,
        compression_audit=[{"attempt": 1, "outcome": "accepted"}],
    )

    assert added_row is not None
    assert added_row.tenant_id == "t"
    assert added_row.version_no == 4
    assert added_row.parent_version_id == 3
    assert added_row.is_active is True
    assert added_row.created_by == "dreaming"
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


def test_list_versions(monkeypatch):
    session = _mock_session(monkeypatch)
    rows = [
        _make_version_row(version_id=1, version_no=2),
        _make_version_row(version_id=2, version_no=1),
    ]
    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = rows

    result = memory_dreaming_db.list_versions("t", "u", agent_id="a", limit=50)

    assert len(result) == 2
    assert result[0]["version_id"] == 1
    assert result[1]["version_id"] == 2


# ---------------------------------------------------------------------------
# activate_version
# ---------------------------------------------------------------------------


def test_activate_version_not_found(monkeypatch):
    session = _mock_session(monkeypatch)
    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = []

    result = memory_dreaming_db.activate_version("t", "u", "a", 999)

    assert result is None


def test_activate_version_already_active(monkeypatch):
    session = _mock_session(monkeypatch)
    row = _make_version_row(version_id=5, is_active=True)
    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [row]

    result = memory_dreaming_db.activate_version("t", "u", "a", 5)

    assert result["version_id"] == 5
    session.commit.assert_not_called()


def test_activate_version_switch(monkeypatch):
    session = _mock_session(monkeypatch)
    current = _make_version_row(version_id=5, is_active=True)
    target = _make_version_row(version_id=10, is_active=False)
    query_chain = MagicMock()
    session.query.return_value = query_chain

    filter_count = [0]

    def filter_side_effect(*args, **kwargs):
        filter_count[0] += 1
        result = MagicMock()
        if filter_count[0] == 1:
            result.all.return_value = [current, target]
        return result

    query_chain.filter.side_effect = filter_side_effect

    result = memory_dreaming_db.activate_version(
        "t", "u", "a", 10, actor_user_id="admin"
    )

    assert result["version_id"] == 10
    assert target.is_active is True
    assert target.updated_by == "admin"
    session.add.assert_called_once()
    audit_row = session.add.call_args[0][0]
    assert isinstance(audit_row, MemoryDreamingActivationAudit)
    assert audit_row.from_version_id == 5
    assert audit_row.to_version_id == 10
    assert audit_row.actor_user_id == "admin"
    session.commit.assert_called_once()


def test_activate_version_switch_no_current_active(monkeypatch):
    session = _mock_session(monkeypatch)
    target = _make_version_row(version_id=10, is_active=False)
    query_chain = MagicMock()
    session.query.return_value = query_chain

    filter_count = [0]

    def filter_side_effect(*args, **kwargs):
        filter_count[0] += 1
        result = MagicMock()
        if filter_count[0] == 1:
            result.all.return_value = [target]
        return result

    query_chain.filter.side_effect = filter_side_effect

    result = memory_dreaming_db.activate_version("t", "u", "a", 10)

    assert result["version_id"] == 10
    audit_row = session.add.call_args[0][0]
    assert audit_row.from_version_id is None
    assert audit_row.created_by == "u"


# ---------------------------------------------------------------------------
# _version_to_dict
# ---------------------------------------------------------------------------


def test_version_to_dict_handles_none_fields():
    row = MagicMock(spec=MemoryDreamingVersion)
    row.version_id = 1
    row.tenant_id = "t"
    row.user_id = "u"
    row.agent_id = "a"
    row.version_no = 1
    row.parent_version_id = None
    row.run_id = 10
    row.is_active = True
    row.raw_content = "raw"
    row.published_content = "pub"
    row.published_units = None
    row.source_evidence_ids = None
    row.config_snapshot = None
    row.raw_char_count = 3
    row.published_char_count = 3
    row.compression_status = "not_needed"
    row.compression_attempts = 0
    row.omitted_evidence_ids = None
    row.mechanical_truncation = False
    row.compression_audit = None
    row.create_time = None

    result = memory_dreaming_db._version_to_dict(row)

    assert result["published_units"] == []
    assert result["source_evidence_ids"] == []
    assert result["config_snapshot"] == {}
    assert result["omitted_evidence_ids"] == []
    assert result["compression_audit"] == []
    assert result["created_at"] is None


# ---------------------------------------------------------------------------
# update_audit
# ---------------------------------------------------------------------------


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
    audit_row.result_json = {"status": "completed"}
    audit_row.error = None

    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = [audit_row]

    result = memory_dreaming_db.list_audits(
        "t", "u", agent_id="a", run_id=1, limit=50
    )

    assert len(result) == 1
    assert result[0]["run_id"] == 1
    assert result[0]["status"] == "completed"
    assert result[0]["started_at"] is not None
    assert result[0]["finished_at"] is not None


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
    audit_row.result_json = None
    audit_row.error = None

    query_chain = MagicMock()
    session.query.return_value = query_chain
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = [audit_row]

    result = memory_dreaming_db.list_audits("t", "u")

    assert result[0]["started_at"] is None
    assert result[0]["finished_at"] is None
