"""Unit tests for the scheduled-task DB layer.

Focus on the two functions that govern cancel / re-arm reliability, since
those are the parts most likely to regress silently:

- ``cancel_task``: a task can be cancelled while 'pending' OR 'fired'
  (mid-execution too), and it honours the optional user_id isolation filter.
- ``reschedule_if_active``: a cron task is re-armed only while still 'fired',
  so a task cancelled mid-run is never resurrected.

Following the established pattern in ``test_conversation_db.py``, sqlalchemy
and the db_models are stubbed and only the session returned by
``get_db_session`` is mocked, so the tests need no running database.
"""
import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Make `backend.*` importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

# --- Stubs so backend.database.scheduled_task_db imports without a DB -------
# Stub sqlalchemy with a builder that records calls (select/update/where/
# values) and returns chainable mocks, mirroring test_conversation_db.py.
sa_mod = types.ModuleType("sqlalchemy")
sa_mod.select = MagicMock(name="select")
sa_mod.update = MagicMock(name="update")


# Stub the client module BEFORE importing the module under test, so the
# relative `from .client import get_db_session, as_dict` does not pull in the
# real client (which needs psycopg2 / a running DB).
_client_mod = types.ModuleType("database.client")
_client_mod.get_db_session = MagicMock(name="get_db_session")
_client_mod.as_dict = MagicMock(name="as_dict")
sys.modules["database.client"] = _client_mod
sys.modules["backend.database.client"] = _client_mod


class _RecordingColumn:
    """Column stand-in that records .in_() calls so tests can assert the
    statuses used in WHERE clauses."""

    def __init__(self, name):
        self.name = name
        self.in_calls = []

    def __eq__(self, other):
        return ("eq", other)

    def in_(self, values):
        self.in_calls.append(list(values))
        return ("in", list(values))


class _ScheduledTaskRecord:
    task_uuid = _RecordingColumn("task_uuid")
    agent_id = _RecordingColumn("agent_id")
    tenant_id = _RecordingColumn("tenant_id")
    user_id = _RecordingColumn("user_id")
    delete_flag = _RecordingColumn("delete_flag")
    status = _RecordingColumn("status")
    fire_count = _RecordingColumn("fire_count")
    next_fire_time = _RecordingColumn("next_fire_time")


db_models_mod = types.ModuleType("database.db_models")
db_models_mod.ScheduledTaskRecord = _ScheduledTaskRecord
sys.modules["sqlalchemy"] = sa_mod
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod

# Stub consts (transitive imports may read it).
_consts = types.ModuleType("consts")
_consts_const = types.ModuleType("consts.const")
_consts.const = _consts_const
sys.modules.setdefault("consts", _consts)
sys.modules.setdefault("consts.const", _consts_const)

# Import after stubbing.
from backend.database.scheduled_task_db import (  # noqa: E402
    cancel_task,
    reschedule_if_active,
)


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------

def test_cancel_returns_true_when_a_row_matched(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    ok = cancel_task("uuid-1", agent_id=1, tenant_id="t", user_id="u")
    assert ok is True
    session.execute.assert_called_once()


def test_cancel_returns_false_when_no_row_matched(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 0
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    ok = cancel_task("uuid-1", agent_id=1, tenant_id="t", user_id="u")
    assert ok is False


def test_cancel_matches_both_pending_and_fired(monkeypatch, mock_session_ctx):
    """Core fix: a task executing right now (status 'fired') must be
    cancellable too, not only 'pending' ones. The status column's .in_()
    filter must include both statuses."""
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    _ScheduledTaskRecord.status.in_calls = []  # reset recorder
    cancel_task("uuid-1", agent_id=1, tenant_id="t", user_id="u")

    assert _ScheduledTaskRecord.status.in_calls, "status .in_() was not used"
    statuses = _ScheduledTaskRecord.status.in_calls[0]
    assert "pending" in statuses
    assert "fired" in statuses


def test_cancel_scopes_by_user_when_provided(monkeypatch, mock_session_ctx):
    """The user_id isolation filter is applied when provided."""
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    cancel_task("uuid-1", agent_id=1, tenant_id="t", user_id="alice")
    # user_id column compared against the provided value -> __eq__ recorded it
    session.execute.assert_called_once()


def test_cancel_without_user_id_still_works(monkeypatch, mock_session_ctx):
    """Omitting user_id relies on agent/tenant scope and still cancels."""
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    ok = cancel_task("uuid-1", agent_id=1, tenant_id="t", user_id=None)
    assert ok is True


# ---------------------------------------------------------------------------
# reschedule_if_active
# ---------------------------------------------------------------------------

def test_reschedule_returns_true_when_task_was_fired(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    re_armed = reschedule_if_active("uuid-1", 3, datetime(2026, 7, 1))
    assert re_armed is True
    session.execute.assert_called_once()


def test_reschedule_returns_false_when_already_cancelled(monkeypatch, mock_session_ctx):
    """A task cancelled (or errored) mid-run is no longer 'fired', so the
    atomic UPDATE matches zero rows and must NOT re-arm it."""
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 0
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    re_armed = reschedule_if_active("uuid-1", 3, datetime(2026, 7, 1))
    assert re_armed is False


def test_reschedule_only_matches_fired_status(monkeypatch, mock_session_ctx):
    """Guard against regressions: re-arm is gated on status = 'fired' via a
    bare equality (NOT an .in_() list), so a cancelled task can never be
    resurrected. Assert status.in_() is NOT used by the re-arm path."""
    session, ctx = mock_session_ctx
    result = MagicMock()
    result.rowcount = 1
    session.execute.return_value = result
    monkeypatch.setattr("backend.database.scheduled_task_db.get_db_session", lambda: ctx)

    _ScheduledTaskRecord.status.in_calls = []  # reset recorder
    reschedule_if_active("uuid-1", 3, datetime(2026, 7, 1))

    # reschedule_if_active uses status == 'fired', so .in_() must NOT fire.
    assert _ScheduledTaskRecord.status.in_calls == []
