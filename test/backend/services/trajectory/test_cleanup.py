# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manual cleanup keeps fixed scope and records safe per-batch audit facts."""

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from infrastructure.observability.trajectory_io import TrajectoryConflict
from management.services.trajectory.access import Actor
from management.services.trajectory.cleanup import cleanup
from management.services.trajectory.primitives import QueryError, TokenSigner

ACTOR = Actor("admin", "tenant", "ADMIN")


def audit_events(caplog):
    return [
        json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
        for record in caplog.records
        if record.getMessage().startswith("trajectory.cleanup ")
    ]


@pytest.fixture
def service(caplog):
    caplog.set_level(logging.INFO)
    store = MagicMock()
    store.clock.return_value = datetime(2026, 11, 10, tzinfo=UTC)
    store.cleanup.return_value = {
        "scanned_runs": 2,
        "deleted_runs": 1,
        "deleted_bytes": 123,
        "skipped_active": 1,
        "pending_runs": 0,
        "failed_runs": 0,
        "next_turn": None,
    }
    catalog = Mock()
    catalog.tenants.return_value = ["tenant"]
    catalog.actor_active.return_value = True
    catalog.cleanup_candidates.return_value = [
        {"tenant_id": "tenant", "user_id": "owner", "conversation_id": "1"},
    ]
    return SimpleNamespace(
        archive=SimpleNamespace(store=store, manifest=Mock(return_value={"runs": []})),
        catalog=catalog,
        signer=TokenSigner("a" * 32),
        recheck=Mock(),
    )


def test_manual_audit_records_actor_scope_cutoff_and_actual_counts(service, caplog):
    result = cleanup(service, ACTOR, 7)
    (event,) = audit_events(caplog)
    assert result["done"] and result["deleted_runs"] == 1
    assert event["source"] == "manual" and event["actor_id"] == "admin"
    assert event["tenant_id"] == "tenant" and event["before_days"] == 7
    assert event["cutoff_at"] == result["cutoff_at"] == "2026-11-03T00:00:00Z"
    assert event["deleted_runs"] == 1 and event["deleted_bytes"] == 123
    assert event["scanned_runs"] == 2 and event["skipped_active"] == 1
    assert event["status"] == "success" and event["counts_complete"]
    assert event["error_code"] is None
    service.catalog.cleanup_candidates.assert_called_once_with("tenant", 0, limit=1001)


@pytest.mark.parametrize(
    "field,status", [("pending_runs", "pending"), ("failed_runs", "failed")]
)
def test_manual_audit_distinguishes_pending_and_failed_batches(
    service, caplog, field, status
):
    service.archive.store.cleanup.return_value[field] = 1
    result = cleanup(service, ACTOR, 7)
    (event,) = audit_events(caplog)
    assert result["done"] and result[field] == 1
    assert event["status"] == status and event[field] == 1
    assert event["error_code"] == ("delete_failed" if field == "failed_runs" else None)


def test_manual_audit_keeps_first_cutoff_on_cursor_continuation(service, caplog):
    service.archive.store.cleanup.return_value["next_turn"] = 2
    first = cleanup(service, ACTOR, 7)
    service.archive.store.clock.return_value += timedelta(days=2)
    service.archive.store.cleanup.return_value["next_turn"] = None
    second = cleanup(service, ACTOR, 7, first["next_cursor"])
    events = audit_events(caplog)
    assert len(events) == 2
    assert (
        events[0]["cutoff_at"]
        == events[1]["cutoff_at"]
        == first["cutoff_at"]
        == second["cutoff_at"]
    )
    assert service.archive.store.cleanup.call_args.kwargs["after_turn"] == 2
    assert first["next_cursor"] not in caplog.text


@pytest.mark.parametrize(
    "error,code,status",
    [
        (OSError("/private/path?token=private"), "storage_unavailable", 503),
        (TrajectoryConflict("locked /private/path"), "cleanup_busy", 409),
        (QueryError("trajectory_not_found", 404), "trajectory_not_found", 404),
    ],
)
def test_manual_audit_preserves_errors_without_logging_sensitive_detail(
    service, caplog, error, code, status
):
    service.archive.store.cleanup.side_effect = error
    with pytest.raises(QueryError) as raised:
        cleanup(service, ACTOR, 7)
    assert raised.value.code == code and raised.value.status == status
    (event,) = audit_events(caplog)
    assert event["status"] == "failed" and event["error_code"] == code
    assert not event["counts_complete"]
    assert "/private/path" not in caplog.text and "token=private" not in caplog.text


def test_manual_audit_retains_completed_counts_when_later_conversation_fails(
    service, caplog
):
    service.catalog.cleanup_candidates.return_value.append(
        {"tenant_id": "tenant", "user_id": "owner", "conversation_id": "2"},
    )
    service.archive.store.cleanup.side_effect = [
        service.archive.store.cleanup.return_value,
        OSError("private error"),
    ]
    with pytest.raises(QueryError):
        cleanup(service, ACTOR, 7)
    (event,) = audit_events(caplog)
    assert event["deleted_runs"] == 1 and event["deleted_bytes"] == 123
    assert event["status"] == "failed" and not event["counts_complete"]


def test_unauthorized_manual_request_does_not_cleanup_or_emit_accepted_audit(
    service, caplog
):
    service.catalog.actor_active.return_value = False
    with pytest.raises(QueryError, match="administrator_required"):
        cleanup(service, ACTOR, 7)
    service.archive.store.cleanup.assert_not_called()
    assert audit_events(caplog) == []
