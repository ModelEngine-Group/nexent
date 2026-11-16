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


def test_root_closes_discovery_and_engine_when_query_fails(mocker):
    engine = Mock()
    candidates = Mock()
    candidates.query.side_effect = Unavailable()
    mocker.patch(
        "management.services.file.source_recovery.source_engine", return_value=engine
    )
    mocker.patch(
        "management.services.file.source_recovery.bind_source_candidates",
        return_value=candidates,
    )
    with pytest.raises(Unavailable):
        reconcile_sources("nexent-config", context=context())
    candidates.close.assert_called_once()
    engine.dispose.assert_called_once()


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
