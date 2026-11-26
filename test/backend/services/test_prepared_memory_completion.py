# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from management.db.conversation import memory_completion as queue
from management.services.memory import prepared_completion as completion

JOB = queue.MemoryJob("a" * 32, queue.FINAL_ANSWER, 7, "b" * 32, 1, None)
SOURCE = queue.MemorySource("tenant-a", "user-a", 42, 81, "final answer", "original query", 1)


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
    monkeypatch.setattr(completion, "can_write_automatic_memory", enabled)
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
    completion.build_memory_service_for_fa_extraction.assert_called_once_with(agent_version_no=1)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", [queue.FINAL_ANSWER, queue.TURN_COMPLETED])
async def test_configuration_read_failure_retries_instead_of_finishing(worker, monkeypatch, job_type):
    from management.services.memory import access

    error = RuntimeError("configuration database unavailable")
    monkeypatch.setattr(access, "get_user_configs", Mock(side_effect=error))
    monkeypatch.setattr(completion, "can_write_automatic_memory", access.can_write_automatic_memory)
    ingest = AsyncMock()
    monkeypatch.setattr(completion, "_ingest_turn", ingest)
    job = replace(JOB, job_type=job_type)
    await completion.process_memory_job(job)
    worker.extractor.select_items.assert_not_awaited()
    ingest.assert_not_awaited()
    worker.settle.assert_called_once_with(job, retry=True)
    # A recovered configuration must make the same persisted work eligible again.
    access.get_user_configs.side_effect = None
    access.get_user_configs.return_value = {"MEMORY_SWITCH": "Y"}
    monkeypatch.setattr(access, "tenant_memory_enabled", Mock(return_value=True))
    monkeypatch.setattr(access, "source_agent_allows_memory", Mock(return_value=True))
    worker.settle.reset_mock()
    retried = replace(job, attempts=2)
    await completion.process_memory_job(retried)
    worker.settle.assert_called_once_with(retried, retry=False)
    assert worker.extractor.store_item.await_count == int(job_type == queue.FINAL_ANSWER)
    assert ingest.await_count == int(job_type == queue.TURN_COMPLETED)


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", [queue.FINAL_ANSWER, queue.TURN_COMPLETED])
@pytest.mark.parametrize("executed_version", [0, 1])
@pytest.mark.parametrize("executed_enabled", [False, True])
async def test_later_publication_does_not_replace_executed_memory_policy(
    worker, monkeypatch, executed_version, executed_enabled, job_type,
):
    from management.services.memory import access

    source = SimpleNamespace(**{**vars(SOURCE), "agent_version_no": executed_version})
    worker.read.return_value = source
    monkeypatch.setattr(access, "get_user_configs", Mock(return_value={"MEMORY_SWITCH": "Y"}))
    monkeypatch.setattr(access, "tenant_memory_enabled", Mock(return_value=True))
    published = Mock(return_value=2)
    monkeypatch.setattr(access, "query_current_version_no", published)
    lookup = Mock(side_effect=lambda _id, _tenant, version: {
        "enable_memory": executed_enabled if version == executed_version else not executed_enabled,
    })
    monkeypatch.setattr(access, "search_agent_info_by_agent_id", lookup)
    monkeypatch.setattr(completion, "can_write_automatic_memory", access.can_write_automatic_memory)
    ingest = AsyncMock()
    monkeypatch.setattr(completion, "_ingest_turn", ingest)
    job = replace(JOB, job_type=job_type)
    await completion.process_memory_job(job)
    lookup.assert_called_once_with(7, "tenant-a", executed_version)
    published.assert_not_called()
    assert worker.extractor.store_item.await_count == int(executed_enabled and job_type == queue.FINAL_ANSWER)
    assert ingest.await_count == int(executed_enabled and job_type == queue.TURN_COMPLETED)
    worker.settle.assert_called_once_with(job, retry=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [0, 1])
async def test_fa_facade_forwards_executed_version_to_backend(monkeypatch, version):
    from management.services.memory import provider

    store = AsyncMock(return_value={"memory_id": 19, "event": "ADD"})
    monkeypatch.setattr(provider, "_backend_store_hook", store)
    service = provider.build_memory_service_for_fa_extraction(agent_version_no=version)
    result = await service.store_memory(content="memo", tenant_id="tenant", user_id="user", agent_id="7")
    assert result.memory_id == "19"
    store.assert_awaited_once()
    payload = store.await_args.args[0]
    assert (payload["agent_id"], payload["agent_version_no"], payload["content"]) == ("7", version, "memo")
