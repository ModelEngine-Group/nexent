# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable storage rejects invalid state and reconciles only safe orphan files."""

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.trace.trajectory_io import (
    Directory,
    TrajectoryConflict,
    TrajectoryCorrupt,
)
from infrastructure.trace.trajectory_store import (
    TrajectoryFileStore,
    component,
    parse_time,
    timestamp,
    uuid_string,
)

from test.backend.utils import test_trajectory_file_store as fixtures

store = fixtures.store
identity = fixtures.identity


@pytest.mark.parametrize(
    "function,value",
    [
        (timestamp, datetime(2026, 1, 1)),
        (parse_time, "2026-01-01"),
        (uuid_string, 123),
        (uuid_string, "00000000-0000-0000-0000-00000000000A"),
        (component, ""),
        (component, "a\\b"),
        (component, ".hidden"),
        (component, "中" * 100),
    ],
)
def test_invalid_identity_encoding_and_naive_dates_are_rejected(function, value):
    with pytest.raises((ValueError, TrajectoryCorrupt)):
        function(value)


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"authorize": None}, TypeError),
        ({"retention_days": True}, ValueError),
        ({"storage_mode": "remote"}, ValueError),
    ],
)
def test_invalid_store_configuration_does_not_create_root(tmp_path, kwargs, error):
    root = tmp_path / "traces"
    with pytest.raises(error):
        TrajectoryFileStore(root, **{"authorize": lambda _: None, **kwargs})
    assert not root.exists()


def test_notification_failure_does_not_change_durable_publication(store, identity):
    store.on_publish = Mock(side_effect=RuntimeError("worker unavailable"))
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    assert store.manifest(identity)["publication_no"] == 1
    store.on_publish.assert_called_once_with(identity)


def test_reconcile_removes_temporary_and_empty_orphans_but_preserves_locked_and_nonempty(
    store, identity
):
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    folder = store.root / "tenant-a/user-a/42/123"
    temporary, empty, locked, nonempty = (
        folder / name
        for name in (
            f".tmp-{uuid4()}",
            f"{uuid4()}.otlp.jsonl",
            f"{uuid4()}.otlp.jsonl",
            f"{uuid4()}.otlp.jsonl",
        )
    )
    temporary.write_bytes(b"unfinished metadata")
    empty.touch()
    locked.touch()
    nonempty.write_bytes(b"unregistered data")
    invalid = folder / ".tmp-invalid"
    invalid.touch()
    with Directory.root(folder) as directory, directory.lock(locked.name):
        assert store.reconcile(identity) == 2
    assert not temporary.exists() and not empty.exists()
    assert locked.exists() and nonempty.exists() and invalid.exists()
    assert store.reconcile(identity) == 1
    assert store.reconcile(identity) == 0


@pytest.mark.parametrize(
    "params", [{"turn_no": 0}, {"turn_no": True}, {"core_type": "invalid"}]
)
def test_invalid_execution_registration_has_no_run_file(store, identity, params):
    with pytest.raises(ValueError):
        store.start(
            identity,
            str(uuid4()),
            str(uuid4()),
            **{"core_type": "smolagents", **params},
        )
    assert not list(store.root.rglob("*.otlp.jsonl"))


def test_duplicate_turn_and_ingress_are_rejected_before_creating_a_second_file(
    store, identity
):
    with store.start(
        identity,
        str(uuid4()),
        str(uuid4()),
        core_type="smolagents",
        ingress_ref="ingress",
        turn_no=4,
    ) as writer:
        writer.finish("completed")
    for params in ({"turn_no": 4}, {"ingress_ref": "ingress"}):
        with pytest.raises(TrajectoryConflict, match="already registered"):
            store.start(
                identity, str(uuid4()), str(uuid4()), core_type="smolagents", **params
            )
    assert len(list(store.root.rglob("*.otlp.jsonl"))) == 1


def test_directory_enumeration_skips_missing_and_corrupt_candidates(store, identity):
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    assert (
        list(
            store.identities(
                tenant_ids=["missing", "tenant-a"], owner_user_id="missing"
            )
        )
        == []
    )
    assert list(
        store.identities(
            tenant_ids=["tenant-a"],
            owner_user_id="user-a",
            conversation_ids=["999", "123"],
        )
    ) == [identity]
    folder = store.root / "tenant-a/user-a/42"
    (folder / "999").mkdir()
    assert list(store.identities()) == [identity]
    shutil.copytree(folder / "123", folder / "124")
    assert list(store.identities()) == [identity]


