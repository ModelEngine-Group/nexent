# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recovery discovery, finite scheduling and shutdown use owned storage and lanes."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.file.source_recovery import (
    reconcile_sources,
    schedule_source_reconciliation,
)
from nexent.storage.errors import ScopeDenied, Unavailable
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery

from infrastructure.rdb.source_candidates import DATASET, bind_source_candidates
from test.backend.infrastructure.test_record_store import context
from test.backend.services import test_source_publish as source_fixtures
from test.backend.services import test_source_reconcile as recovery_fixtures
from test.backend.services.test_source_publish import FILE_ID

publication = source_fixtures.publication
recovery = recovery_fixtures.recovery


def test_discovery_is_readonly_fixed_owner_and_active_only(recovery):
    _, records, _, update = recovery
    # The fixture owns this engine; production only obtains ports from composition.
    engine = records._engine
    candidates = bind_source_candidates("nexent-config", engine)
    try:
        result = candidates.query(
            DATASET, RecordQuery(), PageRequest(limit=100), context=context()
        )
        assert [row["file_id"] for row in result.items] == [FILE_ID]
        with pytest.raises(ScopeDenied):
            candidates.patch(
                DATASET,
                FILE_ID,
                FieldPatch(set_values={"version": 4}),
                context=context(),
            )
        for values in [
            {"upload_owner_service": "other"},
            {"delete_flag": "Y"},
            {"stage": "SOURCE_REVIEW"},
        ]:
            update(
                upload_owner_service="nexent-config",
                delete_flag="N",
                stage="SOURCE_UPLOAD",
            )
            update(**values)
            assert not candidates.query(
                DATASET, RecordQuery(), PageRequest(limit=100), context=context()
            ).items
    finally:
        candidates.close()


def test_root_releases_discovery_owner_when_query_fails(mocker):
    candidates = Mock()
    candidates.query.side_effect = Unavailable()
    owner = mocker.patch("management.services.file.source_recovery.source_candidate_ports")
    owner.return_value.__enter__.return_value = candidates
    with pytest.raises(Unavailable):
        reconcile_sources("nexent-config", context=context())
    owner.return_value.__exit__.assert_called_once()
    assert owner.return_value.__exit__.call_args.args[0] is Unavailable


@pytest.mark.asyncio
async def test_scheduler_retries_storage_failure_in_owned_lane_and_cancels():
    completed = asyncio.Event()
    calls = []

    async def execute(lane, spec, work):
        calls.append((lane, spec, work))
        if len(calls) == 1:
            raise Unavailable()
        completed.set()
        await asyncio.Event().wait()

    manager = type("Manager", (), {"run": AsyncMock(side_effect=execute)})()
    task = await schedule_source_reconciliation(
        "nexent-config", thread_manager=manager, interval_seconds=0.01
    )
    try:
        await asyncio.wait_for(completed.wait(), timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() and len(calls) == 2
    for lane, spec, _ in calls:
        assert lane == "file-upload" and spec.owner == "management.source-recovery"
        assert spec.pass_cancel_event and spec.deadline_monotonic is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [0, -1, True, float("nan"), 3601])
async def test_scheduler_rejects_unbounded_or_busy_loop_intervals(interval):
    with pytest.raises(ValueError):
        await schedule_source_reconciliation(
            "owner", thread_manager=object(), interval_seconds=interval
        )


def test_port_claims_exact_owner_tenant_state_and_revision(publication):
    from contracts.knowledge import INTERRUPTED_UPLOADS
    from nexent.storage.models import Revision

    from infrastructure.rdb.interrupted_uploads import bind_interrupted_uploads

    _, records, _, update = publication
    update(upload_owner_service="nexent-config")
    row = {"file_id": FILE_ID, "tenant_id": "tenant-a"}
    patch = FieldPatch(set_values={"status": "FAILED", "error_code": "CONTAINER_RESTARTED"})

    def attempt(owner="nexent-config", target=row, version="0"):
        port = bind_interrupted_uploads(owner, records._engine, record=target)
        try:
            return port.patch(INTERRUPTED_UPLOADS, FILE_ID, patch, expected=Revision(version), context=context())
        finally:
            port.close()

    assert not attempt(owner="nexent-northbound").matched
    assert not attempt(target={**row, "tenant_id": "tenant-b"}).matched
    assert not attempt(version="1").matched
    update(stage="SOURCE_UPLOAD", source_upload_sha256="f" * 64, file_size=12)
    assert not attempt().matched
    update(stage="UPLOAD", source_upload_sha256=None)
    assert attempt().revision == Revision("1")
    assert not attempt(version="1").matched
    with records._engine.connect() as conn:
        result = conn.execute(records._tables["knowledge_source_bindings"].select()).mappings().one()
    assert result["status"] == "FAILED" and result["updated_by"] == "user-a"


def test_restart_scan_advances_by_sort_key_when_claims_shrink_results(publication, monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime

    from management import recovery as startup
    from sqlalchemy import select

    from infrastructure.rdb.interrupted_uploads import bind_interrupted_uploads
    from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle

    _, records, _, update = publication
    engine = records._engine
    table = KnowledgeFileLifecycle.__table__
    now = datetime(2026, 9, 1)
    update(upload_owner_service="nexent-config", create_time=now, object_name=None)
    with engine.begin() as conn:
        conn.execute(table.insert(), [
            dict(file_id=f"row-{n:03d}", tenant_id="tenant-a", knowledge_id=1, index_name="kb",
                 original_filename="old.txt", status="UPLOADING", stage="UPLOAD",
                 upload_owner_service="nexent-config", create_time=now)
            for n in range(101)
        ])
        conn.execute(table.insert().values(file_id="other", tenant_id="tenant-a", knowledge_id=1, index_name="kb",
                      original_filename="other.txt", status="UPLOADING", upload_owner_service="nexent-northbound",
                      create_time=now))

    @contextmanager
    def ports(owner, *, record=None, expected_status="UPLOADING", context):
        port = bind_interrupted_uploads(owner, engine, record=record, expected_status=expected_status)
        try:
            yield port
        finally:
            port.close()

    monkeypatch.setattr(startup, "interrupted_upload_ports", ports)
    assert startup.fail_interrupted_uploads(now, "nexent-config") == 0
    assert startup.fail_interrupted_uploads(datetime(2026, 9, 2), "nexent-config") == 102
    with engine.connect() as conn:
        still_uploading = conn.execute(select(table.c.file_id).where(table.c.status == "UPLOADING")).scalars().all()
    assert still_uploading == ["other"]
