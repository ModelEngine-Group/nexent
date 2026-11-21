# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cancelled executions retain a readable identity and a distinct list status."""

import pytest
from contracts.trajectory import RecordsQuery
from ops.db.trajectory.queries import ExecutionCatalog
from ops.services.trajectory.collection import _run_matches
from ops.services.trajectory.projection import execution_values


@pytest.fixture
def run():
    return {
        "trajectory_id": "00000000-0000-0000-0000-000000000001",
        "turn_no": 1,
        "root_agent_id": "7",
        "root_agent_version_no": 1,
        "capture_state": "ready",
        "business_status": "cancelled",
        "started_at": "2026-11-17T00:00:00Z",
        "finished_at": "2026-11-17T00:00:01Z",
        "publication_no": 1,
    }


@pytest.mark.parametrize(
    "business,expected",
    [
        ("completed", "success"),
        ("failed", "error"),
        ("cancelled", "cancelled"),
        ("interrupted", "error"),
    ],
)
def test_projection_and_file_filter_keep_cancelled_distinct(run, business, expected):
    run["business_status"] = business
    assert execution_values("123", run)["status"] == expected
    assert _run_matches(run, {"status": expected})
    for other in {"success", "error", "cancelled"} - {expected}:
        assert not _run_matches(run, {"status": other})


@pytest.mark.parametrize("state", ["expired", "corrupt", "partial"])
def test_availability_takes_precedence_over_cancellation(run, state):
    run["capture_state"] = state
    assert execution_values("123", run)["status"] == state


@pytest.mark.parametrize("view", ["execution", "conversation"])
def test_cancelled_pg_row_remains_readable_with_metrics(run, view):
    row = {
        **execution_values("123", run),
        "status": "cancelled",
        "tenant_id": "t",
        "user_id": "u",
        "user_name": "User",
        "conversation_title": "Stopped run",
        "runs": [],
        "duration_ms": 1000,
        "execution_count": 1,
        "matching_execution_count": 1,
        "cumulative_duration_ms": 1000,
    }
    for key, value in [("input", 3), ("output", 2), ("total", 5)]:
        row[key + "_tokens"] = row["cumulative_" + key + "_tokens"] = value
    result = ExecutionCatalog._dto(row, view)
    assert result["status"] == "cancelled"
    assert result["availability"] == "available"
    assert result["trajectory_id"] == run["trajectory_id"]
    assert result["usage"] == {"input": 3, "output": 2, "total": 5, "complete": True}
    assert result["duration_ms"] == 1000


@pytest.mark.parametrize("view", ["execution", "conversation"])
def test_cancelled_filter_is_accepted_for_both_views(view):
    assert RecordsQuery(view=view, status="cancelled").filters == {
        "status": "cancelled",
        "id_query": "",
    }
    with pytest.raises(ValueError):
        RecordsQuery(view=view, status="cancel")
