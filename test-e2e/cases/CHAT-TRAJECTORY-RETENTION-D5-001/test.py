# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""File-risk portion of RETENTION-D5; full HTTP/PG acceptance remains blocked."""

import hashlib
import importlib.util
import json
import os
import selectors
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryConflict,
    TrajectoryFileStore,
    parse_time,
    timestamp,
)

NOW = datetime(2035, 1, 1, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).with_name("cleanup_worker.py")
LIMITS_SPEC = importlib.util.spec_from_file_location(
    "trajectory_retention_limits", Path(__file__).with_name("retention_limits.py")
)
assert LIMITS_SPEC is not None and LIMITS_SPEC.loader is not None
LIMITS = importlib.util.module_from_spec(LIMITS_SPEC)
LIMITS_SPEC.loader.exec_module(LIMITS)
pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-RETENTION-D5-001"),
    pytest.mark.stage("D5"),
    pytest.mark.rel,
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(identity, run_id, start, finish):
    values = {
        "tenant.id": identity.tenant_id,
        "nexent.owner_user_id": identity.owner_user_id,
        "conversation.id": identity.conversation_id,
        "session.id": identity.conversation_id,
        "nexent.trace_id": identity.conversation_id,
        "nexent.trajectory_id": run_id,
        "input.value": "保留边界输入",
        "output.value": "整份正文随执行文件回收",
    }
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": uuid4().hex,
                                "spanId": uuid4().hex[:16],
                                "name": "agent.run",
                                "kind": 1,
                                "startTimeUnixNano": str(
                                    int(start.timestamp() * 1_000_000_000)
                                ),
                                "endTimeUnixNano": str(
                                    int(finish.timestamp() * 1_000_000_000)
                                ),
                                "status": {"code": 1},
                                "attributes": [
                                    {"key": key, "value": {"stringValue": value}}
                                    for key, value in values.items()
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.fixture
def files(tmp_path):
    private = tmp_path / "retention-owned"
    root = private / "traces"
    TrajectoryFileStore.provision(root)
    owner = CaptureIdentity("tenant-a", "owner-a", "123", "42")
    other = CaptureIdentity("tenant-b", "owner-b", "456", "42")
    clock = [NOW]

    def open_store():
        def authorize(identity):
            assert (
                identity.tenant_id,
                identity.owner_user_id,
                identity.conversation_id,
            ) in {
                ("tenant-a", "owner-a", "123"),
                ("tenant-b", "owner-b", "456"),
            }

        return TrajectoryFileStore(
            root, authorize=authorize, clock=lambda: clock[0]
        )

    store = open_store()

    def add(identity=owner, *, age_days=0, active=False):
        run_id = str(uuid4())
        finish = NOW - timedelta(days=age_days)
        start = finish - timedelta(seconds=1)
        writer = store.start(
            identity, run_id, str(uuid4()), core_type="smolagents", started_at=start
        )
        try:
            writer.append(
                [payload(identity, run_id, start, finish)],
                batch_id=str(uuid4()),
                expected_offset=0,
            )
            if not active:
                writer.finish("completed", finished_at=finish)
        except BaseException:
            writer.close()
            raise
        finally:
            if not active:
                writer.close()
        meta = store.manifest(identity)
        path = (
            root
            / identity.tenant_id
            / identity.owner_user_id
            / meta["storage_agent_id"]
        )
        return SimpleNamespace(
            id=run_id,
            path=path / identity.conversation_id / f"{run_id}.otlp.jsonl",
            writer=writer,
        )

    canary = add(other)
    resources = [
        canary.path,
        private / "protected-chat.txt",
        private / "protected-attachment.bin",
    ]
    resources[1].write_text(
        "Protected resource stand-in; actual PG is outside this fixture."
    )
    resources[2].write_bytes(b"protected-attachment")
    hashes = {path: digest(path) for path in resources}
    state = SimpleNamespace(
        root=root,
        owner=owner,
        other=other,
        clock=clock,
        store=store,
        add=add,
        reopen=open_store,
    )
    try:
        yield state
    finally:
        try:
            assert {path: digest(path) for path in hashes} == hashes
        finally:
            shutil.rmtree(private)
        assert not private.exists()


def state(files, run):
    return next(
        item
        for item in files.store.manifest(files.owner)["runs"]
        if item["trajectory_id"] == run.id
    )


def command(files, run, fault):
    return [
        sys.executable,
        str(WORKER),
        str(files.root),
        json.dumps(asdict(files.owner)),
        run.id,
        timestamp(files.clock[0]),
        fault,
    ]


def environment():
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(REPO / "backend"), str(REPO / "sdk"))),
    }


