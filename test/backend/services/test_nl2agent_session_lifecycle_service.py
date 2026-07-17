"""Tests for owner-scoped NL2AGENT session discovery and lifecycle policy."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from consts.exceptions import Nl2AgentDraftNotFoundError, Nl2AgentValidationError
from services import nl2agent_session_lifecycle_service as lifecycle


def _record(**overrides):
    return {
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "active",
        "create_time": datetime(2026, 7, 1),
        "update_time": datetime(2026, 7, 2),
        **overrides,
    }


def test_resolve_active_session_uses_tenant_user_and_conversation(monkeypatch):
    lookup = MagicMock(return_value=_record())
    monkeypatch.setattr(lifecycle, "get_nl2agent_session_by_conversation", lookup)

    result = lifecycle.resolve_active_session(
        conversation_id=902,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["draft_agent_id"] == 202
    assert "workflow_state" not in result
    lookup.assert_called_once_with("tenant-a", "user-a", 902)


def test_resolve_active_session_does_not_disclose_missing_or_foreign_session(
    monkeypatch,
):
    monkeypatch.setattr(
        lifecycle,
        "get_nl2agent_session_by_conversation",
        MagicMock(return_value=None),
    )

    with pytest.raises(Nl2AgentDraftNotFoundError):
        lifecycle.resolve_active_session(
            conversation_id=902,
            tenant_id="tenant-a",
            user_id="user-a",
        )


def test_list_active_sessions_bounds_limit_and_projects_public_fields(monkeypatch):
    list_rows = MagicMock(return_value=[_record(), _record(draft_agent_id=203)])
    monkeypatch.setattr(lifecycle, "list_nl2agent_sessions", list_rows)

    result = lifecycle.list_active_sessions(
        tenant_id="tenant-a",
        user_id="user-a",
        limit=1000,
    )

    assert [row["draft_agent_id"] for row in result] == [202, 203]
    list_rows.assert_called_once_with("tenant-a", "user-a", limit=100)


def test_list_active_sessions_rejects_non_integer_limit():
    with pytest.raises(Nl2AgentValidationError, match="limit"):
        lifecycle.list_active_sessions(
            tenant_id="tenant-a",
            user_id="user-a",
            limit=True,
        )


def test_abandon_session_is_owner_scoped_and_evicts_cache(monkeypatch):
    lookup = MagicMock(return_value=_record())
    update = MagicMock(return_value=True)
    evict = MagicMock()
    monkeypatch.setattr(lifecycle, "get_nl2agent_session", lookup)
    monkeypatch.setattr(lifecycle, "update_nl2agent_session_status", update)
    monkeypatch.setattr(lifecycle, "delete_nl2agent_session_catalogs", evict)

    result = lifecycle.abandon_session(
        draft_agent_id=202,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["status"] == "abandoned"
    lookup.assert_called_once_with("tenant-a", 202, user_id="user-a")
    update.assert_called_once_with(
        tenant_id="tenant-a",
        draft_agent_id=202,
        status="abandoned",
        user_id="user-a",
    )
    evict.assert_called_once_with("tenant-a", 202)


def test_abandon_session_rejects_terminal_session(monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "get_nl2agent_session",
        MagicMock(return_value=_record(status="completed")),
    )

    with pytest.raises(Nl2AgentDraftNotFoundError):
        lifecycle.abandon_session(
            draft_agent_id=202,
            tenant_id="tenant-a",
            user_id="user-a",
        )


def test_abandon_session_by_conversation_is_owner_scoped(monkeypatch):
    lookup = MagicMock(return_value=_record())
    update = MagicMock(return_value=True)
    evict = MagicMock()
    monkeypatch.setattr(lifecycle, "get_nl2agent_session_by_conversation", lookup)
    monkeypatch.setattr(lifecycle, "update_nl2agent_session_status", update)
    monkeypatch.setattr(lifecycle, "delete_nl2agent_session_catalogs", evict)

    result = lifecycle.abandon_session_by_conversation(
        conversation_id=902,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result is not None
    assert result["status"] == "abandoned"
    lookup.assert_called_once_with("tenant-a", "user-a", 902)
    update.assert_called_once_with(
        tenant_id="tenant-a",
        draft_agent_id=202,
        status="abandoned",
        user_id="user-a",
    )
    evict.assert_called_once_with("tenant-a", 202)


def test_abandon_session_by_conversation_ignores_normal_conversation(monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "get_nl2agent_session_by_conversation",
        MagicMock(return_value=None),
    )
    update = MagicMock()
    monkeypatch.setattr(lifecycle, "update_nl2agent_session_status", update)

    assert (
        lifecycle.abandon_session_by_conversation(
            conversation_id=902,
            tenant_id="tenant-a",
            user_id="user-a",
        )
        is None
    )
    update.assert_not_called()


def test_cleanup_uses_configured_retention_and_batch(monkeypatch):
    cleanup = MagicMock(return_value=4)
    monkeypatch.setattr(lifecycle, "cleanup_abandoned_nl2agent_sessions", cleanup)
    monkeypatch.setattr(lifecycle, "NL2AGENT_ABANDONED_RETENTION_DAYS", 30)
    monkeypatch.setattr(lifecycle, "NL2AGENT_CLEANUP_BATCH_SIZE", 25)

    now = datetime(2026, 7, 17, 12, 0, 0)
    assert lifecycle.cleanup_expired_abandoned_sessions(now=now) == 4
    cleanup.assert_called_once_with(
        abandoned_before=datetime(2026, 6, 17, 12, 0, 0),
        limit=25,
    )
