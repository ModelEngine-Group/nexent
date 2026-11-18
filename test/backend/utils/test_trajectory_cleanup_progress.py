# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cleanup resumes from the earliest unfinished file, including lock and I/O failures."""

import os
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_io import Directory, TrajectoryConflict

from test.backend.utils import test_trajectory_file_store as fixtures

store = fixtures.store
identity = fixtures.identity


def populate(store, identity, count):
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    # Seed the large batch from a valid empty execution. Exercise real cleanup I/O
    # without repeating the unrelated capture/registration path a thousand times.
    with store._session(identity) as directory:
        meta = directory.read_json("meta.json")
        template = meta["runs"][0]
        for number in range(2, count + 1):
            run = {
                **template,
                "turn_no": number,
                "trajectory_id": str(uuid4()),
                "turn_id": str(uuid4()),
                "publication_no": number,
            }
            path = (
                store.root
                / "tenant-a/user-a/42/123"
                / f"{run['trajectory_id']}.otlp.jsonl"
            )
            path.touch()
            meta["runs"].append(run)
        meta.update(next_turn_no=count + 1, publication_no=count)
        store._save_manifest(directory, meta)


@pytest.mark.parametrize("count,delete_limit", [(100, 100), (101, 100), (1000, 1), (1001, 1)])
def test_delete_limit_continuation_never_skips_a_file(store, identity, count, delete_limit):
    populate(store, identity, count)
    # Exercise the default deletion boundary and the scan boundary independently.
    # Large manifests need only two expired files to prove deletion continuation;
    # rewriting them for 101 deletions repeats the same proof at quadratic cost.
    expired_count = min(count, delete_limit + 1)
    if count > expired_count:
        from infrastructure.observability.trajectory_store import timestamp

        with store._session(identity) as directory:
            meta = directory.read_json("meta.json")
            for run in meta["runs"][: count - expired_count]:
                run.update(
                    finished_at=timestamp(fixtures.NOW + timedelta(days=30)),
                    expires_at=timestamp(fixtures.NOW + timedelta(days=60)),
                )
            store._save_manifest(directory, meta)
    after, deleted = 0, 0
    for _ in range(count // 100 + 2):
        result = store.cleanup(
            identity, after_turn=after, now=fixtures.NOW + timedelta(days=30),
            delete_limit=delete_limit,
        )
        assert result["deleted_runs"] <= delete_limit and result["scanned_runs"] <= 1000
        if after == 0:
            assert result["scanned_runs"] == min(count, 1000)
            assert result["deleted_runs"] == delete_limit
        deleted += result["deleted_runs"]
        if result["next_turn"] is None:
            break
        assert result["next_turn"] >= after
        after = result["next_turn"]
    else:
        pytest.fail("Cleanup never completed")
    assert deleted == expired_count
    assert len(list(store.root.rglob("*.otlp.jsonl"))) == count - expired_count
    assert (
        store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))["deleted_runs"]
        == 0
    )


def test_cleanup_never_requests_a_blocking_session_lock(store, identity, monkeypatch):
    populate(store, identity, 1)
    original = Directory.lock

    def checked(directory, name, *, blocking=True):
        if name == ".lock":
            assert blocking is False
        return original(directory, name, blocking=blocking)

    monkeypatch.setattr(Directory, "lock", checked)
    result = store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))
    assert result["deleted_runs"] == 1 and result["next_turn"] is None


@pytest.mark.parametrize("busy_on", [1, 2, 3, 4])
def test_busy_session_preserves_progress_and_releases_global_lock(
    store, identity, monkeypatch, busy_on
):
    populate(store, identity, 1)
    original = Directory.lock

    session_locks = 0

    def busy(directory, name, *, blocking=True):
        nonlocal session_locks
        if name == ".lock":
            assert blocking is False
            session_locks += 1
            if session_locks == busy_on:
                raise TrajectoryConflict("Trajectory file is already locked")
        return original(directory, name, blocking=blocking)

    with monkeypatch.context() as context:
        context.setattr(Directory, "lock", busy)
        result = store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))
    assert result["pending_runs"] > 0 and result["next_turn"] == 0
    with store._root() as root, root.lock(".cleanup.lock", blocking=False):
        pass
    assert (
        result["deleted_runs"]
        + store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))["deleted_runs"]
        == 1
    )


@pytest.mark.parametrize("failure", ["locked", "unlink"])
def test_earlier_failed_file_is_retried_before_advancing(
    store, identity, monkeypatch, failure
):
    populate(store, identity, 3)
    first = store.manifest(identity)["runs"][0]
    path = (
        store.root / "tenant-a/user-a/42/123" / f"{first['trajectory_id']}.otlp.jsonl"
    )
    original = os.unlink

    def unlink(name, **kwargs):
        if str(name) == path.name:
            raise PermissionError("controlled deletion failure")
        return original(name, **kwargs)

    with monkeypatch.context() as context:
        if failure == "unlink":
            context.setattr(os, "unlink", unlink)
            result = store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))
        else:
            with Directory.root(path.parent) as directory, directory.lock(path.name):
                result = store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))
    assert result["deleted_runs"] == 2 and result["next_turn"] == 0
    assert result["pending_runs" if failure == "locked" else "failed_runs"] == 1
    assert (
        store.cleanup(
            identity,
            after_turn=result["next_turn"],
            now=fixtures.NOW + timedelta(days=30),
        )["deleted_runs"]
        == 1
    )
    assert not path.exists()


def test_budget_exhausted_before_work_returns_same_position(store, identity):
    populate(store, identity, 1)
    result = store.cleanup(
        identity, deadline=time.monotonic() - 1, now=fixtures.NOW + timedelta(days=30)
    )
    assert result["next_turn"] == 0 and result["deleted_runs"] == 0
    assert len(list(store.root.rglob("*.otlp.jsonl"))) == 1
