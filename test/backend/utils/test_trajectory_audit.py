# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Audit facts stay bounded, safe and independent of cleanup behavior."""

import asyncio
import json
import logging

import pytest
from infrastructure.observability.trajectory_io import (
    TrajectoryConflict,
    TrajectoryCorrupt,
)
from ops.services.trajectory.primitives import QueryError


def audit_context(**kwargs):
    from infrastructure.observability.trajectory_audit import cleanup_audit

    return cleanup_audit(
        source="scheduled",
        tenant_id="tenant",
        before_days=30,
        cutoff_at="2026-10-11T00:00:00Z",
        **kwargs,
    )


def events(caplog):
    return [
        json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
        for record in caplog.records
        if record.getMessage().startswith("trajectory.cleanup ")
    ]


def test_audit_copies_only_allowlisted_facts_and_flattens_identifiers(caplog):
    caplog.set_level(logging.INFO)
    counts = {
        "scanned_runs": 1,
        "deleted_runs": 1,
        "deleted_bytes": 12,
        "cursor": "private-token",
        "payload": "private-content",
        "path": "/private/path",
    }
    with audit_context(counts=counts, conversation_id="1\nforged"):
        pass
    (event,) = events(caplog)
    assert event["source"] == "scheduled" and event["actor_id"] is None
    assert event["conversation_id"] == "1forged"
    assert event["deleted_runs"] == 1 and event["deleted_bytes"] == 12
    assert event["status"] == "success" and event["counts_complete"]
    assert all(
        private not in caplog.text
        for private in ("private-token", "private-content", "/private/path")
    )


@pytest.mark.parametrize(
    "error,code",
    [
        (OSError("private path"), "storage_unavailable"),
        (TrajectoryConflict("private path"), "storage_busy"),
        (TrajectoryCorrupt("private path"), "trajectory_corrupt"),
        (QueryError("cleanup_budget_exceeded", 503), "cleanup_budget_exceeded"),
        (QueryError("private-token", 503), "cleanup_failed"),
        (RuntimeError("private-token"), "cleanup_failed"),
        (asyncio.CancelledError("private-token"), "cleanup_interrupted"),
    ],
)
def test_audit_preserves_exception_identity_and_uses_safe_codes(caplog, error, code):
    with pytest.raises(type(error)) as raised, audit_context(counts={}):
        raise error
    assert raised.value is error
    (event,) = events(caplog)
    assert event["status"] == "failed" and event["error_code"] == code
    assert not event["counts_complete"]
    assert "private-token" not in caplog.text and "private path" not in caplog.text


def test_periodic_empty_scans_do_not_generate_audit_noise(caplog):
    caplog.set_level(logging.INFO)
    with audit_context(
        counts={"scanned_runs": 1000, "skipped_active": 1000}, emit_empty=False
    ):
        pass
    assert events(caplog) == []


def test_audit_failure_keeps_original_result_and_error(monkeypatch):
    from infrastructure.observability import trajectory_audit

    def fail(*args, **kwargs):
        raise OSError("controlled log handler failure")

    monkeypatch.setattr(trajectory_audit.logger, "log", fail)
    with audit_context(counts={"deleted_runs": 1}):
        result = "actual cleanup result"
    assert result == "actual cleanup result"
    error = RuntimeError("original cleanup failure")
    with pytest.raises(RuntimeError) as raised, audit_context(counts={}):
        raise error
    assert raised.value is error
