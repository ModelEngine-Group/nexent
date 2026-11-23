"""Unit tests for Dreaming lease store DB functions (AC-028, AC-029, AC-030)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from database import memory_dreaming_db


def _mock_session(monkeypatch, module=None):
    target = module or memory_dreaming_db
    session = MagicMock()

    @contextmanager
    def _ctx():
        yield session

    monkeypatch.setattr(target, "get_db_session", _ctx)
    return session


# ---------------------------------------------------------------------------
# AC-028: claim_queued
# ---------------------------------------------------------------------------


def test_ac028_claim_queued_returns_payload(monkeypatch):
    session = _mock_session(monkeypatch)
    row = MagicMock()
    row._mapping = {
        "run_id": 42,
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": "a1",
        "trigger_source": "manual",
    }
    session.execute.return_value.fetchone.return_value = row

    result = memory_dreaming_db.claim_queued("worker-1", 120.0)

    assert result == {
        "run_id": 42,
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": "a1",
        "trigger_source": "manual",
    }
    sql_text = str(session.execute.call_args[0][0])
    assert "FOR UPDATE SKIP LOCKED" in sql_text
    assert "LIMIT 1" in sql_text
    assert "status = 'queued'" in sql_text
    assert "lock_owner" in sql_text
    assert "lock_until" in sql_text


def test_ac028_claim_queued_returns_none_when_empty(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.fetchone.return_value = None

    result = memory_dreaming_db.claim_queued("worker-1", 120.0)

    assert result is None


# ---------------------------------------------------------------------------
# AC-029: renew_lease
# ---------------------------------------------------------------------------


def test_ac029_renew_lease_succeeds_when_owned(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar_one_or_none.return_value = 42

    result = memory_dreaming_db.renew_lease(42, "worker-1", 120.0)

    assert result is True
    sql_text = str(session.execute.call_args[0][0])
    assert "lock_owner = :owner_id" in sql_text
    assert "lock_until > now()" in sql_text


def test_ac029_renew_lease_fails_on_owner_mismatch(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = memory_dreaming_db.renew_lease(42, "wrong-worker", 120.0)

    assert result is False


def test_ac029_renew_lease_fails_on_expired(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = memory_dreaming_db.renew_lease(42, "worker-1", 120.0)

    assert result is False


# ---------------------------------------------------------------------------
# AC-030: release_lease
# ---------------------------------------------------------------------------


def test_ac030_release_lease_succeeds_when_owned(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar_one_or_none.return_value = 42

    result = memory_dreaming_db.release_lease(42, "worker-1")

    assert result is True
    sql_text = str(session.execute.call_args[0][0])
    assert "lock_owner = NULL" in sql_text
    assert "lock_until = NULL" in sql_text
    assert "lock_owner = :owner_id" in sql_text


def test_ac030_release_lease_fails_on_wrong_owner(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = memory_dreaming_db.release_lease(42, "wrong-worker")

    assert result is False


# ---------------------------------------------------------------------------
# AC-030: recover_stale
# ---------------------------------------------------------------------------


def test_ac030_recover_stale_marks_expired_as_failed(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.rowcount = 3

    result = memory_dreaming_db.recover_stale()

    assert result == 3
    sql_text = str(session.execute.call_args[0][0])
    assert "status = 'failed'" in sql_text
    assert "lock_until < now()" in sql_text
    assert "status = 'running'" in sql_text
    assert "lock_owner = NULL" in sql_text


def test_ac030_recover_stale_returns_zero_when_clean(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.rowcount = 0

    result = memory_dreaming_db.recover_stale()

    assert result == 0


def test_startup_recovery_includes_unexpired_running_leases(monkeypatch):
    session = _mock_session(monkeypatch)
    session.execute.return_value.rowcount = 2

    result = memory_dreaming_db.recover_stale(include_unexpired=True)

    assert result == 2
    sql_text = str(session.execute.call_args[0][0])
    assert "status = 'running'" in sql_text
    assert "lock_until < now()" not in sql_text
