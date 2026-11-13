# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from management.db.conversation import memory_completion as queue
from management.services.memory import prepared_completion as completion

JOB = queue.MemoryJob("a" * 32, queue.FINAL_ANSWER, 7, "b" * 32, 1, None)
SOURCE = queue.MemorySource("tenant-a", "user-a", 42, 81, "final answer", "original query")


@pytest.fixture
def worker(monkeypatch):
    async def inline(_name, fn, *args, lane, owner, **kwargs):
        return fn(*args, **kwargs)

    read = Mock(return_value=SOURCE)
    enabled = Mock(return_value=True)
    settle = Mock(return_value=True)
    checkpoint = Mock(return_value=True)
    extractor = SimpleNamespace(select_items=AsyncMock(return_value=["memo", "memo"]), store_item=AsyncMock())
    monkeypatch.setattr(completion, "run_blocking", inline)
    monkeypatch.setattr(queue, "read_source", read)
    monkeypatch.setattr(queue, "settle", settle)
    monkeypatch.setattr(queue, "checkpoint", checkpoint)
    monkeypatch.setattr(completion, "get_memory_switch", enabled)
    monkeypatch.setattr(completion, "build_memory_service_for_fa_extraction", Mock())
    monkeypatch.setattr(completion, "FaMemoryExtractor", Mock(return_value=extractor))
    monkeypatch.setattr(completion.tenant_config_manager, "get_app_config", Mock(return_value="11"))
    return SimpleNamespace(read=read, enabled=enabled, settle=settle, checkpoint=checkpoint, extractor=extractor)


@pytest.mark.asyncio
async def test_extracts_once_and_writes_only_after_checkpoint(worker):
    async def store(item):
        worker.checkpoint.assert_called_once_with(JOB, ["memo"])
        assert item == "memo"

    worker.extractor.store_item.side_effect = store
    await completion.process_memory_job(JOB)

    worker.extractor.select_items.assert_awaited_once_with("final answer", "original query")
    worker.extractor.store_item.assert_awaited_once_with("memo")
    worker.settle.assert_called_once_with(JOB, retry=False)


@pytest.mark.asyncio
async def test_lease_loss_before_checkpoint_prevents_store(worker):
    worker.checkpoint.return_value = False
    await completion.process_memory_job(JOB)
    worker.extractor.store_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_resumed_selection_skips_inference_and_requests_retry_on_failed_write(worker):
    job = replace(JOB, selected_items=["memo"], attempts=2)
    worker.extractor.store_item.side_effect = RuntimeError("offline")
    await completion.process_memory_job(job)
    worker.extractor.select_items.assert_not_awaited()
    worker.extractor.store_item.assert_awaited_once_with("memo")
    worker.settle.assert_called_once_with(job, retry=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_revoked_scope_or_switch_suppresses_work(worker, authorized):
    worker.read.return_value = SOURCE if authorized else None
    worker.enabled.return_value = False
    await completion.process_memory_job(JOB)
    worker.extractor.select_items.assert_not_awaited()
    worker.extractor.store_item.assert_not_awaited()
    worker.settle.assert_called_once_with(JOB, retry=False)


@pytest.mark.asyncio
async def test_turn_ingest_uses_committed_unit_ids_without_final_answer(worker, monkeypatch):
    job = replace(JOB, job_type=queue.TURN_COMPLETED)
    read = Mock(return_value=[
        {"unit_id": 11, "unit_index": 0, "unit_type": "tool", "unit_content": "tool content"},
        {"unit_id": 12, "unit_index": 1, "unit_type": "final_answer", "unit_content": "final answer"},
    ])
    ingest = AsyncMock(return_value=[])
    monkeypatch.setattr(completion, "get_units_by_message", read)
    monkeypatch.setattr(completion, "_build_ingestion_event_service",
                        lambda: SimpleNamespace(send_ingest_all_enabled=ingest))
    await completion.process_memory_job(job)

    read.assert_called_once_with(81)
    ingest.assert_awaited_once()
    args = ingest.await_args.kwargs
    assert (args["tenant_id"], args["user_id"], args["agent_id"], args["conversation_id"], args["event_id"]) == (
        "tenant-a", "user-a", "7", "42", "81",
    )
    unit, = args["units"]
    assert (unit.event_id, unit.unit_content) == ("11", "tool content")
    worker.settle.assert_called_once_with(job, retry=False)
