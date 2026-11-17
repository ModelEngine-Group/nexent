# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""File persistence contracts, independent of HTTP and monitoring providers."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryConflict,
    TrajectoryCorrupt,
    TrajectoryFileStore,
)

NOW = datetime(2026, 11, 9, tzinfo=UTC)


@pytest.fixture
def identity():
    return CaptureIdentity("tenant-a", "user-a", "123", "42")


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "traces"
    TrajectoryFileStore.provision(root)
    return TrajectoryFileStore(root, authorize=lambda identity: None, clock=lambda: NOW)


def request(identity, run_id, *, span_id="0000000000000001", text='你好\n"\\'):
    attributes = {
        "tenant.id": identity.tenant_id,
        "nexent.owner_user_id": identity.owner_user_id,
        "conversation.id": identity.conversation_id,
        "session.id": identity.conversation_id,
        "nexent.trace_id": identity.conversation_id,
        "nexent.trajectory_id": run_id,
        "input.value": text,
    }
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "1234567890abcdef1234567890abcdef",
                                "spanId": span_id,
                                "name": "agent.run",
                                "kind": 1,
                                "startTimeUnixNano": "1794182400000000000",
                                "endTimeUnixNano": "1794182400001000000",
                                "attributes": [
                                    {"key": key, "value": {"stringValue": value}} for key, value in attributes.items()
                                ],
                                "status": {"code": 1},
                            }
                        ]
                    }
                ]
            }
        ]
    }


def start(store, identity):
    return store.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents")


