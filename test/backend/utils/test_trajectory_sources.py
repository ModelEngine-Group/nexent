# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted message provenance with isolated PG facts and actual manifest writes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from management.services.trajectory.archive import Archive
from management.services.trajectory.service import TrajectoryService


@pytest.fixture
def linked(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    store = TrajectoryFileStore(
        tmp_path,
        authorize=lambda _: None,
        clock=lambda: datetime(2026, 11, 1, tzinfo=UTC),
    )
    store.source_query = Mock(return_value=["10"])
    identity = CaptureIdentity("t", "u", "1", "7")
    row = {"tenant_id": "t", "user_id": "u", "conversation_id": "1", "agent_id": "7"}
    return SimpleNamespace(store=store, identity=identity, row=row)


def run(linked, source="10"):
    with linked.store.start(
        linked.identity,
        str(uuid4()),
        str(uuid4()),
        core_type="smolagents",
        source_message_id=source,
    ) as writer:
        writer.finish("completed")
    return linked.store.manifest(linked.identity)


def test_first_message_proves_capture_start(linked):
    meta = run(linked)
    assert meta["captured_from_start"] is True
    assert meta["has_uncaptured_history"] is False
    assert meta["source_coverage_verified"] is True
    assert meta["source_message_ids"] == ["10"]
    assert meta["runs"][0]["source_message_id"] == "10"
    linked.store.source_query.assert_called_once_with(linked.identity, "10")


def test_multiple_runs_of_same_message_keep_distinct_executions(linked):
    run(linked)
    linked.store.source_query.return_value = ["10", "20"]
    run(linked, "20")
    meta = run(linked, "20")
    assert len(meta["runs"]) == 3
    assert len({r["trajectory_id"] for r in meta["runs"]}) == 3
    assert meta["source_message_ids"] == ["10", "20"]
    assert meta["captured_from_start"] and not meta["has_uncaptured_history"]


def test_disabled_capture_gap_remains_after_later_runs(linked):
    run(linked)
    linked.store.source_query.return_value = ["10", "20", "30"]
    meta = run(linked, "30")
    assert meta["captured_from_start"] is True
    assert meta["source_history_gap"] and meta["has_uncaptured_history"]
    linked.store.source_query.return_value = ["10", "30", "40"]
    later = run(linked, "40")
    assert later["source_history_gap"] and later["has_uncaptured_history"]


def test_enabling_capture_after_first_message_does_not_claim_full_history(linked):
    linked.store.source_query.return_value = ["10", "20"]
    meta = run(linked, "20")
    assert not meta["captured_from_start"] and meta["has_uncaptured_history"]
    assert meta["source_history_gap"] is True
    assert meta["latest_source_captured"] is True


def test_missing_receipt_is_unlinked_and_does_not_query_source(linked):
    meta = run(linked, None)
    assert meta["has_unlinked_executions"] is True
    assert meta["runs"][0]["source_message_id"] is None
    assert not meta["captured_from_start"] and meta["has_uncaptured_history"]
    linked.store.source_query.assert_not_called()


def test_source_query_failure_does_not_change_business_or_archive_result(linked):
    linked.store.source_query.side_effect = RuntimeError("controlled PG failure")
    meta = run(linked)
    assert meta["runs"][0]["business_status"] == "completed"
    assert meta["runs"][0]["capture_state"] == "ready"
    assert not meta["source_coverage_verified"] and meta["has_uncaptured_history"]
    assert not meta["source_history_gap"]


@pytest.mark.parametrize("observed", [[], ["20"], [True], ["01"], [10], None])
def test_missing_or_invalid_source_proof_cannot_certify_first_message(linked, observed):
    linked.store.source_query.return_value = observed
    meta = run(linked)
    assert not meta["source_coverage_verified"] and not meta["captured_from_start"]
    assert meta["has_uncaptured_history"] is True


def test_query_detects_new_uncaptured_message_without_rewriting_manifest(linked):
    initial = run(linked)
    source_query = Mock(return_value=["10", "20"])
    archive = Archive(linked.store, source_query=source_query)
    current = archive.manifest(linked.row)
    assert current["latest_source_captured"] is False
    assert current["has_uncaptured_history"] and current["source_history_gap"]
    assert current["captured_from_start"] is True
    assert linked.store.manifest(linked.identity) == initial
    source_query.assert_called_once_with(linked.identity, None)


def test_query_source_failure_preserves_archive_and_explains_unknown(linked):
    run(linked)
    archive = Archive(
        linked.store, source_query=Mock(side_effect=RuntimeError("PG unavailable"))
    )
    current = archive.manifest(linked.row)
    assert current["runs"][0]["capture_state"] == "ready"
    assert current["source_coverage_verified"] is False
    assert current["latest_source_captured"] is None
    coverage = TrajectoryService.coverage(current)
    assert not coverage["complete"]
    assert "source_verification_unavailable" in coverage["reasons"]


def test_source_ids_survive_expiry_and_tombstone_pruning(linked):
    run(linked)
    linked.store.clock = lambda: datetime(2026, 12, 10, tzinfo=UTC)
    linked.store.cleanup(linked.identity)
    linked.store.clock = lambda: datetime(2026, 12, 18, tzinfo=UTC)
    linked.store.cleanup(linked.identity)
    assert linked.store.manifest(linked.identity)["runs"] == []
    linked.store.source_query.return_value = ["10", "20"]
    meta = run(linked, "20")
    assert meta["source_message_ids"] == ["10", "20"]
    assert meta["captured_from_start"] is True
    assert meta["has_uncaptured_history"] is False
    assert meta["had_expired_history"] is True


@pytest.mark.parametrize("manual", [False, True])
def test_proven_source_gap_survives_cleanup_and_retry(linked, manual):
    run(linked)
    linked.store.source_query.return_value = ["10", "20", "30"]
    run(linked, "30")
    linked.store.clock = lambda: datetime(2026, 12, 10, tzinfo=UTC)
    options = {"before_days": 1} if manual else {}
    linked.store.cleanup(linked.identity, **options)
    linked.store.clock = lambda: datetime(2026, 12, 18, tzinfo=UTC)
    linked.store.cleanup(linked.identity, **options)
    pruned = linked.store.manifest(linked.identity)
    assert pruned["runs"] == []
    assert pruned["source_message_ids"] == ["10", "30"]
    assert pruned["source_history_gap"] is True
    assert pruned["had_manual_cleanup"] is manual
    linked.store.source_query.return_value = ["10", "30", "40"]
    run(linked, "40")
    meta = run(linked, "40")
    assert meta["source_message_ids"] == ["10", "30", "40"]
    assert len(meta["runs"]) == 2
    assert meta["source_coverage_verified"] is True
    assert meta["source_history_gap"] and meta["has_uncaptured_history"]
    assert not TrajectoryService.coverage(meta)["complete"]


def test_legacy_or_unlinked_runs_cannot_be_promoted_to_complete(linked):
    run(linked, None)
    with linked.store._session(linked.identity) as folder:
        meta = folder.read_json("meta.json")
        for key in list(meta):
            if key.startswith("source_") or key == "has_unlinked_executions":
                del meta[key]
        linked.store._save_manifest(folder, meta)
    linked.store.source_query.return_value = ["10", "20"]
    meta = run(linked, "20")
    assert meta["has_unlinked_executions"] is True
    assert not meta["captured_from_start"] and meta["has_uncaptured_history"]


def test_registration_budget_stops_growing_without_dropping_execution(linked):
    run(linked)
    with linked.store._session(linked.identity) as folder:
        meta = folder.read_json("meta.json")
        meta["source_message_ids"] = [str(i) for i in range(1, 10_001)]
        linked.store._save_manifest(folder, meta)
    linked.store.source_query.return_value = [str(i) for i in range(1, 10_001)]
    meta = run(linked, "20000")
    assert meta["source_coverage_limited"] is True
    assert len(meta["source_message_ids"]) == 10_000
    assert meta["has_uncaptured_history"] is True
    assert meta["runs"][-1]["source_message_id"] == "20000"
    assert meta["runs"][-1]["business_status"] == "completed"


@pytest.mark.parametrize("source", [True, 10, "01", "0", "-1", "2147483648"])
def test_invalid_source_id_is_rejected_before_registration(linked, source):
    with pytest.raises(ValueError):
        run(linked, source)
    assert not list(linked.store.root.rglob("meta.json"))


def test_recheck_can_prove_registered_sources_after_temporary_outage(linked):
    linked.store.source_query.side_effect = RuntimeError("PG unavailable")
    run(linked)
    linked.store.source_query.side_effect = None
    linked.store.source_query.return_value = ["10", "20"]
    meta = run(linked, "20")
    assert meta["source_coverage_verified"] is True
    assert meta["captured_from_start"] is True
    assert meta["has_uncaptured_history"] is False