def test_multiple_conversation_directories_are_reported_as_corrupt(store, identity):
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    source = store.root / "tenant-a/user-a/42/123"
    target = source.parent.parent / "99/123"
    shutil.copytree(source, target)
    meta = json.loads((target / "meta.json").read_text())
    meta["agent_id"] = "99"
    (target / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(TrajectoryCorrupt, match="multiple"):
        store.manifest(identity)


def test_closed_writer_and_terminal_run_reject_appends(store, identity):
    writer = fixtures.start(store, identity)
    writer.finish("completed")
    with pytest.raises(TrajectoryConflict, match="no longer accepts"):
        writer.append([], batch_id=str(uuid4()), expected_offset=0)
    writer.close()
    with pytest.raises(TrajectoryConflict, match="closed"):
        writer.finish("completed")
    with pytest.raises(TrajectoryConflict, match="not registered"):
        store._run(store.manifest(identity), str(uuid4()))


def test_writer_rejects_replaced_inode_and_corrupt_confirmed_prefix(store, identity):
    with fixtures.start(store, identity) as writer:
        writer.append(
            [fixtures.request(identity, writer.trajectory_id)],
            batch_id=str(uuid4()),
            expected_offset=0,
        )
        path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
        path.write_bytes(b"!" + path.read_bytes()[1:])
        with pytest.raises(TrajectoryCorrupt, match="checksum"):
            writer.finish("completed")
        assert store.manifest(identity)["runs"][0]["capture_state"] == "corrupt"
        path.unlink()
        path.touch()
        with pytest.raises(TrajectoryCorrupt, match="identity changed"):
            writer.finish("completed")


@pytest.mark.parametrize("offset", [-1, True])
def test_writer_rejects_invalid_offsets_before_writing(store, identity, offset):
    with fixtures.start(store, identity) as writer:
        with pytest.raises(ValueError, match="offset"):
            writer.append([], batch_id=str(uuid4()), expected_offset=offset)
        assert store.manifest(identity)["runs"][0]["confirmed_bytes"] == 0


def test_writer_rejects_conflicting_span_and_exhausted_dedup_budget(store, identity):
    with fixtures.start(store, identity) as writer:
        first = fixtures.request(identity, writer.trajectory_id)
        receipt = writer.append([first], batch_id=str(uuid4()), expected_offset=0)
        with pytest.raises(TrajectoryConflict, match="content changed"):
            writer.append(
                [fixtures.request(identity, writer.trajectory_id, text="different")],
                batch_id=str(uuid4()),
                expected_offset=receipt["confirmed_bytes"],
            )
        writer._seen.update(dict.fromkeys(range(100000)))
        with pytest.raises(TrajectoryConflict, match="deduplication budget"):
            writer.append(
                [
                    fixtures.request(
                        identity, writer.trajectory_id, span_id="0000000000000002"
                    )
                ],
                batch_id=str(uuid4()),
                expected_offset=receipt["confirmed_bytes"],
            )


def test_corrupt_hash_is_not_repaired_by_retrying_a_batch(store, identity):
    with fixtures.start(store, identity) as writer:
        batch = str(uuid4())
        payload = fixtures.request(identity, writer.trajectory_id)
        writer.append([payload], batch_id=batch, expected_offset=0)
        path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
        path.write_bytes(b"!" + path.read_bytes()[1:])
        with pytest.raises(TrajectoryCorrupt, match="checksum"):
            writer.append([payload], batch_id=batch, expected_offset=0)
        writer._hash = hashlib.sha256(b"wrong in-memory state")
        with pytest.raises(TrajectoryCorrupt, match="checksum"):
            writer.append(
                [payload], batch_id=str(uuid4()), expected_offset=path.stat().st_size
            )


def test_cleanup_handles_already_missing_file_without_double_counting(store, identity):
    with fixtures.start(store, identity) as writer:
        writer.finish("completed")
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    path.unlink()
    result = store.cleanup(identity, now=fixtures.NOW + timedelta(days=30))
    assert result["deleted_runs"] == result["failed_runs"] == 0
    assert store.manifest(identity)["runs"][0]["file_deleted_at"] is not None
    with pytest.raises(TrajectoryConflict, match="unavailable"):
        store.recover(identity, writer.trajectory_id)


def test_invalid_terminal_and_gap_codes_are_rejected(store, identity):
    with fixtures.start(store, identity) as writer:
        with pytest.raises(ValueError, match="terminal status"):
            writer.finish("unknown")
        with pytest.raises(ValueError, match="safe diagnostic"):
            writer.mark_incomplete("private/path")
        writer.finish("completed")
