# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Readers and background compensation tolerate independent lifecycle changes."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
    parse_time,
)
from ops.services.trajectory.archive import Archive
from ops.services.trajectory.primitives import Budget


@pytest.fixture
def archived(tmp_path):
    owner = CaptureIdentity("t", "u", "123", "7")
    store = TrajectoryFileStore(tmp_path / "traces", authorize=lambda _: None)
    run_id = str(uuid4())
    with store.start(owner, run_id, str(uuid4()), core_type="smolagents") as writer:
        attributes = {
            "tenant.id": "t",
            "nexent.owner_user_id": "u",
            "conversation.id": "123",
            "session.id": "123",
            "nexent.trace_id": "123",
            "nexent.trajectory_id": run_id,
            "input.value": "example",
        }
        payload = {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "1" * 32,
                                    "spanId": "1" * 16,
                                    "attributes": [
                                        {"key": key, "value": {"stringValue": value}}
                                        for key, value in attributes.items()
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
        writer.finish("completed")
    row = {"tenant_id": "t", "user_id": "u", "conversation_id": "123", "agent_id": "8"}
    return store, owner, run_id, row


def test_manifest_and_archive_read_do_not_contend_with_conversation_writer(archived):
    store, owner, run_id, row = archived
    archive = Archive(store)
    with store._session(owner):
        meta = archive.manifest(row)
        assert meta["runs"][0]["trajectory_id"] == run_id
        with archive.opened(row, run_id, Budget()) as (_, opened_meta, run):
            assert opened_meta["revision"] == meta["revision"]
            assert run["capture_state"] == "ready"


def test_reader_does_not_scan_an_unrelated_tenant(archived):
    store, _, _, row = archived
    (store.root / "unrelated").symlink_to(store.root / "t", target_is_directory=True)
    assert Archive(store).manifest(row)["agent_id"] == "7"


def test_former_tenant_archive_is_not_reported_as_uncaptured(archived):
    from ops.services.trajectory.primitives import QueryError

    store, _, _, row = archived
    with pytest.raises(QueryError, match="trajectory_not_found"):
        Archive(store).manifest({**row, "tenant_id": "new-tenant"})


@pytest.mark.parametrize("missing", ["conversation", "membership"])
def test_compensation_skips_revoked_owner_without_database_error(mocker, missing):
    from infrastructure.rdb.trajectory_repository import ExecutionRepository

    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = (
        None if missing == "conversation" else object()
    )
    session.execute.return_value.first.return_value = (
        None if missing == "membership" else ("u",)
    )
    errors = []

    @contextmanager
    def scoped():
        try:
            yield session
        except Exception as error:
            errors.append(error)
            raise

    mocker.patch("infrastructure.rdb.trajectory_repository.get_db_session", scoped)
    owner = CaptureIdentity("t", "u", "123", "7")
    ExecutionRepository().sync(owner, {"trajectory_id": "run", "status": "success"})
    assert errors == []
    session.get.assert_not_called()
    session.add.assert_not_called()


def test_registration_keeps_strict_owner_check(mocker):
    from infrastructure.rdb.trajectory_repository import ExecutionRepository

    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    @contextmanager
    def scoped():
        yield session

    mocker.patch("infrastructure.rdb.trajectory_repository.get_db_session", scoped)
    with pytest.raises(PermissionError, match="no longer authorized"):
        ExecutionRepository().begin(CaptureIdentity("t", "u", "123", "7"), str(uuid4()))
    session.add.assert_not_called()


def test_compensation_does_not_hide_database_failure(mocker):
    from infrastructure.rdb.trajectory_repository import ExecutionRepository

    session = Mock()
    session.execute.side_effect = RuntimeError("database unavailable")

    @contextmanager
    def scoped():
        yield session

    mocker.patch("infrastructure.rdb.trajectory_repository.get_db_session", scoped)
    with pytest.raises(RuntimeError, match="database unavailable"):
        ExecutionRepository().sync(CaptureIdentity("t", "u", "123", "7"), {})


def test_unchanged_archive_reuses_checksum_but_file_changes_are_rejected(
    archived, mocker
):
    from infrastructure.trace.trajectory_io import prefix_hash
    from ops.services.trajectory.primitives import QueryError

    store, _, run_id, row = archived
    archive = Archive(store)
    hashed = mocker.patch(
        "ops.services.trajectory.archive.prefix_hash", wraps=prefix_hash
    )
    for _ in range(2):
        with archive.opened(row, run_id, Budget()):
            pass
    assert hashed.call_count == 1
    path = store.root / "t/u/7/123" / f"{run_id}.otlp.jsonl"
    raw = path.read_bytes()
    path.write_bytes(b"!" + raw[1:])
    with (
        pytest.raises(QueryError, match="trajectory_corrupt"),
        archive.opened(row, run_id, Budget()),
    ):
        pytest.fail("Changed content must never be returned")


def test_shorter_retention_is_enforced_even_when_expiry_persistence_is_busy(archived):
    from ops.services.trajectory.primitives import QueryError

    store, owner, run_id, row = archived
    meta = store.manifest(owner)
    finished = parse_time(meta["runs"][0]["finished_at"])
    store.retention_days = 1
    store.clock = lambda: finished + timedelta(days=2)
    archive = Archive(store)
    with store._session(owner):
        tightened = archive.manifest(row)
        assert parse_time(tightened["runs"][0]["expires_at"]) == finished + timedelta(
            days=1
        )
        with (
            pytest.raises(QueryError, match="content_expired"),
            archive.opened(row, run_id, Budget()),
        ):
            pytest.fail("Expired bodies must never be returned")


def test_checksum_cache_never_bypasses_current_authorization(archived):
    from ops.services.trajectory.primitives import QueryError

    store, _, run_id, row = archived
    archive = Archive(store)
    with archive.opened(row, run_id, Budget()):
        pass
    store.authorize = Mock(side_effect=PermissionError("Owner revoked"))
    with (
        pytest.raises(QueryError, match="trajectory_not_found"),
        archive.opened(row, run_id, Budget()),
    ):
        pytest.fail("Revoked callers must never reuse cached verification")


def test_read_only_session_cannot_create_storage(tmp_path):
    store = TrajectoryFileStore(tmp_path / "traces", authorize=lambda _: None)
    owner = CaptureIdentity("t", "u", "123", "7")
    with (
        pytest.raises(ValueError, match="read-only"),
        store._session(owner, create=True, read_only=True),
    ):
        pytest.fail("Read-only sessions must never create a conversation directory")
    assert not (store.root / "t").exists()
