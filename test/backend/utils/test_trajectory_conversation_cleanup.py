# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deletion queue, fixed file ownership and retry boundaries."""

import asyncio
import queue
import time
from unittest.mock import Mock
from uuid import uuid4

import pytest

# isort: split
import infrastructure.observability.trajectory_store as storage
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager


@pytest.fixture
def processor(tmp_path):
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    value = LocalTrajectoryProcessor(store, lambda: None, maintenance_store=store, cleanup_enabled=False)
    value.deleted_conversation_check = Mock(return_value=True)
    value._accepting = True
    return value


def run(processor, *, owner="owner", conversation="1", agent="42", active=False):
    identity = CaptureIdentity("tenant", owner, conversation, agent)
    writer = processor.store.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents")
    if not active:
        writer.finish("completed")
        writer.close()
    fixed_agent = processor.store.manifest(identity)["storage_agent_id"]
    writer.path = (
        processor.store.root / "tenant" / owner / (fixed_agent or "_unknown")
        / conversation / f"{writer.trajectory_id}.otlp.jsonl"
    )
    return identity, writer


def test_deletion_removes_all_rounds_in_fixed_directory_and_preserves_canaries(processor):
    identity, first = run(processor)
    _, second = run(processor, agent="99")
    _, other = run(processor, conversation="2")
    _, other_owner = run(processor, owner="other", conversation="3")
    before = {p: p.read_bytes() for p in (other.path, other_owner.path)}
    assert processor.request_conversation_cleanup([1], "owner")
    processor._delete_conversation_files()
    assert not first.path.exists() and not second.path.exists()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert all(r["cleanup_reason"] == "conversation_deleted" for r in processor.store.manifest(identity)["runs"])
    assert processor._deletions.empty()


def test_busy_file_is_marked_and_retried_after_writer_releases(processor, monkeypatch):
    identity, writer = run(processor, active=True)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: 100)
    try:
        processor.request_conversation_cleanup([1], "owner")
        processor._delete_conversation_files()
        assert writer.path.exists()
        assert processor.store.manifest(identity)["runs"][0]["cleanup_reason"] == "conversation_deleted"
    finally:
        writer.close()
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: 102)
    processor._delete_conversation_files()
    assert not writer.path.exists() and processor._deletions.empty()


def test_failed_unlink_remains_pending_and_retries(processor, monkeypatch):
    identity, writer = run(processor)
    unlink = storage.os.unlink

    def fail(path, **kwargs):
        if str(path).endswith(".otlp.jsonl"):
            raise PermissionError("temporarily denied")
        return unlink(path, **kwargs)

    monkeypatch.setattr(storage.os, "unlink", fail)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: 100)
    processor.request_conversation_cleanup([1], "owner")
    processor._delete_conversation_files()
    assert writer.path.exists()
    assert processor.store.manifest(identity)["runs"][0]["file_deleted_at"] is None
    monkeypatch.setattr(storage.os, "unlink", unlink)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: 102)
    processor._delete_conversation_files()
    assert not writer.path.exists()


@pytest.mark.parametrize("check", [False, ConnectionError("database unavailable")])
def test_no_files_deleted_without_confirmed_pg_absence(processor, check):
    _, writer = run(processor)
    processor.deleted_conversation_check = Mock(
        **({"side_effect": check} if isinstance(check, Exception) else {"return_value": check}),
    )
    processor.request_conversation_cleanup([1], "owner")
    processor._delete_conversation_files()
    assert writer.path.exists()


def test_missing_trajectory_is_an_idempotent_noop(processor):
    processor.request_conversation_cleanup([123], "owner")
    processor._delete_conversation_files()
    assert processor._deletions.empty()


def test_queue_is_bounded_and_shutdown_rejects_requests(processor):
    processor._deletions = queue.Queue(maxsize=1)
    assert processor.request_conversation_cleanup([1], "owner")
    assert not processor.request_conversation_cleanup([2], "owner")
    processor.request_stop()
    assert not processor.request_conversation_cleanup([3], "owner")


def test_restart_scan_reclaims_deleted_conversation_with_retention_disabled(processor):
    _, writer = run(processor)
    processor._maintain()
    assert not writer.path.exists()


def test_early_worker_ticks_do_not_extend_retry_deadline(processor, monkeypatch):
    _, writer = run(processor, active=True)
    clock = [100.0]
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: clock[0])
    try:
        processor.request_conversation_cleanup([1], "owner")
        processor._delete_conversation_files()
        clock[0] = 100.5
        processor._delete_conversation_files()
    finally:
        writer.close()
    clock[0] = 101.1
    processor._delete_conversation_files()
    assert not writer.path.exists()


def test_cleanup_continues_after_scan_budget(processor, monkeypatch):
    _, first = run(processor)
    _, second = run(processor)
    cleanup = processor.store.cleanup
    monkeypatch.setattr(processor.store, "cleanup", lambda *a, **kw: cleanup(*a, scan_limit=1, **kw))
    clock = [100.0]
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: clock[0])
    processor.request_conversation_cleanup([1], "owner")
    processor._delete_conversation_files()
    assert not first.path.exists() and second.path.exists()
    clock[0] = 102
    processor._delete_conversation_files()
    assert not second.path.exists() and processor._deletions.empty()


def test_deleted_local_writer_is_closed_before_reclamation(processor):
    _, writer = run(processor, active=True)
    processor._writers[writer.trajectory_id] = writer
    processor.request_conversation_cleanup([1], "owner")
    processor._delete_conversation_files()
    assert writer.fd is None and not writer.path.exists()
    assert not processor._writers


def test_managed_worker_executes_deletion_without_retention_timer(processor):
    _, writer = run(processor)
    manager = ThreadManager("trajectory-delete-test", {"background-service": LanePolicy("background-service", 1, 0)})
    manager.start()
    try:
        processor.start(manager, ManagedThreadSpec("trajectory-delete-writer", "test", close_hook=processor.request_stop))
        assert processor.request_conversation_cleanup([1], "owner")
        deadline = time.monotonic() + 3
        while writer.path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not writer.path.exists()
    finally:
        processor.shutdown()
        asyncio.run(manager.shutdown(timeout=2))
    assert manager.snapshot().active_count == 0
