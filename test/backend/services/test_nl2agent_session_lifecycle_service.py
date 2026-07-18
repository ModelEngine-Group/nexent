"""Tests for owner-scoped NL2AGENT session discovery and lifecycle policy."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from consts.exceptions import Nl2AgentDraftNotFoundError, Nl2AgentValidationError
from services import nl2agent_session_lifecycle_service as lifecycle


def _record(**overrides):
    return {
        "runner_agent_id": 101,
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
    assert result["nl2agent_agent_id"] == 101
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


def test_require_active_session_authorizes_owner_and_conversation(monkeypatch):
    lookup = MagicMock(return_value=_record())
    monkeypatch.setattr(lifecycle, "get_nl2agent_session", lookup)

    result = lifecycle.require_active_session(
        draft_agent_id=202,
        tenant_id="tenant-a",
        user_id="user-a",
        conversation_id=902,
    )

    assert result["runner_agent_id"] == 101
    lookup.assert_called_once_with("tenant-a", 202, user_id="user-a")


@pytest.mark.parametrize(
    "record,conversation_id",
    [(None, 902), (_record(status="completed"), 902), (_record(), 903)],
)
def test_require_active_session_rejects_missing_terminal_or_mismatched_session(
    monkeypatch, record, conversation_id
):
    monkeypatch.setattr(
        lifecycle,
        "get_nl2agent_session",
        MagicMock(return_value=record),
    )

    with pytest.raises(Nl2AgentDraftNotFoundError):
        lifecycle.require_active_session(
            draft_agent_id=202,
            tenant_id="tenant-a",
            user_id="user-a",
            conversation_id=conversation_id,
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
    abandon_stale = MagicMock(return_value=2)
    cleanup_abandoned = MagicMock(return_value=4)
    cleanup_completed = MagicMock(return_value=3)
    monkeypatch.setattr(
        lifecycle, "abandon_stale_active_nl2agent_sessions", abandon_stale
    )
    monkeypatch.setattr(
        lifecycle, "cleanup_abandoned_nl2agent_sessions", cleanup_abandoned
    )
    monkeypatch.setattr(
        lifecycle, "cleanup_completed_nl2agent_sessions", cleanup_completed
    )
    monkeypatch.setattr(lifecycle, "NL2AGENT_ACTIVE_RETENTION_DAYS", 14)
    monkeypatch.setattr(lifecycle, "NL2AGENT_ABANDONED_RETENTION_DAYS", 30)
    monkeypatch.setattr(lifecycle, "NL2AGENT_COMPLETED_RETENTION_DAYS", 60)
    monkeypatch.setattr(lifecycle, "NL2AGENT_CLEANUP_BATCH_SIZE", 25)

    now = datetime(2026, 7, 17, 12, 0, 0)
    assert lifecycle.cleanup_expired_sessions(now=now) == 7
    abandon_stale.assert_called_once_with(
        active_before=datetime(2026, 7, 3, 12, 0, 0),
        limit=25,
    )
    cleanup_abandoned.assert_called_once_with(
        abandoned_before=datetime(2026, 6, 17, 12, 0, 0),
        limit=25,
    )
    cleanup_completed.assert_called_once_with(
        completed_before=datetime(2026, 5, 18, 12, 0, 0),
        limit=25,
    )
