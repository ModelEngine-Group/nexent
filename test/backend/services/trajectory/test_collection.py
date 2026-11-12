# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Whole-result aggregation and membership snapshots with isolated collaborators."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from management.services.trajectory.access import Actor, authorize
from management.services.trajectory.archive import Archive
from management.services.trajectory.collection import records
from management.services.trajectory.primitives import QueryError, ReferenceStore
from management.services.trajectory.service import TrajectoryService


@pytest.fixture
def service():
    now = datetime.now(UTC)
    row = {
        "tenant_id": "t",
        "user_id": "u",
        "user_name": "Owner",
        "conversation_id": "1",
        "conversation_title": "Title",
        "agent_id": "7",
    }
    runs = [
        {
            "trajectory_id": str(uuid4()),
            "publication_no": i + 1,
            "turn_no": i + 1,
            "root_agent_id": "7",
            "business_status": "completed",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "confirmed_sha256": str(i),
            "capture_state": "ready",
        }
        for i in range(3)
    ]
    meta = {"runs": runs, "publication_no": 3, "cleanup_version": 0}
    catalog = Mock()
    catalog.tenants.return_value = ["t"]
    catalog.actor_active.return_value = True
    catalog.candidates.return_value = [row]
    catalog.resolve.return_value = row
    catalog.names.return_value = {"t": "Tenant"}
    catalog.agent_names.return_value = {}
    catalog.message_upper.return_value = 0
    instance = TrajectoryService(Mock(), catalog, ReferenceStore())
    instance.archive = SimpleNamespace(
        manifest=Mock(return_value=meta),
        available=lambda run: Archive.available(instance.archive, run),
        store=SimpleNamespace(clock=lambda: now),
    )

    def load(actor, row, run_id, budget):
        run = next(r for r in runs if r["trajectory_id"] == run_id)
        number = int(run["confirmed_sha256"])
        return (
            [
                {
                    "id": "root",
                    "display_trace_id": "1",
                    "model": None,
                    "name": "Agent",
                    "duration_ms": number * 10,
                    "kind": "agent",
                    "usage": {"total": number * 5},
                },
                {
                    "id": "child-" + str(number),
                    "display_trace_id": "child-" + str(number),
                    "model": "model",
                    "kind": "model",
                    "ttft_ms": number * 2,
                },
            ],
            "root",
            {"complete": True},
        )

    instance.load = Mock(side_effect=load)
    return instance


def test_aggregate_is_not_page_dependent_and_query_members_are_fixed(service):
    actor = Actor("admin", "t", "ADMIN")
    first = records(
        service, actor, {}, page_size=1, sort_by="duration_ms", sort_order="asc"
    )
    assert first["total"] == 3 and len(first["items"]) == 1
    assert first["summary"]["conversation_count"] == 1
    assert first["summary"]["duration"]["mean_ms"] == 10
    assert first["summary"]["duration"]["p90_ms"] == 18
    assert first["summary"]["ttft"]["p50_ms"] == 2
    meta = service.archive.manifest.return_value
    meta["runs"].append(
        {**meta["runs"][0], "trajectory_id": str(uuid4()), "publication_no": 4}
    )
    meta["publication_no"] = 4
    second = records(
        service, actor, {}, query_id=first["query_id"], page=2, page_size=1
    )
    assert second["total"] == 3
    assert second["summary"]["duration"] == first["summary"]["duration"]
    fresh = records(service, actor, {})
    assert fresh["total"] == 4
    meta["cleanup_version"] += 1
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(service, actor, {}, query_id=first["query_id"])


def test_model_and_child_id_filtering_empty_values(service):
    actor = Actor("admin", "t", "ADMIN")
    found = records(service, actor, {"id_query": " CHILD-2 ", "model": "model"})
    assert found["total"] == 1 and found["summary"]["duration"]["mean_ms"] == 20
    empty = records(service, actor, {"model": "missing"})
    assert empty["total"] == 0
    assert empty["summary"]["duration"]["p50_ms"] is None
    assert empty["summary"]["ttft"]["sample_count"] == 0


