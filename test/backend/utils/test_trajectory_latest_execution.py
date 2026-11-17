# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Latest execution facts survive cleanup without reverting to earlier runs."""

from datetime import timedelta
from uuid import uuid4

from . import test_trajectory_file_store as file_fixtures

NOW = file_fixtures.NOW
identity, request, store = (
    file_fixtures.identity,
    file_fixtures.request,
    file_fixtures.store,
)


def test_latest_summary_retains_version_and_cleanup_after_tombstone_pruning(
    store, identity
):
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents"
    ) as writer:
        payload = request(identity, writer.trajectory_id)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span["attributes"].extend(
            [
                {"key": "nexent.trajectory.root", "value": {"boolValue": True}},
                {"key": "agent.version_no", "value": {"intValue": "0"}},
                {"key": "agent.name", "value": {"stringValue": "Historical agent"}},
            ]
        )
        writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("failed")
        run_id = writer.trajectory_id
    meta = store.manifest(identity)
    assert meta["latest_execution"]["trajectory_id"] == run_id
    assert meta["latest_execution"]["root_agent_version_no"] == 0
    assert meta["latest_execution"]["root_agent_name"] == "Historical agent"
    store.clock = lambda: NOW + timedelta(days=31)
    store.cleanup(identity)
    store.clock = lambda: NOW + timedelta(days=40)
    store.cleanup(identity)
    meta = store.manifest(identity)
    assert meta["runs"] == []
    assert meta["latest_execution"]["cleanup_reason"] == "retention"
    assert meta["latest_execution"]["capture_state"] == "expired"
    assert meta["next_turn_no"] == 2


def test_finishing_an_older_concurrent_run_does_not_replace_latest(store, identity):
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents"
    ) as older:
        with store.start(
            identity, str(uuid4()), str(uuid4()), core_type="smolagents"
        ) as latest:
            latest.finish("failed")
        older.finish("completed")
    meta = store.manifest(identity)
    assert meta["latest_execution"]["trajectory_id"] == latest.trajectory_id
    assert meta["latest_execution"]["business_status"] == "failed"


def test_child_agent_cannot_replace_the_root_version_snapshot(store, identity):
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents"
    ) as writer:
        payload = request(identity, writer.trajectory_id)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span["attributes"].extend(
            [
                {"key": "agent.version_no", "value": {"intValue": "99"}},
                {"key": "agent.name", "value": {"stringValue": "Child agent"}},
            ]
        )
        writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("completed")
    latest = store.manifest(identity)["latest_execution"]
    assert latest["root_agent_version_no"] is None
    assert latest["root_agent_name"] is None
