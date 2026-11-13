# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Conversation projection keeps latest state independent of matching history."""

from uuid import uuid4

import pytest
import test_collection as collection_fixtures
from contracts.trajectory import RecordsQuery
from ops.services.trajectory.access import Actor
from ops.services.trajectory.collection import records
from ops.services.trajectory.primitives import QueryError

service = collection_fixtures.service

ACTOR = Actor("admin", "t", "ADMIN")


def test_conversation_view_aggregates_all_rounds_but_summarizes_matches(service):
    meta = service.archive.manifest.return_value
    meta["runs"][0]["business_status"] = "failed"
    response = records(service, ACTOR, {"id_query": "child-0"}, view="conversation")
    assert response["total"] == 1
    row = response["items"][0]
    assert row["status"] == "success"
    assert row["trajectory_id"] == meta["runs"][-1]["trajectory_id"]
    assert row["round_count"] == row["execution_count"] == 3
    assert row["matching_execution_count"] == 1
    assert row["duration_ms"] == 30 and row["usage"]["total"] == 15
    assert response["summary"]["duration"]["mean_ms"] == 0
    assert response["summary"]["conversation_duration"]["p50_ms"] == 0
    assert (
        records(service, ACTOR, {"status": "error"}, view="conversation")["total"] == 0
    )
    assert (
        records(
            service,
            ACTOR,
            {"status": "success", "id_query": "child-0"},
            view="conversation",
        )["total"]
        == 1
    )
    assert records(service, ACTOR, {})["total"] == 3


@pytest.mark.parametrize("state", ["expired", "not_captured", "unarchived", "corrupt"])
def test_latest_availability_cannot_be_replaced_by_historical_success(service, state):
    meta = service.archive.manifest.return_value
    latest = meta["runs"][-1]
    if state == "not_captured":
        meta.update(latest_source_captured=False, source_coverage_verified=True)
    elif state == "expired":
        latest.update(capture_state="expired", cleanup_reason="manual")
    elif state == "unarchived":
        latest.update(publication_no=None, capture_state="writing")
    else:
        latest["capture_state"] = "corrupt"
    result = records(service, ACTOR, {}, view="conversation")
    row = result["items"][0]
    assert row["availability"] == state and row["status"] is None
    assert row["coverage"]["complete"] is False
    assert (
        records(service, ACTOR, {"status": "success"}, view="conversation")["total"]
        == 0
    )
    if state in {"expired", "not_captured"}:
        assert (
            records(service, ACTOR, {"status": state}, view="conversation")["total"]
            == 1
        )
    if state == "expired":
        assert row["cleanup_reason"] == "manual"
    assert row["duration_ms"] is not None


def test_uncaptured_conversation_counts_without_invented_metrics(service):
    service.archive.manifest.return_value = None
    result = records(service, ACTOR, {"status": "not_captured"}, view="conversation")
    assert result["total"] == result["summary"]["conversation_count"] == 1
    row = result["items"][0]
    assert row["trajectory_id"] is None and row["round_count"] == 0
    assert row["duration_ms"] is None and row["usage"] is None
    assert result["summary"]["duration"]["sample_count"] == 0
    assert result["summary"]["conversation_duration"]["p50_ms"] is None
    service.load.assert_not_called()


def test_query_freezes_latest_execution_and_view_binding(service):
    first = records(service, ACTOR, {}, view="conversation")
    meta = service.archive.manifest.return_value
    last = meta["runs"][-1]
    meta["runs"].append(
        {
            **last,
            "trajectory_id": str(uuid4()),
            "turn_no": 4,
            "publication_no": 4,
            "business_status": "failed",
        }
    )
    meta["publication_no"] = 4
    old = records(service, ACTOR, {}, view="conversation", query_id=first["query_id"])
    assert (
        old["items"][0]["status"] == "success" and old["items"][0]["round_count"] == 3
    )
    assert (
        records(service, ACTOR, {}, view="conversation")["items"][0]["status"]
        == "error"
    )
    with pytest.raises(QueryError, match="invalid_reference"):
        records(service, ACTOR, {}, query_id=first["query_id"])
    meta["cleanup_version"] += 1
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(service, ACTOR, {}, view="conversation", query_id=first["query_id"])


def test_detail_uses_query_members_and_marks_matching_rounds(service):
    first = records(service, ACTOR, {"id_query": "child-1"}, view="conversation")
    meta = service.archive.manifest.return_value
    last = meta["runs"][-1]
    meta["runs"].append(
        {**last, "trajectory_id": str(uuid4()), "turn_no": 4, "publication_no": 4}
    )
    meta["publication_no"] = 4
    first_page = service.conversation(ACTOR, "1", query_id=first["query_id"], limit=1)
    assert first_page["executions"][0]["round_no"] == 1
    assert first_page["executions"][0]["matches_filters"] is False
    second = service.conversation(
        ACTOR, "1", cursor=first_page["next_cursor"], limit=10
    )
    assert [item["round_no"] for item in second["executions"]] == [2, 3]
    assert [item["matches_filters"] for item in second["executions"]] == [True, False]


def test_query_contract_restricts_four_states_to_conversation_view():
    assert RecordsQuery(view="conversation", status="expired").status == "expired"
    with pytest.raises(ValueError):
        RecordsQuery(status="expired")


def test_pruned_latest_summary_keeps_status_count_and_filter_proof(service):
    meta = service.archive.manifest.return_value
    latest = dict(meta["runs"][-1], capture_state="expired", cleanup_reason="manual")
    meta.update(latest_execution=latest, next_turn_no=4, had_expired_history=True)
    meta["runs"][:] = meta["runs"][:1]
    response = records(service, ACTOR, {"status": "expired"}, view="conversation")
    row = response["items"][0]
    assert row["round_count"] == 3 and row["trajectory_id"] is None
    assert row["availability"] == "expired" and row["cleanup_reason"] == "manual"
    assert row["status"] is None
    assert (
        records(service, ACTOR, {"status": "success"}, view="conversation")["total"]
        == 0
    )


def test_legacy_manifest_with_missing_latest_execution_stays_unknown(service):
    meta = service.archive.manifest.return_value
    meta.update(next_turn_no=5, had_expired_history=True)
    response = records(service, ACTOR, {}, view="conversation")
    assert response["items"][0]["availability"] == "unknown"
    assert response["items"][0]["status"] is None
    assert response["items"][0]["trajectory_id"] is None


def test_naturally_expired_latest_is_a_filterable_row_not_a_snapshot_error(service):
    from datetime import timedelta

    meta = service.archive.manifest.return_value
    meta["runs"][-1]["expires_at"] = (
        service.archive.store.clock() - timedelta(seconds=1)
    ).isoformat()
    response = records(service, ACTOR, {"status": "expired"}, view="conversation")
    assert response["total"] == 1
    assert response["items"][0]["availability"] == "expired"
    assert response["items"][0]["cleanup_reason"] == "retention"