def test_list_projects_historical_root_version_not_child_or_current_agent(service):
    service.catalog.agent_names.return_value = {("t", "7"): "Current display name"}
    original = service.load.side_effect

    def load(*args):
        nodes, root, coverage = original(*args)
        nodes[0].update(agent_version_no=3, agent_version_name="Historical release")
        nodes[1].update(agent_version_no=99, agent_version_name="not root")
        return nodes, root, coverage

    service.load.side_effect = load
    result = records(service, Actor("admin", "t", "ADMIN"), {})
    assert all(row["root_agent_version_no"] == 3 for row in result["items"])
    assert all(
        row["root_agent_version_name"] == "Historical release"
        for row in result["items"]
    )
    assert all(
        row["root_agent_name"] == "Current display name" for row in result["items"]
    )
    service.catalog.agent_names.assert_called_once_with(["t"], {"7"})


@pytest.mark.parametrize(
    "names", [{}, {("t", "7"): "7"}, {("other", "7"): "Other tenant agent"}]
)
def test_missing_agent_display_name_never_uses_id_or_another_tenant(service, names):
    service.catalog.agent_names.return_value = names
    result = records(service, Actor("admin", "t", "ADMIN"), {})
    assert result["items"]
    assert all(row["root_agent_name"] is None for row in result["items"])


def test_old_archive_root_version_stays_unknown(service):
    result = records(service, Actor("admin", "t", "ADMIN"), {})
    assert all(row["root_agent_version_no"] is None for row in result["items"])
    assert all(row["root_agent_version_name"] is None for row in result["items"])


@pytest.mark.parametrize("role", ["USER", "DEV", "SPEED", ""])
def test_roles_cannot_be_promoted_by_filters(service, role):
    with pytest.raises(QueryError) as exc:
        records(service, Actor("admin", "t", role), {"tenant_id": "t"})
    assert exc.value.status == 403
    service.catalog.candidates.assert_not_called()


def test_foreign_scope_and_revoked_actor_are_rejected(service):
    with pytest.raises(QueryError) as exc:
        authorize(service.catalog, Actor("admin", "t", "ADMIN"), "other")
    assert exc.value.status == 404
    service.catalog.actor_active.return_value = False
    with pytest.raises(QueryError) as exc:
        records(service, Actor("admin", "t", "SU"), {})
    assert exc.value.status == 403


def test_expired_query_and_budget_never_return_partial_totals(service):
    actor = Actor("admin", "t", "ADMIN")
    data = records(service, actor, {})
    service.queries.entries.clear()
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(service, actor, {}, query_id=data["query_id"])
    service.seconds = -1
    with pytest.raises(QueryError) as exc:
        records(service, actor, {})
    assert exc.value.status == 503


@pytest.mark.parametrize(
    "filters",
    [
        {"agent_id": "8"},
        {"status": "error"},
        {"started_from": "2099-01-01T00:00:00Z"},
        {"started_to": "2000-01-01T00:00:00Z"},
    ],
)
def test_manifest_filters_avoid_body_io_without_changing_empty_totals(service, filters):
    response = records(service, Actor("admin", "t", "ADMIN"), filters)
    assert (
        response["total"] == 0 and response["summary"]["duration"]["sample_count"] == 0
    )
    service.load.assert_not_called()


def test_facet_rechecks_owner_after_reading_candidate_names(service):
    from management.services.trajectory.collection import facets

    service.catalog.agent_names.return_value = {("t", "7"): "Agent"}
    service.catalog.resolve.side_effect = QueryError("trajectory_not_found", 404)
    with pytest.raises(QueryError, match="trajectory_not_found"):
        facets(service, Actor("admin", "t", "ADMIN"), {}, "agents")


