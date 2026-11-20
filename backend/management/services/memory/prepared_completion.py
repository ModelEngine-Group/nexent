# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deliver recoverable Memory work from Management's committed projection."""

import asyncio
import logging

from contracts.constants.constants import MODEL_CONFIG_MAPPING
from management.db.conversation import memory_completion as queue
from management.db.conversation.repository import get_units_by_message
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.configuration.user.memory import get_memory_switch
from management.services.memory.extraction import AgentOSMemoryExtractionModel, FaMemoryExtractor
from management.services.memory.provider import _build_ingestion_event_service, build_memory_service_for_fa_extraction
from nexent.core.concurrency import run_blocking
from nexent.memory.models import MemoryIngestUnit

logger = logging.getLogger(__name__)


async def _io(name, fn, *args, **kwargs):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management.memory", **kwargs)


async def _ingest_turn(job, source):
    units = await _io("memory-completion-units", get_units_by_message, source.message_id)
    events = [
        MemoryIngestUnit(
            event_id=str(unit["unit_id"]), event_type=queue.TURN_COMPLETED, unit_type=unit["unit_type"],
            unit_content=unit["unit_content"], unit_index=unit["unit_index"],
        )
        for unit in units if unit["unit_type"] != queue.FINAL_ANSWER
    ]
    if not events:
        return
    results = await _build_ingestion_event_service().send_ingest_all_enabled(
        tenant_id=source.tenant_id, user_id=source.user_id, agent_id=str(job.agent_id),
        conversation_id=str(source.conversation_id), event_type=queue.TURN_COMPLETED,
        event_id=str(source.message_id), units=events,
    )
    if any(result.status == "error" for result in results):
        raise RuntimeError("An external Memory provider failed to ingest the completed turn")


async def _extract_answer(job, source):
    items = job.selected_items
    extractor = FaMemoryExtractor(
        tenant_id=source.tenant_id, user_id=source.user_id, agent_id=str(job.agent_id),
        conversation_id=str(source.conversation_id), memory_service=build_memory_service_for_fa_extraction(),
    )
    if items is None:
        model_id = await _io(
            "memory-completion-model", tenant_config_manager.get_app_config,
            key=MODEL_CONFIG_MAPPING["llm"], tenant_id=source.tenant_id,
        )
        if not model_id:
            return
        extractor.model_client = AgentOSMemoryExtractionModel(int(model_id), source.user_id, source.tenant_id)
        items = list(dict.fromkeys(await extractor.select_items(source.answer, source.query)))
        if not await _io("memory-completion-checkpoint", queue.checkpoint, job, items):
            return
    for item in items:
        await extractor.store_item(item)


async def process_memory_job(job):
    retry = False
    try:
        async with asyncio.timeout(240):
            source = await _io("memory-completion-source", queue.read_source, job)
            if source is not None and await _io("memory-completion-switch", get_memory_switch, source.user_id):
                if job.job_type == queue.TURN_COMPLETED:
                    await _ingest_turn(job, source)
                else:
                    await _extract_answer(job, source)
    except Exception as exc:
        retry = True
        logger.warning("Memory completion failed run_id=%s type=%s attempt=%s error=%s",
                       job.run_id, job.job_type, job.attempts, type(exc).__name__)
    await _io("memory-completion-settle", queue.settle, job, retry=retry)


async def recover_memory_jobs():
    while True:
        try:
            job = await _io("memory-completion-claim", queue.claim)
            if job is not None:
                await process_memory_job(job)
                continue
        except Exception as exc:
            logger.warning("Unable to recover Memory completion jobs error=%s", type(exc).__name__)
        await asyncio.sleep(3)