def worker(files, run, fault, *, config=None):
    child_environment = environment()
    if config is not None:
        child_environment = {
            key: value
            for key, value in child_environment.items()
            if not key.startswith("TRAJECTORY_")
        }
        child_environment.update(
            {
                "ENABLE_TELEMETRY": "true",
                "MONITORING_PROVIDER": "local_file",
                "TRAJECTORY_READ_ENABLED": "true",
                "TRAJECTORY_ROOT_DIR": str(files.root),

                **config,
            }
        )
    return subprocess.run(
        command(files, run, fault),
        cwd=REPO,
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@contextmanager
def locked(files, run, fault):
    process = subprocess.Popen(
        command(files, run, fault),
        cwd=REPO,
        env=environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10), "Owned lock worker did not become ready"
            assert process.stdout.readline().strip() == "locked"
        assert process.poll() is None
        yield process
    finally:
        try:
            if process.poll() is None:
                process.communicate(input="", timeout=5)
            else:
                process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
        assert process.poll() is not None


@pytest.mark.parametrize("fault", ["after_mark", "after_unlink", "after_delete_sync"])
def test_retention_process_death_does_not_resurrect_and_cold_retry_finishes(
    files, fault
):
    expired = files.add(age_days=30)
    fresh = files.add()
    fresh_hash = digest(fresh.path)
    size = expired.path.stat().st_size
    completed = worker(files, expired, fault)
    assert completed.returncode == 17, completed.stderr
    files.store = files.reopen()
    marked = state(files, expired)
    assert (
        marked["capture_state"] == "expired" and marked["cleanup_reason"] == "retention"
    )
    assert marked["file_deleted_at"] is None
    assert expired.path.exists() == (fault == "after_mark")
    version = files.store.manifest(files.owner)["cleanup_version"]
    with pytest.raises(TrajectoryConflict):
        files.store.recover(files.owner, expired.id)
    outcome = files.store.cleanup(files.owner)
    assert outcome["deleted_runs"] == (1 if fault == "after_mark" else 0)
    assert outcome["deleted_bytes"] == (size if fault == "after_mark" else 0)
    assert outcome["failed_runs"] == outcome["pending_runs"] == 0
    assert state(files, expired)["file_deleted_at"] is not None
    assert not expired.path.exists()
    assert files.store.manifest(files.owner)["cleanup_version"] == version
    assert files.store.cleanup(files.owner)["deleted_runs"] == 0
    assert digest(fresh.path) == fresh_hash


@pytest.mark.parametrize(
    "fault", ["unlink_failure", "directory_sync_failure", "metadata_failure"]
)
def test_retention_failed_deletion_is_not_counted_and_pending_marker_survives_seven_days(
    files, fault
):
    expired = files.add(age_days=30)
    completed = worker(files, expired, fault)
    assert completed.returncode == 0, completed.stderr
    outcome = json.loads(completed.stdout)
    assert outcome["failed_runs"] == 1
    assert outcome["deleted_runs"] == outcome["deleted_bytes"] == 0
    files.store = files.reopen()
    assert state(files, expired)["file_deleted_at"] is None
    assert expired.path.exists() == (fault == "unlink_failure")
    files.clock[0] += timedelta(days=8)
    pending = files.store.cleanup(files.owner, delete_limit=0)
    assert pending["pending_runs"] == 1 and pending["deleted_runs"] == 0
    assert state(files, expired)["file_deleted_at"] is None
    outcome = files.store.cleanup(files.owner)
    assert outcome["deleted_runs"] == (1 if fault == "unlink_failure" else 0)
    assert outcome["failed_runs"] == outcome["pending_runs"] == 0
    assert state(files, expired)["file_deleted_at"] == timestamp(files.clock[0])
    assert not expired.path.exists()
    files.clock[0] += timedelta(days=7, microseconds=-1)
    files.store.cleanup(files.owner)
    assert state(files, expired)["file_deleted_at"] is not None
    files.clock[0] += timedelta(microseconds=1)
    files.store.cleanup(files.owner)
    meta = files.store.manifest(files.owner)
    assert meta["runs"] == [] and meta["expired_execution_count"] == 1
    assert meta["had_expired_history"] and meta["cleanup_version"] == 1


def test_retention_run_lock_blocks_deletion_across_processes_without_losing_marker(
    files,
):
    expired = files.add(age_days=30)
    original = digest(expired.path)
    with locked(files, expired, "hold_run"):
        outcome = files.store.cleanup(files.owner)
        assert outcome["pending_runs"] == 1 and outcome["failed_runs"] == 0
        assert outcome["deleted_runs"] == outcome["deleted_bytes"] == 0
        assert digest(expired.path) == original
        assert state(files, expired)["cleanup_reason"] == "retention"
        assert state(files, expired)["file_deleted_at"] is None
    assert files.reopen().cleanup(files.owner)["deleted_runs"] == 1
    assert not expired.path.exists()


def test_retention_cleanup_batch_lock_is_exclusive_across_processes(files):
    expired = files.add(age_days=30)
    original = digest(expired.path)
    with locked(files, expired, "hold_cleanup"):
        with pytest.raises(TrajectoryConflict):
            files.store.cleanup(files.owner)
        assert state(files, expired)["cleanup_reason"] is None
        assert digest(expired.path) == original
    assert files.reopen().cleanup(files.owner)["deleted_runs"] == 1


def test_retention_active_runs_and_fixed_storage_agent_survive_old_run_reclamation(
    files,
):
    old = files.add(age_days=30)
    switched = CaptureIdentity("tenant-a", "owner-a", "123", "43")
    fresh = files.add(switched)
    active = files.add(switched, age_days=100, active=True)
    original = {run.path: digest(run.path) for run in (fresh, active)}
    try:
        assert old.path.parent == fresh.path.parent == active.path.parent
        assert fresh.path.parent.parent.name == "42"
        outcome = files.store.cleanup(switched)
        assert outcome["deleted_runs"] == 1 and outcome["skipped_active"] == 1
        assert not old.path.exists()
        assert {path: digest(path) for path in original} == original
        files.clock[0] += timedelta(days=7)
        files.store.cleanup(switched)
        meta = files.store.manifest(switched)
        assert {item["trajectory_id"] for item in meta["runs"]} == {fresh.id, active.id}
        assert meta["storage_agent_id"] == "42" and meta["expired_execution_count"] == 1
        assert meta["had_expired_history"]
        files.add(switched)
        assert {path: digest(path) for path in original} == original
    finally:
        active.writer.close()


def test_retention_terminal_boundary_and_shortening_never_extend_existing_expiry(files):
    run = files.add()
    assert parse_time(state(files, run)["expires_at"]) == NOW + timedelta(days=30)
    files.store.retention_days = 7
    files.clock[0] += timedelta(days=2)
    assert files.store.cleanup(files.owner)["deleted_runs"] == 0
    assert parse_time(state(files, run)["expires_at"]) == NOW + timedelta(days=7)
    files.store.retention_days = 30
    files.clock[0] = NOW + timedelta(days=7, microseconds=-1)
    assert files.store.cleanup(files.owner)["deleted_runs"] == 0
    files.clock[0] += timedelta(microseconds=1)
    assert files.store.cleanup(files.owner)["deleted_runs"] == 1
    assert not run.path.exists()


def test_retention_fixed_manual_cutoff_keeps_newer_run_and_default_policy(files):
    first = files.add(age_days=8)
    later = files.add(age_days=6)
    cutoff = NOW - timedelta(days=7)
    outcome = files.store.cleanup(
        files.owner, before_days=7, cutoff_at=cutoff, delete_limit=1
    )
    assert outcome["deleted_runs"] == 1 and not first.path.exists()
    assert later.path.exists() and files.store.retention_days == 30
    files.clock[0] += timedelta(days=2)
    again = files.reopen().cleanup(files.owner, before_days=7, cutoff_at=cutoff)
    assert again["deleted_runs"] == 0 and later.path.exists()
    meta = files.store.manifest(files.owner)
    assert meta["had_manual_cleanup"] and meta["cleanup_version"] == 1
    assert state(files, first)["cleanup_reason"] == "manual"


@pytest.mark.parametrize(
    "overrides,age,removed,days,interval",
    [
        ({}, 30, True, 30, 3600),
        ({"TRAJECTORY_CLEANUP_ENABLED": "false"}, 30, False, 30, 3600),
        (
            {
                "TRAJECTORY_RETENTION_DAYS": "7",
                "TRAJECTORY_CLEANUP_INTERVAL_SECONDS": "60",
            },
            8,
            True,
            7,
            60,
        ),
    ],
)
def test_retention_independent_process_loads_cleanup_defaults_and_explicit_configuration(
    files,
    overrides,
    age,
    removed,
    days,
    interval,
):
    run = files.add(age_days=age)
    fresh = files.add()
    fresh_hash = digest(fresh.path)
    completed = worker(files, run, "scheduled", config=overrides)
    assert completed.returncode == 0, completed.stderr
    reported = json.loads(completed.stdout)
    assert reported["retention_days"] == days
    assert reported["cleanup_interval_seconds"] == interval
    assert reported["cleanup_enabled"] == (
        overrides.get("TRAJECTORY_CLEANUP_ENABLED") != "false"
    )
    assert interval - 10 < reported["until_next_seconds"] <= interval
    assert run.path.exists() != removed
    assert (state(files, run)["cleanup_reason"] == "retention") == removed
    assert digest(fresh.path) == fresh_hash


def test_retention_scheduled_slow_delete_yields_using_real_monotonic_deadline(files):
    runs = [files.add(age_days=30) for _ in range(3)]
    fresh = files.add()
    fresh_hash = digest(fresh.path)
    completed = worker(files, runs[0], "scheduled_slow", config={})
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["elapsed_seconds"] >= 2
    assert sum(run.path.exists() for run in runs) == 2
    assert all(state(files, run)["cleanup_reason"] == "retention" for run in runs)
    assert sum(state(files, run)["file_deleted_at"] is None for run in runs) == 2
    assert digest(fresh.path) == fresh_hash
    assert files.reopen().cleanup(files.owner)["deleted_runs"] == 2


def test_retention_hard_scan_limit_preserves_all_fresh_files(files):
    LIMITS.prove_scan_limit(files)


def test_retention_hard_delete_limit_reports_only_confirmed_files_and_bytes(files):
    LIMITS.prove_delete_limit(files)
