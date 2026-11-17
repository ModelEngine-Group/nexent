# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-RECOVERY-D5-001: real process death and file durability risks."""

import asyncio
import copy
import errno
import hashlib
import json
import os
import selectors
import stat
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from infrastructure.observability import trajectory_store
from infrastructure.observability.trajectory_otlp import span_request
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryConflict,
    TrajectoryCorrupt,
    TrajectoryFileStore,
)
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from opentelemetry.sdk.trace import TracerProvider

IDENTITY = CaptureIdentity("fixture-tenant", "fixture-owner", "123", "42")
REPO = Path(__file__).resolve().parents[3]
pytestmark = [pytest.mark.case_id("CHAT-TRAJECTORY-RECOVERY-D5-001"), pytest.mark.stage("D5"), pytest.mark.rel]


def request(run_id, text):
    provider = TracerProvider(shutdown_on_exit=False)
    span = provider.get_tracer("risk-fixture").start_span(
        "model.attempt",
        attributes={
            "tenant.id": IDENTITY.tenant_id,
            "nexent.owner_user_id": IDENTITY.owner_user_id,
            "conversation.id": IDENTITY.conversation_id,
            "session.id": IDENTITY.conversation_id,
            "nexent.trace_id": IDENTITY.conversation_id,
            "nexent.trajectory_id": run_id,
            "input.value": text,
        },
    )
    span.end()
    result = span_request(span)
    provider.shutdown()
    return result


def environment():
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "backend"), str(REPO / "sdk")])}


def open_store(root):
    return TrajectoryFileStore(root, authorize=lambda identity: None)


