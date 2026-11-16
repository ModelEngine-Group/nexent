# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual broker, KB admission and tenant output objects with a controlled parser."""

import hashlib

from contracts.agentos_knowledge import CleanseArtifact, ObjectReference
from contracts.knowledge_cleanse import KnowledgeCleanseLookup, KnowledgeCleanseRequest
from management.services.file.cleanse_executor import CleanseExecutor
from management.services.file.cleanse_worker import HANDLER
from management.services.file.knowledge_cleanse_service import KnowledgeCleanseService
from management.services.file.knowledge_cleanse_worker import consume_knowledge_once
from nexent.storage.errors import NotFound
from nexent.storage.models import ObjectRef, Revision, StorageScope, TaskEnvelope

from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.knowledge_cleanse import knowledge_cleanse_ports
from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


class Parser:
    def ensure_initialized(self):
        pass

    def file_process(self, *, file_data, filename, chunking_strategy):
        assert chunking_strategy == "none"
        return [{"content": file_data.decode("utf-8"), "metadata": {"page": 1}}], []


def check_execution(queue, row, context):
    with knowledge_cleanse_ports("tenant-a", "user-a", context=context()) as (
        _,
        resources,
    ):
        file = resources.get("cleanse_files", row["file_id"], context=context())
    request = KnowledgeCleanseRequest(
        knowledge_id=row["knowledge_id"],
        file_id=row["file_id"],
        file_version=row["source_generation"],
        filename=file["original_filename"],
        source=ObjectReference(
            space=row["source_space"],
            key=row["source_key"],
            version=row["source_revision"],
            sha256=row["source_sha256"],
        ),
        idempotency_key="production-worker",
    )
    api = KnowledgeCleanseService(parser_version="parser-v1")
    state = api.submit(
        request, tenant_id="tenant-a", user_id="user-a", context=context()
    )
    task = TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id})
    queue.enqueue(task, context=context())
    calls = []

    def execute(snapshot, request, *, tick, context):
        tick(context=context)
        objects = bind_cleanse_objects(
            "tenant-a", "user-a", request.source, context=context
        )
        executor = CleanseExecutor(
            runtime=Parser(), objects=objects, parser_version="parser-v1"
        )
        try:
            result = executor(snapshot, request, context=context)
            tick(context=context)
            calls.append(result)
            return result
        finally:
            executor.close()

    assert consume_knowledge_once(
        queue,
        owner_id="worker-proof",
        parser_version="parser-v1",
        execute=execute,
        lease_seconds=60,
        context=context(),
    )
    lookup = KnowledgeCleanseLookup(
        knowledge_id=request.knowledge_id,
        file_id=request.file_id,
        file_version=request.file_version,
        job_id=state.job_id,
    )
    completed = api.inspect(
        lookup, tenant_id="tenant-a", user_id="user-a", context=context()
    )
    assert completed.status == "completed" and completed.artifact == calls[0]
    queue.enqueue(task, context=context())
    assert consume_knowledge_once(
        queue,
        owner_id="worker-proof",
        parser_version="parser-v1",
        execute=execute,
        lease_seconds=60,
        context=context(),
    )
    assert len(calls) == 1
    environment = _configured_environment()
    for tenant in ("tenant-a", "tenant-b"):
        objects = S3ObjectStore(
            StorageScope("management", tenant, "proof", {"files"}),
            ObjectBinding(
                "files", environment.MINIO_DEFAULT_BUCKET, "", {"management"}
            ),
            _configured_client,
        )
        ref = ObjectRef(
            "files", completed.artifact.key, Revision(completed.artifact.version)
        )
        try:
            if tenant == "tenant-a":
                with objects.open_read(ref, context=context()) as stream:
                    data = stream.read()
                assert hashlib.sha256(data).hexdigest() == completed.artifact.sha256
                artifact = CleanseArtifact.model_validate_json(data)
                assert artifact.source == request.source and artifact.blocks[0].content
                assert artifact.blocks[0].location == {"page": 1}
            else:
                try:
                    objects.stat(ObjectRef(ref.space, ref.key), context=context())
                except NotFound:
                    pass
                else:
                    raise AssertionError("output object escaped its tenant partition")
        finally:
            objects.close()
