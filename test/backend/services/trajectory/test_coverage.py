# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Separate conversation source completeness from the currently returned page."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from ops.services.trajectory.access import Actor
from ops.services.trajectory.archive import Archive
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.service import TrajectoryService


@pytest.fixture
def service():
    now = datetime.now(UTC)
    catalog = Mock()
    catalog.tenants.return_value = ["t"]
    catalog.actor_active.return_value = True
    catalog.resolve.return_value = {
        "tenant_id": "t",
        "user_id": "u",
        "conversation_id": "1",
        "conversation_title": "Title",
    }
    catalog.message_upper.return_value = 3
    catalog.messages.return_value = []
    runs = [
        {
            "trajectory_id": str(uuid4()),
            "turn_no": i,
            "publication_no": i,
            "root_agent_id": "7",
            "core_type": "smolagents",
            "business_status": "completed",
            "capture_state": "ready",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
        }
        for i in (1, 2)
    ]
    meta = {
        "runs": runs,
        "publication_no": 2,
        "cleanup_version": 0,
        "captured_from_start": True,
    }
    result = TrajectoryService(Mock(), catalog, ReferenceStore())
    result.archive = SimpleNamespace(
        manifest=Mock(return_value=meta),
        available=lambda run: Archive.available(result.archive, run),
        store=SimpleNamespace(clock=lambda: now),
    )
    return result


def view(service, **kwargs):
    return service.conversation(Actor("admin", "t", "ADMIN"), "1", **kwargs)


def messages():
    return [
        {
            "message_id": str(i),
            "preview": "你好",
            "char_count": 2,
            "byte_count": 6,
            "hash": str(i),
        }
        for i in (1, 2)
    ]


def test_complete_sources_remain_complete_with_more_pages(service):
    service.catalog.messages.return_value = messages()
    result = view(service, include="messages", limit=1)
    coverage = result["coverage"]
    assert coverage["complete"] is True
    assert coverage["conversation"] == {
        "complete": True,
        "reasons": [],
        "scope": "conversation",
        "has_more": True,
    }
    window = coverage["retention_window"]
    assert window["complete"] is True and window["reasons"] == []
    assert window["execution_count"] == 2
    assert window["publication_no"] == "2" and window["basis"] == "manifest"
    assert coverage["chat"] == {
        "complete": True,
        "reasons": [],
        "scope": "current_messages",
        "message_id_upper": "3",
        "has_more": True,
    }
    assert result["next_cursor"] and result["message_cursor"]
    assert len(result["messages"]) == len(result["executions"]) == 1


def test_unrequested_chat_is_unknown_and_never_loads_messages(service):
    result = view(service)
    assert result["coverage"]["chat"]["complete"] is None
    assert result["coverage"]["chat"]["reasons"] == ["not_requested"]
    assert result["coverage"]["chat"]["has_more"] is None
    assert "messages" not in result
    service.catalog.messages.assert_not_called()


@pytest.mark.parametrize("state", ["partial", "corrupt", "unarchived", "expired"])
def test_hidden_execution_state_changes_source_coverage(service, state):
    meta = service.archive.manifest.return_value
    hidden = meta["runs"][1]
    if state == "partial":
        hidden["capture_state"] = "incomplete"
    elif state == "unarchived":
        hidden["capture_state"] = "writing"
        hidden["publication_no"] = None
    elif state == "expired":
        hidden["expires_at"] = (
            service.archive.store.clock() - timedelta(seconds=1)
        ).isoformat()
    else:
        hidden["capture_state"] = "corrupt"

    result = view(service, limit=1)
    assert len(result["executions"]) == 1
    assert result["executions"][0]["availability"] == "available"
    coverage = result["coverage"]
    assert coverage["complete"] is False
    assert state in coverage["reasons"]
    assert coverage["conversation"]["complete"] is False
    assert state in coverage["conversation"]["reasons"]
    window = coverage["retention_window"]
    assert window["complete"] is (state == "expired")
    if state == "expired":
        assert window["execution_count"] == 1
        assert "expired" not in window["reasons"]
    else:
        assert state in window["reasons"]


def test_expired_history_does_not_invalidate_clean_retained_window(service):
    meta = service.archive.manifest.return_value
    meta["had_expired_history"] = True
    result = view(service)
    assert result["coverage"]["conversation"]["complete"] is False
    assert "had_expired_history" in result["coverage"]["conversation"]["reasons"]
    assert result["coverage"]["retention_window"]["complete"] is True


def test_manual_cleanup_in_manifest_invalidates_retained_scope(service):
    meta = service.archive.manifest.return_value
    meta["runs"][1].update(cleanup_reason="manual", capture_state="expired")
    coverage = view(service, limit=1)["coverage"]
    assert coverage["retention_window"]["complete"] is False
    assert "had_manual_cleanup" in coverage["retention_window"]["reasons"]
    assert coverage["retention_window"]["execution_count"] == 1
    assert "expired" in coverage["conversation"]["reasons"]