def child(root, fault):
    store = open_store(root)
    writer = store.start(IDENTITY, str(uuid4()), str(uuid4()), core_type="smolagents")
    payload = request(writer.trajectory_id, "confirmed-prefix")
    batch_id = str(uuid4())
    receipt = writer.append([payload], batch_id=batch_id, expected_offset=0)
    assert writer.append([payload], batch_id=batch_id, expected_offset=0) == receipt
    assert (
        writer.append([payload], batch_id=str(uuid4()), expected_offset=receipt["confirmed_bytes"])["confirmed_bytes"]
        == receipt["confirmed_bytes"]
    )
    bad = copy.deepcopy(payload)
    bad["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] = "changed"
    with pytest.raises(TrajectoryConflict):
        writer.append([bad], batch_id=batch_id, expected_offset=0)
    with pytest.raises(TrajectoryConflict):
        writer.append([bad], batch_id=str(uuid4()), expected_offset=receipt["confirmed_bytes"])
    with pytest.raises(TrajectoryConflict):
        writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
    print(json.dumps({"trajectory_id": writer.trajectory_id, "receipt": receipt}), flush=True)
    if fault == "hold":
        sys.stdin.read()
        return
    original_write = trajectory_store.write_all
    original_sync = os.fsync
    original_replace = os.replace
    renamed = False

    def write(fd, data):
        if (fault == "body" and len(data) > 16384) or (fault == "newline" and data == b"\n"):
            if fault == "body":
                original_write(fd, data[:137])
            os._exit(17)
        return original_write(fd, data)

    def sync(fd):
        original_sync(fd)
        mode = os.fstat(fd).st_mode
        if (
            (fault == "file_fsync" and fd == writer.fd)
            or (fault == "meta_fsync" and fd != writer.fd and stat.S_ISREG(mode))
            or (fault == "directory_fsync" and renamed and stat.S_ISDIR(mode))
        ):
            os._exit(17)

    def replace(src, dst, **kwargs):
        nonlocal renamed
        result = original_replace(src, dst, **kwargs)
        if dst == "meta.json":
            renamed = True
            if fault == "rename":
                os._exit(17)
        return result

    trajectory_store.write_all = write
    os.fsync = sync
    os.replace = replace
    if fault == "terminal":
        original_save = store._save_manifest

        def save(directory, manifest):
            if manifest["publication_no"]:
                os._exit(17)
            return original_save(directory, manifest)

        store._save_manifest = save
    writer.append(
        [request(writer.trajectory_id, '长正文\n\\"😀' * 400000)],
        batch_id=str(uuid4()),
        expected_offset=receipt["confirmed_bytes"],
    )
    writer.finish("completed")
    raise AssertionError("Fault boundary was never reached")


@pytest.mark.parametrize(
    "fault", ["body", "newline", "file_fsync", "meta_fsync", "rename", "directory_fsync", "terminal"]
)
def test_trj_recovery_process_death_preserves_confirmed_prefix(tmp_path, fault):
    with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        TrajectoryFileStore.provision(root)
        # The canary sits outside the registered root's tenant directory tree.
        canary = root.parent / f"canary-{root.name}"
        canary.write_text("untouched")
        try:
            completed = subprocess.run(
                [sys.executable, __file__, "child", str(root), fault],
                cwd=REPO,
                env=environment(),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            assert completed.returncode == 17, completed.stderr
            ack = json.loads(completed.stdout.splitlines()[0])
            store = open_store(root)
            before = store.manifest(IDENTITY)["runs"][0]
            run_id = ack["trajectory_id"]
            store.recover(IDENTITY, run_id)
            run = store.manifest(IDENTITY)["runs"][0]
            path = root / f"fixture-tenant/fixture-owner/42/123/{run_id}.otlp.jsonl"
            raw = path.read_bytes()
            assert len(raw) == before["confirmed_bytes"] >= ack["receipt"]["confirmed_bytes"]
            assert hashlib.sha256(raw).hexdigest() == run["confirmed_sha256"] == run["file_sha256"]
            values = [json.loads(line) for line in raw.splitlines()]
            spans = [
                s for v in values for r in v["resourceSpans"] for scope in r["scopeSpans"] for s in scope["spans"]
            ]
            assert len({(s["traceId"], s["spanId"]) for s in spans}) == len(spans)
            sequences = [
                int(next(a["value"]["intValue"] for a in s["attributes"] if a["key"] == "nexent.export_seq"))
                for s in spans
            ]
            assert sequences == list(range(1, len(spans) + 1))
            assert run["last_export_seq"] == str(len(spans))
            assert b"confirmed-prefix" in raw
            assert run["business_status"] == "interrupted" and run["capture_state"] == "incomplete"
            assert run["finished_at"] == before["last_durable_at"]
            expires = run["expires_at"]
            store.recover(IDENTITY, run_id)
            assert store.manifest(IDENTITY)["runs"][0]["expires_at"] == expires
            assert canary.read_text() == "untouched"
        finally:
            canary.unlink(missing_ok=True)
    assert not root.exists()


def test_trj_recovery_live_file_lock_and_corruption(tmp_path):
    with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        TrajectoryFileStore.provision(root)
        process = subprocess.Popen(
            [sys.executable, __file__, "child", str(root), "hold"],
            cwd=REPO,
            env=environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=15), "Writer never acknowledged its first durable batch"
                ack = json.loads(process.stdout.readline())
            store = open_store(root)
            with pytest.raises(TrajectoryConflict):
                store.recover(IDENTITY, ack["trajectory_id"])
            process.terminate()
            process.wait(timeout=5)
            store.recover(IDENTITY, ack["trajectory_id"])
            path = root / f"fixture-tenant/fixture-owner/42/123/{ack['trajectory_id']}.otlp.jsonl"
            path.write_bytes(b"damaged-confirmed-prefix")
            with pytest.raises(TrajectoryCorrupt):
                store.recover(IDENTITY, ack["trajectory_id"])
            assert store.manifest(IDENTITY)["runs"][0]["capture_state"] == "corrupt"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        assert process.poll() is not None


@pytest.mark.parametrize("failure_code", [errno.ENOSPC, errno.EACCES])
def test_trj_recovery_queue_and_disk_failures_keep_business_independent(tmp_path, monkeypatch, failure_code):
    with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        TrajectoryFileStore.provision(root)
        store = open_store(root)
        meta = SimpleNamespace(
            tenant_id=IDENTITY.tenant_id,
            user_id=IDENTITY.owner_user_id,
            agent_id=42,
            conversation_id=123,
            extra_metadata={},
        )
        processor = LocalTrajectoryProcessor(store, lambda: meta, queue_max_bytes=4096, run_queue_max_bytes=2048)
        manager = ThreadManager("recovery-risk", {"background-service": LanePolicy("background-service", 1, 0)})
        manager.start()
        processor.start(manager, ManagedThreadSpec("file-writer", "risk-fixture", close_hook=processor.request_stop))
        provider = TracerProvider(shutdown_on_exit=False)
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("risk-fixture")
        try:
            with tracer.start_as_current_span("agent.run") as span:
                span.set_attribute("output.value", "x" * 8192)
                business_result = "completed-once"
            assert processor.force_flush(3000)
            assert business_result == "completed-once"
            assert processor._bytes <= 4096 and all(v <= 2048 for v in processor._run_bytes.values())
            assert store.manifest(IDENTITY)["runs"][0]["capture_state"] == "incomplete"
            original = trajectory_store.write_all

            def full_disk(*args):
                raise OSError(failure_code, "controlled-file-failure")

            monkeypatch.setattr(trajectory_store, "write_all", full_disk)
            processor.run_queue_max_bytes = 4096
            with tracer.start_as_current_span("agent.run"):
                business_result = "completed-despite-disk-failure"
            assert processor.force_flush(3000)
            assert business_result == "completed-despite-disk-failure"
            failed = store.manifest(IDENTITY)["runs"][1]
            assert failed["confirmed_bytes"] == 0 and failed["capture_state"] == "incomplete"
            monkeypatch.setattr(trajectory_store, "write_all", original)
            with tracer.start_as_current_span("agent.run"):
                pass
            assert processor.force_flush(3000)
            assert store.manifest(IDENTITY)["runs"][2]["capture_state"] == "ready"
        finally:
            processor.shutdown()
            provider.shutdown()
            asyncio.run(manager.shutdown(timeout=3))
        assert manager.snapshot().active_count == 0
        assert processor._bytes == 0


def test_trj_recovery_publication_order_and_no_resurrection(tmp_path, monkeypatch):
    with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        TrajectoryFileStore.provision(root)
        now = datetime(2026, 11, 9, tzinfo=UTC)
        store = open_store(root)
        store.clock = lambda: now
        writer = store.start(IDENTITY, str(uuid4()), str(uuid4()), core_type="smolagents")
        syncs = []
        original = os.fsync

        def record(fd):
            original(fd)
            syncs.append("file" if fd == writer.fd else "meta" if stat.S_ISREG(os.fstat(fd).st_mode) else "directory")

        try:
            monkeypatch.setattr(os, "fsync", record)
            writer.append([request(writer.trajectory_id, "confirmed")], batch_id=str(uuid4()), expected_offset=0)
            assert syncs == ["file", "meta", "directory"]
            monkeypatch.setattr(os, "fsync", original)
            writer.finish("completed")
            before = store.manifest(IDENTITY)["runs"][0]
            writer.finish("completed")
            assert store.manifest(IDENTITY)["publication_no"] == 1
            assert store.cleanup(IDENTITY, now=now + timedelta(days=30))["pending_runs"] == 1
            with pytest.raises(TrajectoryConflict):
                writer.finish("completed")
            writer.close()
            assert store.cleanup(IDENTITY, now=now + timedelta(days=30))["deleted_runs"] == 1
            with pytest.raises(TrajectoryConflict):
                store.recover(IDENTITY, writer.trajectory_id)
            after = store.manifest(IDENTITY)["runs"][0]
            assert after["expires_at"] == before["expires_at"]
            assert after["capture_state"] == "expired" and after["file_deleted_at"]
        finally:
            writer.close()


def child_active(root):
    store = open_store(root)
    metadata = SimpleNamespace(
        tenant_id=IDENTITY.tenant_id,
        user_id=IDENTITY.owner_user_id,
        conversation_id=123,
        agent_id=42,
        extra_metadata={},
    )
    processor = LocalTrajectoryProcessor(store, lambda: metadata)
    manager = ThreadManager("active-fragment-risk", {"background-service": LanePolicy("background-service", 1, 0)})
    manager.start()
    processor.start(manager, ManagedThreadSpec("writer", "risk-fixture", close_hook=processor.request_stop))
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    try:
        with provider.get_tracer("risk-fixture").start_as_current_span("agent.run") as root_span:
            root_span.set_attributes({"input.value": "active-input", "output.value": "partial-output"})
            assert processor.force_flush(3000)
            print(json.dumps(store.manifest(IDENTITY)["runs"][0]), flush=True)
            sys.stdin.read()
    finally:
        processor.shutdown()
        provider.shutdown()
        asyncio.run(manager.shutdown(timeout=3))


def test_trj_recovery_active_fragments_and_abandoned_temporaries(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    process = subprocess.Popen(
        [sys.executable, __file__, "active", str(tmp_path)],
        cwd=REPO,
        env=environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=15)
            before = json.loads(process.stdout.readline())
        process.kill()
        process.wait(timeout=5)
        store = open_store(tmp_path)
        store.recover(IDENTITY, before["trajectory_id"])
        run = store.manifest(IDENTITY)["runs"][0]
        directory = tmp_path / "fixture-tenant/fixture-owner/42/123"
        raw = (directory / f"{before['trajectory_id']}.otlp.jsonl").read_bytes()
        assert len(raw) >= before["confirmed_bytes"] > 0
        assert b"active-input" in raw and b"partial-output" in raw
        assert b"nexent.trajectory.snapshot" in raw
        assert run["business_status"] == "interrupted" and run["capture_state"] == "incomplete"
        temporary = directory / f".tmp-{uuid4()}"
        temporary.write_text("partial metadata")
        orphan = directory / f"{uuid4()}.otlp.jsonl"
        orphan.touch()
        unregistered_valid = directory / f"{uuid4()}.otlp.jsonl"
        unregistered_valid.write_bytes(raw)
        assert store.reconcile(IDENTITY) == 2
        assert not temporary.exists() and not orphan.exists()
        assert unregistered_valid.read_bytes() == raw
        assert (directory / f"{before['trajectory_id']}.otlp.jsonl").read_bytes() == raw
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    assert process.poll() is not None


def test_trj_recovery_publication_retries_after_repeated_metadata_failure(tmp_path, monkeypatch):
    TrajectoryFileStore.provision(tmp_path)
    store = open_store(tmp_path)
    meta = SimpleNamespace(
        tenant_id=IDENTITY.tenant_id,
        user_id=IDENTITY.owner_user_id,
        agent_id=42,
        conversation_id=123,
        extra_metadata={},
    )
    processor = LocalTrajectoryProcessor(store, lambda: meta)
    manager = ThreadManager("publication-risk", {"background-service": LanePolicy("background-service", 1, 0)})
    manager.start()
    processor.start(manager, ManagedThreadSpec("writer", "risk-fixture", close_hook=processor.request_stop))
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    attempts = []
    retried = threading.Event()
    original = store._save_manifest

    def fail_publication(directory, manifest):
        if manifest["publication_no"]:
            attempts.append(1)
            if len(attempts) >= 3:
                retried.set()
            raise OSError(errno.ENOSPC, "controlled-meta-failure")
        return original(directory, manifest)

    try:
        monkeypatch.setattr(store, "_save_manifest", fail_publication)
        with provider.get_tracer("risk-fixture").start_as_current_span("agent.run") as span:
            span.set_attribute("output.value", "durable-before-publication")
        assert retried.wait(5), "Publication was not retried after storage failure"
        before = store.manifest(IDENTITY)["runs"][0]
        assert before["confirmed_bytes"] > 0 and before["publication_no"] is None
        monkeypatch.setattr(store, "_save_manifest", original)
        assert processor.force_flush(3000)
        after = store.manifest(IDENTITY)["runs"][0]
        assert after["publication_no"] == 1 and after["file_bytes"] == before["confirmed_bytes"]
        assert after["file_sha256"] == before["confirmed_sha256"]
    finally:
        monkeypatch.setattr(store, "_save_manifest", original)
        processor.shutdown()
        provider.shutdown()
        asyncio.run(manager.shutdown(timeout=3))
    assert manager.snapshot().active_count == 0


if __name__ == "__main__":
    if sys.argv[1] == "active":
        child_active(Path(sys.argv[2]))
    else:
        assert sys.argv[1] == "child"
        child(Path(sys.argv[2]), sys.argv[3])
