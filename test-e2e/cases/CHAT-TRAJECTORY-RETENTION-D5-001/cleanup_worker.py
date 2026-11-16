# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned subprocess fault boundaries for local retention risk assertions."""

import errno
import fcntl
import json
import os
import runpy
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
    parse_time,
)


def scheduled_cleanup(root, clock, fault):
    from ops.services.trajectory.lifecycle import create_maintenance_processor

    # Local dotenv files are outside this isolated environment-configuration proof.
    with patch("dotenv.load_dotenv", return_value=False):
        config = SimpleNamespace(**runpy.run_module("contracts.constants.environment"))
    assert (
        config.TRAJECTORY_ROOT_DIR == root
    )
    processor = create_maintenance_processor(config)
    assert processor is not None
    wall = [clock]
    processor._maintenance_store.clock = lambda: wall[0]
    # Tenant policies are the controlled PG boundary; the real scheduler and files remain active.
    processor._cleanup_policy_provider = dict
    processor.deleted_conversation_check = lambda _: False
    processor._maintenance_store.initialization_guard = None
    processor._maintenance_store.expire_callback = None
    before = sorted(str(path) for path in Path(root).rglob("*.otlp.jsonl"))
    for _ in range(100):
        processor._maintain()
        if processor._maintenance_iterator is None:
            break
    else:
        raise AssertionError("Owned startup maintenance did not finish")
    assert sorted(str(path) for path in Path(root).rglob("*.otlp.jsonl")) == before
    wall[0] = processor._next_cleanup_at
    scheduled_at = wall[0]
    unlink = os.unlink

    def slow_unlink(path, **kwargs):
        unlink(path, **kwargs)
        if fault == "scheduled_slow" and str(path).endswith(".otlp.jsonl"):
            time.sleep(2.05)

    os.unlink = slow_unlink
    started = time.monotonic()
    for _ in range(100):
        processor._maintain()
        if processor._maintenance_iterator is None:
            break
    else:
        raise AssertionError("Owned maintenance cycle did not finish")
    print(
        json.dumps(
            {
                "retention_days": config.TRAJECTORY_RETENTION_DAYS,
                "cleanup_enabled": config.TRAJECTORY_CLEANUP_ENABLED,
                "cleanup_interval_seconds": config.TRAJECTORY_CLEANUP_INTERVAL_SECONDS,
                "until_next_seconds": processor._next_maintenance - time.monotonic(),
                "elapsed_seconds": time.monotonic() - started,
                "scheduled_at": scheduled_at.isoformat(),
                "next_cleanup_at": processor._next_cleanup_at.isoformat(),
            }
        ),
        flush=True,
    )


def main():
    root, encoded_identity, run_id, now, fault = sys.argv[1:]
    identity = CaptureIdentity(**json.loads(encoded_identity))
    clock = parse_time(now)
    store = TrajectoryFileStore(
        root,
        authorize=lambda _: None,
        clock=lambda: clock,
    )
    meta = store.manifest(identity)
    target = (
        Path(root)
        / identity.tenant_id
        / identity.owner_user_id
        / meta["agent_id"]
        / identity.conversation_id
        / f"{run_id}.otlp.jsonl"
    )

    if fault in {"scheduled", "scheduled_slow"}:
        scheduled_cleanup(root, clock, fault)
        return

    if fault == "hold_cleanup":
        with (
            store._root() as directory,
            directory.lock(".cleanup.lock"),
        ):
            print("locked", flush=True)
            sys.stdin.read()
        return
    if fault == "hold_run":
        with target.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            print("locked", flush=True)
            sys.stdin.read()
        return

    save, unlink, sync = store._save_manifest, os.unlink, os.fsync
    parent_inode = target.parent.stat().st_ino

    def save_manifest(directory, value):
        run = next(item for item in value["runs"] if item["trajectory_id"] == run_id)
        if run["file_deleted_at"]:
            if fault == "after_delete_sync":
                os._exit(17)
            if fault == "metadata_failure":
                raise OSError(errno.EIO, "Injected deletion receipt failure")
        save(directory, value)
        if (
            fault == "after_mark"
            and run["cleanup_reason"]
            and not run["file_deleted_at"]
        ):
            os._exit(17)

    def unlink_file(path, **kwargs):
        selected = str(path) == target.name
        if selected and fault == "unlink_failure":
            raise PermissionError(errno.EACCES, "Injected unlink failure")
        unlink(path, **kwargs)
        if selected and fault == "after_unlink":
            os._exit(17)

    def sync_directory(fd):
        info = os.fstat(fd)
        if (
            fault == "directory_sync_failure"
            and stat.S_ISDIR(info.st_mode)
            and info.st_ino == parent_inode
            and not target.exists()
        ):
            raise OSError(errno.EIO, "Injected directory sync failure")
        sync(fd)

    store._save_manifest = save_manifest
    os.unlink, os.fsync = unlink_file, sync_directory
    result = store.cleanup(identity, now=clock)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