def test_expiry_during_final_authorization_updates_states_and_coverage(service):
    row = service.catalog.resolve.return_value
    later = service.archive.store.clock() + timedelta(days=31)

    def resolve(*args, **kwargs):
        if service.catalog.resolve.call_count == 2:
            service.archive.store.clock = lambda: later
        return row

    service.catalog.resolve.side_effect = resolve
    result = view(service, include="messages", limit=1)
    assert result["availability"] == "expired"
    assert result["executions"][0]["availability"] == "expired"
    assert result["coverage"]["chat"]["complete"] is True
    assert "expired" in result["coverage"]["conversation"]["reasons"]
    assert result["coverage"]["retention_window"]["complete"] is True
    assert result["coverage"]["retention_window"]["execution_count"] == 0


def test_final_manifest_state_is_used_for_returned_execution(service):
    initial = service.archive.manifest.return_value
    current = deepcopy(initial)
    current["runs"][0]["capture_state"] = "corrupt"
    service.archive.manifest.side_effect = [initial, current]
    result = view(service)
    assert result["executions"][0]["availability"] == "corrupt"
    assert "corrupt" in result["coverage"]["retention_window"]["reasons"]


def test_manifest_disappearance_invalidates_conversation_snapshot(service):
    initial = service.archive.manifest.return_value
    service.archive.manifest.side_effect = [initial, None]
    with pytest.raises(QueryError, match="snapshot_reset") as error:
        view(service)
    assert error.value.status == 409


@pytest.mark.parametrize(
    "flag", ["has_uncaptured_history", "had_capture_gap", "had_manual_cleanup"]
)
def test_unlocalized_history_gaps_are_not_claimed_complete(service, flag):
    service.archive.manifest.return_value[flag] = True
    coverage = view(service)["coverage"]
    assert coverage["retention_window"]["complete"] is False
    assert flag in coverage["retention_window"]["reasons"]
    assert coverage["conversation"]["complete"] is False


def test_unknown_capture_start_is_reported_in_both_trajectory_scopes(service):
    service.archive.manifest.return_value["captured_from_start"] = False
    coverage = view(service)["coverage"]
    for scope in ("retention_window", "conversation"):
        assert coverage[scope]["complete"] is False
        assert "capture_start_unknown" in coverage[scope]["reasons"]


def test_uncaptured_trajectory_does_not_hide_readable_chat(service):
    service.archive.manifest.return_value = None
    service.catalog.messages.return_value = messages()[:1]
    result = view(service, include="messages")
    coverage = result["coverage"]
    assert coverage["chat"]["complete"] is True
    assert coverage["chat"]["has_more"] is False
    assert result["messages"][0]["preview"] == "你好"
    for scope in ("retention_window", "conversation"):
        assert coverage[scope]["complete"] is False
        assert "not_captured" in coverage[scope]["reasons"]
    assert coverage["retention_window"]["execution_count"] == 0


def test_new_publication_does_not_change_old_snapshot_coverage(service):
    initial = view(service)
    meta = service.archive.manifest.return_value
    meta["runs"].append(
        {
            **meta["runs"][0],
            "trajectory_id": str(uuid4()),
            "turn_no": 3,
            "publication_no": 3,
            "capture_state": "incomplete",
        }
    )
    meta["publication_no"] = 3
    old = view(service, snapshot_id=initial["snapshot_id"])
    assert old["coverage"] == initial["coverage"]
    assert old["coverage"]["retention_window"]["execution_count"] == 2
    refreshed = view(service)
    assert refreshed["coverage"]["retention_window"]["execution_count"] == 3
    assert "partial" in refreshed["coverage"]["conversation"]["reasons"]


def test_message_page_keeps_snapshot_upper_bound(service):
    service.catalog.messages.return_value = messages()
    initial = view(service, include="messages", limit=1)
    service.catalog.message_upper.return_value = 99
    service.catalog.messages.return_value = messages()[1:]
    result = view(
        service, include="messages", message_cursor=initial["message_cursor"], limit=1
    )
    assert result["coverage"]["chat"]["message_id_upper"] == "3"
    assert result["coverage"]["chat"]["complete"] is True
    assert result["coverage"]["chat"]["has_more"] is False
    service.catalog.messages.assert_called_with("1", 3, "1", 1)


@pytest.mark.parametrize(
    "character, count", [("x", 2 * 1024 * 1024), ("中", 700_000), ("😀", 600_000)]
)
def test_conversation_response_enforces_combined_byte_budget(service, character, count):
    service.archive.manifest.return_value["runs"][0]["safe_error"] = character * count
    with pytest.raises(QueryError, match="conversation_page_budget_exceeded") as error:
        view(service)
    assert error.value.status == 503 and error.value.retry_after == 2