@pytest.mark.parametrize(
    "state, expected, active",
    [
        ("missing", "not_captured", 0),
        ("empty", "not_captured", 0),
        ("running", "unarchived", 1),
        ("pending_terminal", "unarchived", 1),
        ("expired", "expired", 0),
        ("expired_and_running", "unarchived", 1),
        ("ready", "available", 0),
        ("ready_and_running", "available", 1),
    ],
)
def test_conversation_and_placeholder_availability(service, state, expected, active):
    actor = Actor("admin", "t", "ADMIN")
    meta = service.archive.manifest.return_value
    ready = meta["runs"][0]
    pending = {
        **ready,
        "trajectory_id": str(uuid4()),
        "publication_no": None,
        "capture_state": "writing",
        "business_status": "running",
        "finished_at": None,
    }
    expired = {**ready, "cleanup_reason": "retention", "capture_state": "expired"}
    meta["runs"][:] = {
        "missing": [],
        "empty": [],
        "running": [pending],
        "pending_terminal": [{**pending, "business_status": "completed"}],
        "expired": [expired],
        "expired_and_running": [expired, pending],
        "ready": [ready],
        "ready_and_running": [ready, pending],
    }[state]
    meta["captured_from_start"] = True
    if state == "missing":
        service.archive.manifest.return_value = None

    detail = service.conversation(actor, "1")
    assert detail["availability"] == expected
    assert detail["active_execution_count"] == active
    assert all(
        item["trajectory_id"] != pending["trajectory_id"]
        for item in detail["executions"]
    )
    if active:
        assert detail["coverage"]["complete"] is False
        assert "unarchived" in detail["coverage"]["reasons"]

    response = records(service, actor, {})
    assert response["total"] == 1
    item = response["items"][0]
    assert item["availability"] == expected
    if expected != "available":
        assert item["trajectory_id"] is None
        assert item["business_status"] is None
        assert item["duration_ms"] is None and item["usage"] is None
        assert item["coverage"]["complete"] is False
        assert response["summary"]["conversation_count"] == 1
        assert response["summary"]["duration"]["sample_count"] == 0
        assert response["summary"]["ttft"]["sample_count"] == 0
        service.load.assert_not_called()


def test_unarchived_placeholder_survives_publication_until_query_refresh(service):
    actor = Actor("admin", "t", "ADMIN")
    meta = service.archive.manifest.return_value
    meta["runs"][:] = meta["runs"][:1]
    run = meta["runs"][0]
    run["publication_no"] = None
    run["capture_state"] = "writing"
    meta["publication_no"] = 0
    first = records(service, actor, {})
    assert first["items"][0]["availability"] == "unarchived"
    service.load.assert_not_called()

    run["publication_no"] = 1
    run["capture_state"] = "ready"
    meta["publication_no"] = 1
    old = records(service, actor, {}, query_id=first["query_id"])
    assert old["items"][0]["availability"] == "unarchived"
    assert old["items"][0]["trajectory_id"] is None
    assert old["summary"]["duration"]["sample_count"] == 0
    service.load.assert_not_called()
    refreshed = records(service, actor, {})
    assert refreshed["items"][0]["availability"] == "available"
    assert refreshed["items"][0]["trajectory_id"] == run["trajectory_id"]
    assert refreshed["summary"]["duration"]["sample_count"] == 1
    service.load.assert_called_once()


@pytest.mark.parametrize(
    "filters",
    [
        {"model": "model"},
        {"status": "success"},
        {"started_from": "2000-01-01T00:00:00Z"},
        {"started_to": "2099-01-01T00:00:00Z"},
        {"id_query": "child-0"},
    ],
)
def test_unarchived_placeholder_does_not_fabricate_filter_matches(service, filters):
    meta = service.archive.manifest.return_value
    for run in meta["runs"]:
        run["publication_no"] = None
        run["capture_state"] = "writing"
    meta["publication_no"] = 0
    result = records(service, Actor("admin", "t", "ADMIN"), filters)
    assert result["total"] == 0
    assert result["summary"]["conversation_count"] == 0
    service.load.assert_not_called()
