# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime ingestion and actual vector protocol with controlled model/object inputs."""

import asyncio
import hashlib
import io
from contextlib import contextmanager

from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    KnowledgeFileUpload,
    ObjectReference,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.models import (
    ObjectMetadata,
    ObjectRef,
    Revision,
    SearchQuery,
    StorageScope,
    VectorKey,
)
from runtime.knowledge_base.ingestion import KnowledgeIngestor
from runtime.model.service import ModelService

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_schema import VectorBinding
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def probe_ingestion(client_factory, ports, context):
    actor = ServicePrincipal("ingestion-proof", "tenant-a")
    source = ObjectReference(
        space="files",
        key="source",
        version="source-v1",
        sha256=hashlib.sha256(b"source").hexdigest(),
    )
    content = "Runtime owned ingestion"
    artifact = CleanseArtifact(
        source=source,
        parser_version="cleanse-v2",
        blocks=[
            CleanseBlock(
                ordinal=0,
                kind="text",
                content=content,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        ],
    )
    data = artifact.model_dump_json().encode()
    reference = ObjectReference(
        space="files",
        key="artifact",
        version="artifact-v1",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    streams, calls = [], []

    class Objects:
        scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"})

        def stat(self, ref, *, context):
            assert ref == ObjectRef("files", "artifact", Revision("artifact-v1"))
            return ObjectMetadata(
                ref, len(data), "application/json", sha256=reference.sha256
            )

        @contextmanager
        def open_read(self, ref, *, context):
            self.stat(ref, context=context)
            stream = io.BytesIO(data)
            streams.append(stream)
            try:
                yield stream
            finally:
                stream.close()

    class Adapter:
        async def invoke(self, request):
            calls.append(request.inputs)
            return [[1.0, 0.5] for _ in request.inputs]

    def load_record(model_id, tenant_id):
        assert model_id == 2 and tenant_id == actor.tenant_id
        return {
            "tenant_id": tenant_id,
            "delete_flag": "N",
            "model_type": "embedding",
            "update_time": "model-v1",
        }

    def build_adapter(record, modality, slot, tenant_id):
        assert modality == slot == "embedding" and tenant_id == actor.tenant_id
        return Adapter()

    fields = tuple(
        FieldDefinition(name, kind)
        for name, kind in (
            ("knowledge_id", "integer"),
            ("file_id", "string"),
            ("file_version", "integer"),
            ("chunk_index", "integer"),
            ("embedding_model_id", "integer"),
            ("embedding_revision", "string"),
            ("parser_version", "string"),
            ("content", "string"),
            ("filename", "string"),
            ("location", "object"),
        )
    )
    vectors = ElasticsearchVectorStore(
        StorageScope("runtime", actor.tenant_id, actor.user_id, {"ingest"}),
        (VectorBinding("ingest", "ingest-proof", 2, fields, writable=True),),
        client_factory,
    )
    ports.append(vectors)
    vectors.ensure_collection("ingest", context=context())
    service = KnowledgeIngestor(
        Objects(),
        vectors,
        ModelService(load_record, build_adapter),
        max_artifact_bytes=10000,
        max_source_bytes=10000,
    )
    payload = KnowledgeFileUpload(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=2,
        artifact=reference,
        parser_version="cleanse-v2",
        idempotency_key="ingest",
        embedding_model={"model_id": 2, "revision": "model-v1"},
        chunking_strategy="none",
    )

    async def execute():
        manager = ThreadManager(
            service_name="runtime-ingest-proof",
            lane_policies={
                "control-io": LanePolicy(
                    name="control-io",
                    max_workers=2,
                    max_queue_size=4,
                    queue_timeout_seconds=0,
                    cancel_grace_seconds=2,
                    shutdown_grace_seconds=5,
                ),
            },
        )
        manager.start()
        set_default_thread_manager(manager)
        try:
            first = await service.execute(
                payload,
                actor=actor,
                source=source,
                filename="source.txt",
                collection="ingest",
                generation=Revision("attempt-1"),
                context=context(),
            )
            second = await service.execute(
                payload,
                actor=actor,
                source=source,
                filename="source.txt",
                collection="ingest",
                generation=Revision("attempt-1"),
                context=context(),
            )
            assert first == second and len(first.chunk_keys) == 1
            return first
        finally:
            await manager.shutdown(timeout=5)
            clear_default_thread_manager(manager)

    result = asyncio.run(execute())
    assert calls == [[content], [content]] and all(stream.closed for stream in streams)
    assert vectors.count("ingest", None, context=context()) == 1
    record = vectors.get(VectorKey("ingest", result.chunk_keys[0]), context=context())
    assert record.payload["file_id"] == payload.file_id
    assert record.payload["embedding_revision"] == "model-v1"
    assert record.generation == Revision("attempt-1")
    hits = vectors.search(
        "ingest",
        SearchQuery(vector=(1.0, 0.5), fields=("content", "file_id")),
        context=context(),
    )
    assert len(hits) == 1 and hits[0].payload["content"] == content
    return {
        "runtime_model_service": True,
        "stable_chunk_keys": True,
        "physical_rows": 1,
        "model_input_controlled": True,
    }
