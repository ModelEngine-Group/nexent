# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual persistent coordination with signed HTTP and a deliberately lost reply."""

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_ingestion import KnowledgeIngestionIntent
from management.services.file.knowledge_cleanse_service import KnowledgeCleanseService
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCoordinator,
)
from management.services.knowledge_base.ingestion_dispatch import ingestion_lifespan
from nexent.core.concurrency import run_blocking

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_jobs import jobs


async def check_management_coordinator(
    api, engine, source, artifact, context, requests
):
    files = KnowledgeFileLifecycle.__table__
    value = KnowledgeIngestionIntent(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        user_id="user-a",
        attempt=1,
        source=source,
        filename="coordinated.txt",
        parser_version="v2",
        embedding_model={"model_id": 2, "revision": "model-v1"},
    )
    with engine.begin() as connection:
        connection.execute(
            files.insert().values(
                file_id=value.file_id,
                knowledge_id=1,
                tenant_id="tenant-a",
                index_name="kb-one",
                original_filename=value.filename,
                status="UPLOADED",
                stage="UPLOAD",
                delete_flag="N",
                source_generation=0,
                source_space=source.space,
                source_key=source.key,
                source_revision=source.version,
                source_sha256=source.sha256,
            )
        )

    def row():
        with engine.connect() as connection:
            return dict(
                connection.execute(
                    sa.select(files).where(files.c.file_id == value.file_id)
                )
                .mappings()
                .one()
            )

    class LoseReply:
        def __init__(self):
            self.uploads = 0
            self.inspect_ids = []
            self.discovered = asyncio.Event()

        async def get_model(self, *args, **kwargs):
            return await api.get_model(*args, **kwargs)

        async def upload_knowledge_file(self, payload, **kwargs):
            self.uploads += 1
            assert row()["stage"] == "RUNTIME_SUBMITTING"
            state = await api.upload_knowledge_file(payload, **kwargs)
            assert state.job_id == row()["forward_task_id"] and state.status == "queued"
            raise RuntimeServiceTimeoutError()

        async def inspect_knowledge_file(self, lookup, **kwargs):
            self.inspect_ids.append(lookup.job_id)
            result = await api.inspect_knowledge_file(lookup, **kwargs)
            if len(self.inspect_ids) == 2:
                self.discovered.set()
            return result

    actor = ServicePrincipal("user-a", "tenant-a")
    cleanse = KnowledgeCleanseService(parser_version="v2")
    transport = LoseReply()
    coordinator = IngestionCoordinator(cleanse, transport)
    assert (await coordinator.accept(value.file_id, actor, context=context()))[
        "stage"
    ] == "INGEST_ACCEPTED"
    assert row()["ingestion_request"] == value.model_dump(mode="json")
    assert (await coordinator.advance(value.file_id, actor, context=context()))[
        "stage"
    ] == "CLEANSE_PENDING"
    persisted = row()
    assert persisted["process_task_id"]

    def publish_cleanse():
        with cleanse._jobs(actor.tenant_id, actor.user_id, context()) as service:
            handle = service.claim(
                "controlled-parser",
                job_id=persisted["process_task_id"],
                lease_seconds=30,
                context=context(),
            )
            assert handle is not None and service.begin_execution(
                handle, context=context()
            )
            assert service.transition(
                handle, status="completed", artifact=artifact, context=context()
            )

    await run_blocking(
        "coordinator-publish-fixture", publish_cleanse, lane="control-io", owner="test"
    )
    try:
        await coordinator.advance(value.file_id, actor, context=context())
    except RuntimeServiceTimeoutError:
        pass
    else:
        raise AssertionError(
            "The controlled lost reply must reach the coordinator caller"
        )
    reserved = row()
    assert reserved["stage"] == "RUNTIME_SUBMITTING"
    # Discard the first coordinator and service; every next step reconstructs persisted identity.
    replacement = IngestionCoordinator(
        KnowledgeCleanseService(parser_version="v2"), transport
    )
    state = await replacement.advance(value.file_id, actor, context=context())
    assert (
        state["stage"] == "RUNTIME_PENDING"
        and state["forward_task_id"] == reserved["forward_task_id"]
    )
    app = SimpleNamespace(state=SimpleNamespace())
    async with ingestion_lifespan(app, enabled=True, coordinator=replacement):
        await asyncio.wait_for(transport.discovered.wait(), timeout=5)
        (task,) = app.state.required_background_tasks
        assert not task.done()
    assert task.done() and app.state.required_background_tasks == ()
    assert transport.uploads == 1
    assert transport.inspect_ids == [reserved["forward_task_id"]] * 2
    from contracts.agentos import ModelOperation
    from contracts.agentos_knowledge import KnowledgeOperation
    from contracts.constants import environment

    process_env = {
        **os.environ,
        "RUNTIME_SERVICE_URL": api.runtime_url,
        "POSTGRES_USER": "postgres",
        "NEXENT_POSTGRES_PASSWORD": "fixture-password",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(environment.POSTGRES_PORT),
        "POSTGRES_DB": "postgres",
        "JWT_SECRET": environment.JWT_SECRET,
        "NO_PROXY": "127.0.0.1,localhost",
    }
    before = len(requests)
    for _ in range(2):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("dispatch_process.py")),
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
            assert process.returncode == 0, stderr.decode(errors="replace")
            observed = json.loads(stdout.decode().splitlines()[-1])
            assert observed == [
                {
                    "file_id": value.file_id,
                    "stage": "RUNTIME_PENDING",
                    "job_id": reserved["forward_task_id"],
                }
            ]
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.communicate(), timeout=5)
    calls = Counter(requests[before:])
    assert (
        sum(
            count
            for path, count in calls.items()
            if path.endswith(ModelOperation.GET.value)
        )
        == 2
    )
    assert (
        sum(
            count
            for path, count in calls.items()
            if path.endswith(KnowledgeOperation.INSPECT.value)
        )
        == 2
    )
    assert (
        sum(
            count
            for path, count in calls.items()
            if path.endswith(KnowledgeOperation.UPLOAD.value)
        )
        == 0
    )
    with engine.connect() as connection:
        rows = (
            connection.execute(sa.select(jobs).where(jobs.c.file_id == value.file_id))
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert (
            rows[0]["job_id"] == reserved["forward_task_id"]
            and rows[0]["status"] == "queued"
        )
