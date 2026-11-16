# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute an authorized text ingestion attempt without publishing file visibility."""

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass

from contracts.agentos import EmbeddingInvocation
from contracts.agentos_knowledge import CleanseArtifact, KnowledgeFileUpload
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    PartialFailure,
    ScopeDenied,
)
from nexent.storage.models import (
    ObjectRef,
    Revision,
    VectorKey,
    VectorRecord,
    WriteOutcome,
)
from pydantic import ValidationError
from runtime.knowledge_base.chunking import chunk_text

from infrastructure.agent_model_config import normalize_model_revision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestedChunks:
    """Confirmed physical writes; the job owner must separately publish visibility."""

    chunk_keys: tuple[str, ...]
    embedding_revision: str


def _scope(port, actor, namespace):
    scope = port.scope
    if (
        scope.system
        or scope.service_role != "runtime"
        or scope.tenant_id != actor.tenant_id
        or scope.actor_id != actor.user_id
        or namespace not in scope.namespaces
    ):
        raise ScopeDenied()


def _read(objects, reference, limit, context):
    context.remaining()
    ref = ObjectRef(reference.space, reference.key, Revision(reference.version))
    metadata = objects.stat(ref, context=context)
    if (
        metadata.ref != ref
        or type(metadata.size) is not int
        or not 0 <= metadata.size <= limit
        or metadata.sha256 not in {None, reference.sha256}
    ):
        raise InvalidInput()
    parts, size = [], 0
    with objects.open_read(ref, context=context) as stream:
        while True:
            context.remaining()
            part = stream.read(min(1024 * 1024, limit - size + 1))
            if not part:
                break
            size += len(part)
            if size > limit:
                raise InvalidInput()
            parts.append(part)
    context.remaining()
    content = b"".join(parts)
    if size != metadata.size or hashlib.sha256(content).hexdigest() != reference.sha256:
        raise InvalidInput()
    return content


def _embeddings(output, count, dimensions):
    if not isinstance(output, list) or len(output) != count:
        raise InvalidInput()
    vectors = []
    for values in output:
        if (
            not isinstance(values, list)
            or len(values) != dimensions
            or any(type(value) not in {int, float} for value in values)
        ):
            raise InvalidInput()
        try:
            vector = tuple(float(value) for value in values)
        except OverflowError as exc:
            raise InvalidInput() from exc
        if (
            not any(vector)
            or not all(math.isfinite(value) for value in vector)
            or not math.isfinite(sum(value * value for value in vector))
        ):
            raise InvalidInput()
        vectors.append(vector)
    return vectors


