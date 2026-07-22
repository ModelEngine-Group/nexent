"""Focused tests for durable NL2AGENT installation operations."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from database import nl2agent_installation_db as repository
from database.nl2agent_session_db import Nl2AgentSessionIdentity


@contextmanager
def _session_context(session):
    yield session


def _identity() -> Nl2AgentSessionIdentity:
    return Nl2AgentSessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        runner_agent_id=7,
        draft_agent_id=11,
        conversation_id=22,
    )


def _record(**overrides):
    values = {
        "operation_id": "operation-a",
        "request_fingerprint": "fingerprint-a",
        "status": "running",
        "lease_owner": "owner-a",
        "lease_expires_at": datetime.utcnow() + timedelta(minutes=2),
        "attempt": 1,
        "error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _claim_session(monkeypatch, record):
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = record
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        repository, "get_db_session", lambda: _session_context(session)
    )
    monkeypatch.setattr(repository, "as_dict", lambda value: vars(value).copy())
    return session


def test_claim_replays_completed_operation_without_new_attempt(monkeypatch):
    record = _record(status="completed", result={"mcp_id": 5})
    session = _claim_session(monkeypatch, record)

    result = repository.claim_installation_operation(
        identity=_identity(),
        operation_id="operation-a",
        installation_key="stable-key",
        request_fingerprint="fingerprint-a",
        resource_type="mcp",
        lease_owner="owner-b",
        lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
    )

    assert result["status"] == "completed"
    assert result["result"] == {"mcp_id": 5}
    assert record.attempt == 1
    session.flush.assert_not_called()


def test_claim_rejects_another_live_lease(monkeypatch):
    _claim_session(monkeypatch, _record())

    with pytest.raises(repository.InstallationLeaseConflictError):
        repository.claim_installation_operation(
            identity=_identity(),
            operation_id="operation-a",
            installation_key="stable-key",
            request_fingerprint="fingerprint-a",
            resource_type="mcp",
            lease_owner="owner-b",
            lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
        )


def test_claim_takes_over_expired_lease(monkeypatch):
    record = _record(lease_expires_at=datetime.utcnow() - timedelta(seconds=1))
    session = _claim_session(monkeypatch, record)

    result = repository.claim_installation_operation(
        identity=_identity(),
        operation_id="operation-a",
        installation_key="stable-key",
        request_fingerprint="fingerprint-a",
        resource_type="mcp",
        lease_owner="owner-b",
        lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
    )

    assert result["lease_owner"] == "owner-b"
    assert result["attempt"] == 2
    session.flush.assert_called_once()


def test_completed_transition_clears_lease_and_redacted_error(monkeypatch):
    query = MagicMock()
    query.filter.return_value = query
    query.update.return_value = 1
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        repository, "get_db_session", lambda: _session_context(session)
    )

    assert repository.transition_installation_operation(
        operation_id="operation-a",
        lease_owner="owner-a",
        status="completed",
        checkpoint={"provider_persisted": True},
        result={"mcp_id": 5},
    )
    values = query.update.call_args.args[0]
    assert values["status"] == "completed"
    assert values["lease_owner"] is None
    assert values["lease_expires_at"] is None
    assert values["error"] is None
