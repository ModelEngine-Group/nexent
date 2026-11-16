# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lose an actual HTTP response while admission waits on an owned database lock."""

import asyncio

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeFileDelete
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure import agentos_client
from infrastructure.rdb.knowledge_jobs import files


async def check_lost_admission(api, engine, monkeypatch):
    entered, finished = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original = KnowledgeJobs.submit
    previous_deadline = agentos_client._KNOWLEDGE_DEADLINE_SECONDS
    payload = KnowledgeFileDelete(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=0,
        idempotency_key="lost-response-delete",
    )

    def observed(service, request, *, context):
        if getattr(request, "idempotency_key", None) != payload.idempotency_key:
            return original(service, request, context=context)
        loop.call_soon_threadsafe(entered.set)
        try:
            return original(service, request, context=context)
        finally:
            loop.call_soon_threadsafe(finished.set)

    connection = engine.connect()
    transaction = connection.begin()
    task = None
    try:
        # A lock without changing revision ensures the delayed CAS can still commit.
        connection.execute(sa.select(files.c.record_id).with_for_update()).scalar_one()
        monkeypatch.setattr(KnowledgeJobs, "submit", observed)
        monkeypatch.setattr(agentos_client, "_KNOWLEDGE_DEADLINE_SECONDS", 1.0)
        task = asyncio.create_task(
            api.delete_knowledge_file(payload, "user-a", "tenant-a")
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(RuntimeServiceTimeoutError):
            await asyncio.wait_for(task, timeout=2)
    finally:
        transaction.rollback()
        connection.close()
        monkeypatch.setattr(
            agentos_client, "_KNOWLEDGE_DEADLINE_SECONDS", previous_deadline
        )
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    try:
        await asyncio.wait_for(finished.wait(), timeout=3)
        first = await api.delete_knowledge_file(payload, "user-a", "tenant-a")
        second = await api.delete_knowledge_file(payload, "user-a", "tenant-a")
        assert first == second and first.status == "cleanup_pending"
        assert not first.physical_cleanup_complete
    finally:
        monkeypatch.setattr(KnowledgeJobs, "submit", original)