def test_durable_append_and_terminal_publication(store, identity):
    with start(store, identity) as writer:
        payload = request(identity, writer.trajectory_id)
        receipt = writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
        path = store.root / "tenant-a/user-a/42/123" / f"{writer.trajectory_id}.otlp.jsonl"
        raw = path.read_bytes()
        manifest = store.manifest(identity)
        run = manifest["runs"][0]
        assert run["confirmed_bytes"] == receipt["confirmed_bytes"] == len(raw)
        assert run["confirmed_sha256"] == hashlib.sha256(raw).hexdigest()
        assert manifest["publication_no"] == 0
        decoded = json.loads(raw)
        saved_attrs = decoded["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        assert saved_attrs.pop() == {"key": "nexent.export_seq", "value": {"intValue": "1"}}
        assert decoded == payload
        writer.finish("completed")
    manifest = store.manifest(identity)
    assert manifest["trace_id"] == "123"
    assert manifest["runs"][0]["capture_state"] == "ready"
    assert manifest["runs"][0]["file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["publication_no"] == 1
    assert manifest["runs"][0]["expires_at"] == "2026-12-09T00:00:00Z"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_batch_retry_span_dedup_and_conflicting_retry(store, identity):
    with start(store, identity) as writer:
        payload = request(identity, writer.trajectory_id)
        batch = str(uuid4())
        receipt = writer.append([payload], batch_id=batch, expected_offset=0)
        assert writer.append([payload], batch_id=batch, expected_offset=0) == receipt
        offset = receipt["confirmed_bytes"]
        again = writer.append([payload], batch_id=str(uuid4()), expected_offset=offset)
        assert again["confirmed_bytes"] == offset
        with pytest.raises(TrajectoryConflict):
            writer.append([request(identity, writer.trajectory_id, text="changed")], batch_id=batch, expected_offset=0)
        with pytest.raises(TrajectoryConflict):
            writer.append([payload], batch_id=str(uuid4()), expected_offset=0)


def test_fixed_storage_agent_and_cross_tenant_conflict(store, identity):
    with start(store, identity) as writer:
        writer.finish("completed")
    changed = CaptureIdentity("tenant-a", "user-a", "123", "99")
    with start(store, changed) as writer:
        writer.finish("failed")
    manifest = store.manifest(changed)
    assert manifest["agent_id"] == "42"
    assert [r["root_agent_id"] for r in manifest["runs"]] == ["42", "99"]
    assert [r["turn_no"] for r in manifest["runs"]] == [1, 2]
    with pytest.raises(TrajectoryConflict):
        start(store, CaptureIdentity("tenant-b", "user-a", "123", "99"))


def test_actual_lock_excludes_takeover_and_interrupted_prefix_recovery(store, identity):
    writer = start(store, identity)
    run_id = writer.trajectory_id
    payload = request(identity, run_id)
    receipt = writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
    with pytest.raises(TrajectoryConflict):
        store.recover(identity, run_id)
    writer.close()
    path = store.root / f"tenant-a/user-a/42/123/{run_id}.otlp.jsonl"
    with path.open("ab") as handle:
        handle.write(b'{"unconfirmed":')
    store.recover(identity, run_id)
    assert path.stat().st_size == receipt["confirmed_bytes"]
    run = store.manifest(identity)["runs"][0]
    assert run["business_status"] == "interrupted"
    assert run["capture_state"] == "incomplete"
    assert run["finished_at"] == "2026-11-09T00:00:00Z"


def test_confirmed_corruption_is_never_published_ready(store, identity):
    writer = start(store, identity)
    writer.append([request(identity, writer.trajectory_id)], batch_id=str(uuid4()), expected_offset=0)
    writer.close()
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    path.write_bytes(b"corrupt")
    with pytest.raises(TrajectoryCorrupt):
        store.recover(identity, writer.trajectory_id)
    assert store.manifest(identity)["runs"][0]["capture_state"] == "corrupt"


def test_failed_meta_commit_does_not_confirm_file_tail(store, identity, monkeypatch):
    with start(store, identity) as writer:
        original = store._save_manifest
        monkeypatch.setattr(store, "_save_manifest", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            writer.append([request(identity, writer.trajectory_id)], batch_id=str(uuid4()), expected_offset=0)
        monkeypatch.setattr(store, "_save_manifest", original)
        assert store.manifest(identity)["runs"][0]["confirmed_bytes"] == 0
        writer.append([request(identity, writer.trajectory_id)], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("completed")
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    assert len(path.read_text().splitlines()) == 1


def test_large_inline_unicode_is_preserved(store, identity):
    text = '中\n"\\😀' * 400_000
    with start(store, identity) as writer:
        writer.append([request(identity, writer.trajectory_id, text=text)], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("completed")
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    data = json.loads(path.read_bytes())
    attributes = data["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
    assert next(a["value"]["stringValue"] for a in attributes if a["key"] == "input.value") == text
    assert len(path.read_bytes().splitlines()) == 1


def test_retention_boundary_skips_active_and_deletion_is_idempotent(store, identity):
    with start(store, identity) as old:
        old.finish("completed")
    active = start(store, identity)
    try:
        result = store.cleanup(identity, before_days=30, now=NOW + timedelta(days=30))
        assert result["deleted_runs"] == 1
        assert result["skipped_active"] == 1
        assert store.cleanup(identity, before_days=30, now=NOW + timedelta(days=30))["deleted_runs"] == 0
        manifest = store.manifest(identity)
        assert manifest["cleanup_version"] == 1
        assert manifest["had_expired_history"]
        assert manifest["runs"][1]["capture_state"] == "writing"
    finally:
        active.close()


def test_authorization_runs_before_filesystem_access(store, identity):
    def deny(_identity):
        raise PermissionError("denied")

    store.authorize = deny
    with pytest.raises(PermissionError):
        start(store, identity)
    assert not (store.root / "tenant-a").exists()


@pytest.mark.parametrize(
    "field,value",
    [("tenant_id", "../outside"), ("owner_user_id", "a/b"), ("conversation_id", "01"), ("root_agent_id", "-1")],
)
def test_invalid_identity_has_no_filesystem_side_effects(store, field, value):
    kwargs = {"tenant_id": "tenant", "owner_user_id": "user", "conversation_id": "1", "root_agent_id": "2"}
    kwargs[field] = value
    with pytest.raises(ValueError):
        identity = CaptureIdentity(**kwargs)
        start(store, identity)
    assert not (store.root / "tenant").exists()


def test_symlink_and_misconfigured_mount_fail_closed(store, identity, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "tenant-a").symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        start(store, identity)
    assert list(outside.iterdir()) == []
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore(store.root, authorize=lambda _: None, storage_mode="shared_directory")


def test_mixed_ownership_payload_is_rejected_without_confirmation(store, identity):
    with start(store, identity) as writer:
        other = CaptureIdentity("tenant-b", "user-a", "123", "42")
        with pytest.raises(TrajectoryConflict):
            writer.append([request(other, writer.trajectory_id)], batch_id=str(uuid4()), expected_offset=0)
        assert store.manifest(identity)["runs"][0]["confirmed_bytes"] == 0


def test_commit_uncertainty_retries_without_duplicate_or_lost_hash(store, identity, monkeypatch):
    with start(store, identity) as writer:
        payload = request(identity, writer.trajectory_id)
        batch = str(uuid4())
        original = store._save_manifest

        def save_then_fail(directory, manifest):
            original(directory, manifest)
            raise OSError("directory sync uncertain")

        monkeypatch.setattr(store, "_save_manifest", save_then_fail)
        with pytest.raises(OSError):
            writer.append([payload], batch_id=batch, expected_offset=0)
        monkeypatch.setattr(store, "_save_manifest", original)
        receipt = writer.append([payload], batch_id=batch, expected_offset=0)
        receipt = writer.append(
            [request(identity, writer.trajectory_id, span_id="0000000000000002")],
            batch_id=str(uuid4()),
            expected_offset=receipt["confirmed_bytes"],
        )
        writer.finish("completed")
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    assert len(path.read_text().splitlines()) == 2
    assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["confirmed_sha256"]


def test_missing_registered_file_is_corrupt_even_without_confirmed_bytes(store, identity):
    writer = start(store, identity)
    writer.close()
    path = store.root / f"tenant-a/user-a/42/123/{writer.trajectory_id}.otlp.jsonl"
    path.unlink()
    with pytest.raises(TrajectoryCorrupt):
        store.recover(identity, writer.trajectory_id)
    assert not path.exists()
    assert store.manifest(identity)["runs"][0]["capture_state"] == "corrupt"


def test_cleanup_failure_retries_and_keeps_revoked_state(store, identity, monkeypatch):
    with start(store, identity) as writer:
        writer.finish("completed")
    original = os.unlink

    def fail_run_unlink(path, **kwargs):
        if str(path).endswith(".otlp.jsonl"):
            raise PermissionError("cannot delete")
        return original(path, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_run_unlink)
    result = store.cleanup(identity, now=NOW + timedelta(days=30))
    assert result["failed_runs"] == 1 and result["deleted_runs"] == 0
    run = store.manifest(identity)["runs"][0]
    assert run["capture_state"] == "expired" and run["file_deleted_at"] is None
    monkeypatch.setattr(os, "unlink", original)
    assert store.cleanup(identity, now=NOW + timedelta(days=30))["deleted_runs"] == 1
    assert store.manifest(identity)["cleanup_version"] == 1


def test_repeated_finish_is_idempotent_and_cannot_change_outcome(store, identity):
    with start(store, identity) as writer:
        writer.finish("completed")
        writer.finish("completed")
        with pytest.raises(TrajectoryConflict):
            writer.finish("failed")
    assert store.manifest(identity)["publication_no"] == 1


def test_initial_metadata_failure_can_retry_without_unregistered_execution(store, identity, monkeypatch):
    original = store._save_manifest

    def fail(*_):
        raise OSError("Controlled initial metadata failure")

    monkeypatch.setattr(store, "_save_manifest", fail)
    with pytest.raises(OSError):
        start(store, identity)
    assert not list(store.root.rglob("*.otlp.jsonl"))
    monkeypatch.setattr(store, "_save_manifest", original)
    with start(store, identity) as writer:
        writer.finish("completed")
    assert store.manifest(identity)["runs"][0]["capture_state"] == "ready"


def test_missing_manifest_with_existing_data_fails_closed(store, identity):
    with start(store, identity) as writer:
        writer.append([request(identity, writer.trajectory_id)], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("completed")
    path = store.root / "tenant-a/user-a/42/123/meta.json"
    path.unlink()
    with pytest.raises(TrajectoryCorrupt):
        start(store, identity)
    assert len(list(store.root.rglob("*.otlp.jsonl"))) == 1


@pytest.mark.parametrize("corruption", ["object", "offset", "hash", "uuid"])
def test_invalid_metadata_reports_corrupt_before_file_operations(store, identity, corruption):
    with start(store, identity) as writer:
        writer.finish("completed")
    path = store.root / "tenant-a/user-a/42/123/meta.json"
    meta = json.loads(path.read_text())
    if corruption == "object":
        meta = []
    elif corruption == "offset":
        meta["runs"][0]["confirmed_bytes"] = -1
    elif corruption == "hash":
        meta["runs"][0]["confirmed_sha256"] = "invalid"
    else:
        meta["runs"][0]["trajectory_id"] = "../other"
    path.write_text(json.dumps(meta))
    with pytest.raises(TrajectoryCorrupt):
        store.manifest(identity)
    assert len(list(store.root.rglob("*.otlp.jsonl"))) == 1


def test_manual_cleanup_uses_requested_days_and_preserves_default_retention(store, identity):
    with start(store, identity) as writer:
        writer.finish("completed")
    result = store.cleanup(identity, before_days=7, now=NOW + timedelta(days=14))
    assert result["deleted_runs"] == 1 and store.retention_days == 30
    meta = store.manifest(identity)
    assert meta["had_manual_cleanup"] and meta["runs"][0]["cleanup_reason"] == "manual"
    assert not list(store.root.rglob("*.otlp.jsonl"))


def test_shorter_retention_persists_and_later_extension_does_not_revive_history(store, identity):
    with start(store, identity) as writer:
        writer.finish("completed")
    store.retention_days = 7
    assert store.cleanup(identity, now=NOW + timedelta(days=2))["deleted_runs"] == 0
    assert store.manifest(identity)["runs"][0]["expires_at"] == "2026-11-16T00:00:00Z"
    store.retention_days = 30
    assert store.cleanup(identity, now=NOW + timedelta(days=7))["deleted_runs"] == 1
    assert store.manifest(identity)["runs"][0]["capture_state"] == "expired"


def test_deleted_tombstone_expires_after_seven_days_while_coverage_summary_remains(store, identity):
    with start(store, identity) as writer:
        writer.finish("completed")
    assert store.cleanup(identity, now=NOW + timedelta(days=30))["deleted_runs"] == 1
    store.cleanup(identity, now=NOW + timedelta(days=37, microseconds=-1))
    assert len(store.manifest(identity)["runs"]) == 1
    store.cleanup(identity, now=NOW + timedelta(days=37))
    meta = store.manifest(identity)
    assert meta["runs"] == [] and meta["expired_execution_count"] == 1
    assert meta["had_expired_history"] and meta["next_turn_no"] == 2
