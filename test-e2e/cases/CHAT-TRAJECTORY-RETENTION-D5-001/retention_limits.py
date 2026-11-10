# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real private-file workloads for the retention batch hard limits."""


def prove_scan_limit(files):
    runs = [files.add() for _ in range(1001)]
    original = {run.path: run.path.read_bytes() for run in runs}
    first = files.store.cleanup(files.owner, scan_limit=10000, delete_limit=10000)
    assert first["scanned_runs"] == 1000
    assert first["next_turn"] == 1000
    assert first["deleted_runs"] == first["deleted_bytes"] == 0
    assert first["failed_runs"] == first["pending_runs"] == 0
    last = files.store.cleanup(
        files.owner, after_turn=first["next_turn"], scan_limit=10000
    )
    assert last["scanned_runs"] == 1 and last["next_turn"] is None
    assert last["deleted_runs"] == last["deleted_bytes"] == 0
    assert {path: path.read_bytes() for path in original} == original
    meta = files.store.manifest(files.owner)
    assert meta["cleanup_version"] == 0
    assert all(run["cleanup_reason"] is None for run in meta["runs"])


def prove_delete_limit(files):
    runs = [files.add(age_days=30) for _ in range(101)]
    sizes = {run.path: run.path.stat().st_size for run in runs}
    first = files.store.cleanup(files.owner, delete_limit=10000)
    assert first["scanned_runs"] == 101 and first["deleted_runs"] == 100
    assert first["pending_runs"] == 1 and first["failed_runs"] == 0
    removed = {path for path in sizes if not path.exists()}
    assert len(removed) == 100 and runs[-1].path.exists()
    assert first["deleted_bytes"] == sum(sizes[path] for path in removed)
    pending = files.store.manifest(files.owner)["runs"]
    assert all(run["cleanup_reason"] == "retention" for run in pending)
    assert sum(run["file_deleted_at"] is None for run in pending) == 1
    last = files.reopen().cleanup(files.owner)
    assert (
        last["deleted_runs"] == 1 and last["pending_runs"] == last["failed_runs"] == 0
    )
    assert last["deleted_bytes"] == sizes[runs[-1].path]
    assert not any(run.path.exists() for run in runs)
    assert first["deleted_bytes"] + last["deleted_bytes"] == sum(sizes.values())
    assert files.reopen().cleanup(files.owner)["deleted_runs"] == 0
