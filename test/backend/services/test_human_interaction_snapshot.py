"""Unit tests for the read-path snapshot split (snapshot / light_snapshot)
and the repository read_only context manager.

The Postgres-backed suite in test_human_interaction.py skips without a real
database, so these mocks keep the read-path lines covered in CI. No real
database is required.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from database.human_interaction_db import HumanInteractionRepository, RunTransaction
from services.human_interaction.models import InteractionError
from services.human_interaction.service import HumanInteractionService


def _future_lock():
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _make_run(**overrides):
    run = SimpleNamespace(
        run_id="run-1",
        conversation_id=7,
        status="WAITING_HUMAN",
        event_seq=4,
        pause_requested=True,
        lock_until=_future_lock(),
    )
    for key, value in overrides.items():
        setattr(run, key, value)
    return run


def _yielding_ctx(value):
    """Fresh single-use context manager yielding ``value`` (exception-safe)."""

    @contextmanager
    def ctx():
        yield value

    return ctx()


def _make_service(tx):
    repo = MagicMock()
    repo.read_only.side_effect = lambda *a, **k: _yielding_ctx(tx)
    repo.transaction.side_effect = lambda *a, **k: _yielding_ctx(tx)
    service = HumanInteractionService(repository=repo, cipher=MagicMock(), wait_seconds=60)
    return service, repo


def _snapshot_tx(run):
    tx = MagicMock()
    tx.run = run
    tx.requests.return_value = []
    return tx


# --- service.light_snapshot ---------------------------------------------------

def test_light_snapshot_builds_snapshot_without_writer_path():
    run = _make_run()
    tx = _snapshot_tx(run)
    service, repo = _make_service(tx)

    snap = service.light_snapshot("run-1", "tenant-1", "user-1")

    assert snap["run_id"] == "run-1"
    assert snap["conversation_id"] == 7
    assert snap["status"] == "WAITING_HUMAN"
    assert snap["event_seq"] == 4
    assert snap["pause_requested"] is True
    assert snap["attempt_active"] is True
    # Read path only: no write transaction, no expiration side effects.
    repo.read_only.assert_called_once_with("run-1", "tenant-1", "user-1")
    repo.transaction.assert_not_called()


def test_light_snapshot_missing_run_raises_404():
    service, repo = _make_service(None)

    with pytest.raises(InteractionError, match="not found"):
        service.light_snapshot("run-1", "tenant-1", "user-1")


# --- service.snapshot (writer path) -------------------------------------------

def test_snapshot_takes_write_transaction_and_expires():
    run = _make_run()
    tx = _snapshot_tx(run)
    service, repo = _make_service(tx)

    with patch.object(service, "_expire") as expire:
        snap = service.snapshot("run-1", "tenant-1", "user-1")

    assert snap["run_id"] == "run-1"
    expire.assert_called_once()
    repo.transaction.assert_called_once_with("run-1", "tenant-1", "user-1")
    repo.read_only.assert_not_called()


# --- repository.read_only ------------------------------------------------------

def _repo_with_session(session):
    factory = MagicMock(side_effect=lambda: _yielding_ctx(session))
    return HumanInteractionRepository(session_factory=factory), factory


def test_read_only_yields_transaction_without_lock_or_writes():
    run = _make_run()
    session = MagicMock()
    session.scalar.return_value = run
    repo, factory = _repo_with_session(session)

    with repo.read_only("run-1", "tenant-1", "user-1") as tx:
        assert isinstance(tx, RunTransaction)
        assert tx.run is run
        assert tx.actor == "user-1"

    # Plain SELECT: no FOR UPDATE lock row, no flush, no commit.
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    factory.assert_called_once_with()


def test_read_only_missing_run_yields_none():
    session = MagicMock()
    session.scalar.return_value = None
    repo, _ = _repo_with_session(session)

    with repo.read_only("run-1") as tx:
        assert tx is None


def test_read_only_works_with_and_without_tenant_scope():
    run = _make_run()
    session = MagicMock()
    session.scalar.return_value = run
    repo, _ = _repo_with_session(session)

    with repo.read_only("run-1", "tenant-1", "user-1") as scoped:
        assert scoped is not None
    with repo.read_only("run-1") as unscoped:
        assert unscoped is not None
    assert session.scalar.call_count == 2