class KnowledgeIngestor:
    """Ports are owned by the calling attempt and closed by its composition root."""

    def __init__(
        self, objects, vectors, models, *, max_artifact_bytes, max_source_bytes
    ):
        if any(
            type(value) is not int or value <= 0
            for value in (max_artifact_bytes, max_source_bytes)
        ):
            raise InvalidInput()
        self.objects, self.vectors, self.models = objects, vectors, models
        self.max_artifact_bytes, self.max_source_bytes = (
            max_artifact_bytes,
            max_source_bytes,
        )

    async def _blocking(self, action, *args, context, **kwargs):
        context.remaining()
        result = await run_blocking(
            "knowledge-ingestion",
            action,
            *args,
            context=context,
            lane="control-io",
            owner="runtime.knowledge_base",
            **kwargs,
        )
        context.remaining()
        return result

    async def _model(self, method, *args, context):
        timeout = context.remaining()
        try:
            async with asyncio.timeout(timeout):
                result = await method(*args)
        except TimeoutError as exc:
            logger.warning(
                "knowledge_model_timeout operation_id=%s phase=model timeout_seconds=%s exception_type=%s",
                context.operation_id,
                timeout,
                type(exc).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from exc
        context.remaining()
        return result

    async def execute(
        self,
        request,
        *,
        actor,
        source,
        filename,
        collection,
        generation,
        context,
        max_characters=1536,
        new_after_n_chars=1024,
        batch_size=64,
    ):
        if (
            not isinstance(request, KnowledgeFileUpload)
            or not isinstance(generation, Revision)
            or not isinstance(filename, str)
            or not 1 <= len(filename) <= 1024
            or type(batch_size) is not int
            or not 1 <= batch_size <= 64
            or any(
                type(value) is not int or value < 1
                for value in (max_characters, new_after_n_chars)
            )
        ):
            raise InvalidInput()
        _scope(self.objects, actor, request.artifact.space)
        _scope(self.objects, actor, source.space)
        _scope(self.vectors, actor, collection)
        metadata = await self._model(
            self.models.get, request.embedding_model.model_id, actor, context=context
        )
        expected = request.embedding_model
        if (
            metadata.model_id != expected.model_id
            or metadata.model_type not in {"embedding", "multi_embedding"}
            or normalize_model_revision(metadata.revision)
            != normalize_model_revision(expected.revision)
        ):
            raise Conflict()
        info = await self._blocking(
            self.vectors.describe_collection, collection, context=context
        )
        if (
            info.collection != collection
            or type(info.dimensions) is not int
            or info.dimensions <= 0
        ):
            raise InvalidInput()
        artifact = await self._blocking(
            self._artifact,
            request,
            source,
            context=context,
        )
        json_source = None
        if filename.lower().endswith(".json"):
            json_source = await self._blocking(
                _read,
                self.objects,
                source,
                self.max_source_bytes,
                context=context,
            )

        def chunks(*, context):
            context.remaining()
            return chunk_text(
                artifact,
                filename=filename,
                strategy=request.chunking_strategy,
                max_characters=max_characters,
                new_after_n_chars=new_after_n_chars,
                json_source=json_source,
            )

        documents = await self._blocking(chunks, context=context)
        keys = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            result = await self._model(
                self.models.invoke,
                EmbeddingInvocation(
                    model_id=expected.model_id,
                    expected_revision=expected.revision,
                    input=[item["content"] for item in batch],
                ),
                actor,
                context=context,
            )
            if normalize_model_revision(result.revision) != normalize_model_revision(
                expected.revision
            ):
                raise Conflict()
            embeddings = _embeddings(result.output, len(batch), info.dimensions)
            rows = tuple(
                VectorRecord(
                    VectorKey(
                        collection,
                        f"{request.knowledge_id}/{request.file_id}/{request.file_version}/{start + index}",
                    ),
                    embedding,
                    {
                        "knowledge_id": request.knowledge_id,
                        "file_id": request.file_id,
                        "file_version": request.file_version,
                        "chunk_index": start + index,
                        "embedding_model_id": expected.model_id,
                        "embedding_revision": expected.revision,
                        "parser_version": request.parser_version,
                        "content": item["content"],
                        "filename": filename,
                        "location": {
                            **item.get("metadata", {}),
                            **(
                                {"language": item["language"]}
                                if "language" in item
                                else {}
                            ),
                        },
                    },
                    generation,
                )
                for index, (item, embedding) in enumerate(zip(batch, embeddings))
            )
            receipts = await self._blocking(self.vectors.upsert, rows, context=context)
            if len(receipts) != len(rows) or any(
                receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched
                for receipt in receipts
            ):
                raise PartialFailure(
                    results=receipts, operation_id=context.operation_id
                )
            keys.extend(row.key.key for row in rows)
        return IngestedChunks(tuple(keys), expected.revision)

    def _artifact(self, request, source, *, context):
        content = _read(
            self.objects, request.artifact, self.max_artifact_bytes, context
        )
        try:
            artifact = CleanseArtifact.model_validate_json(content)
        except ValidationError as exc:
            raise InvalidInput() from exc
        if (
            artifact.source != source
            or artifact.parser_version != request.parser_version
        ):
            raise InvalidInput()
        if any(block.kind == "image" for block in artifact.blocks):
            raise CapabilityUnsupported()
        return artifact
