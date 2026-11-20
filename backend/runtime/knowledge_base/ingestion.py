# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute an authorized text ingestion attempt without publishing file visibility."""

import asyncio
import logging
import math
from dataclasses import dataclass
from threading import Lock

from contracts.agentos import EmbeddingInvocation
from contracts.agentos_knowledge import (
    CleanseArtifact,
    KnowledgeFileSourceDisplay,
    KnowledgeFileUpload,
)
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OperationCancelled,
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
from nexent.storage.objects import read_verified_object
from pydantic import ValidationError
from runtime.knowledge_base.chunking import chunk_text
from runtime.knowledge_base.image_ingestion import image_documents

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


def embedding_vectors(output, count, dimensions):
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
        self, objects, vectors, models, *, max_artifact_bytes, max_source_bytes, image_objects=None
    ):
        if any(
            type(value) is not int or value <= 0
            for value in (max_artifact_bytes, max_source_bytes)
        ):
            raise InvalidInput()
        self.objects, self.vectors, self.models = objects, vectors, models
        self.image_objects = image_objects
        self.max_artifact_bytes, self.max_source_bytes = (
            max_artifact_bytes,
            max_source_bytes,
        )
        self._write_lock = Lock()
        self._writes_open = True
        self._active_writes = 0
        self._unknown_write = False

    def stop_writes(self):
        """Prevent delayed callbacks from writing; report whether all writes are settled."""
        with self._write_lock:
            self._writes_open = False
            return not self._active_writes and not self._unknown_write

    def _upsert(self, rows, *, context):
        with self._write_lock:
            if not self._writes_open:
                raise OperationCancelled(operation_id=context.operation_id)
            context.remaining()
            self._active_writes += 1
        try:
            receipts = self.vectors.upsert(rows, context=context)
            if len(receipts) != len(rows) or any(
                receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched
                for receipt in receipts
            ):
                raise PartialFailure(
                    results=receipts, operation_id=context.operation_id
                )
            return receipts
        except PartialFailure as error:
            with self._write_lock:
                self._unknown_write |= len(error.results) != len(rows) or any(
                    receipt.outcome is WriteOutcome.UNKNOWN for receipt in error.results
                )
            raise
        except (
            InvalidInput,
            ScopeDenied,
            Conflict,
            NotFound,
            CapabilityUnsupported,
            DeadlineExceeded,
            OperationCancelled,
        ):
            raise
        except BaseException:
            with self._write_lock:
                self._unknown_write = True
            raise
        finally:
            with self._write_lock:
                self._active_writes -= 1

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

    async def _embeddings(self, batch, expected, actor, dimensions, *, context, input_batch_size):
        output = [None] * len(batch)
        for images in (False, True):
            selected = [(index, item) for index, item in enumerate(batch) if ("_image_input" in item) == images]
            if not selected:
                continue
            for start in range(0, len(selected), input_batch_size):
                group = selected[start : start + input_batch_size]
                result = await self._model(
                    self.models.invoke,
                    EmbeddingInvocation(model_id=expected.model_id, expected_revision=expected.revision,
                                        input=[item["_image_input"] if images else item["content"] for _, item in group],
                                        input_type="image" if images else "text"), actor, context=context,
                )
                if normalize_model_revision(result.revision) != normalize_model_revision(expected.revision):
                    raise Conflict()
                for (index, _), vector in zip(group, embedding_vectors(result.output, len(group), dimensions)):
                    output[index] = vector
        return output

    async def execute(
        self,
        request,
        *,
        actor,
        source,
        source_display,
        filename,
        collection,
        generation,
        context,
        max_characters=1536,
        new_after_n_chars=1024,
        batch_size=64,
        checkpoint=None,
        progress=None,
    ):
        if (
            not isinstance(request, KnowledgeFileUpload)
            or not isinstance(source_display, KnowledgeFileSourceDisplay)
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
        with self._write_lock:
            if not self._writes_open:
                raise OperationCancelled(operation_id=context.operation_id)
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
                read_verified_object,
                self.objects,
                ObjectRef(source.space, source.key, Revision(source.version)),
                sha256=source.sha256,
                limit=self.max_source_bytes,
                context=context,
            )

        def chunks(*, context):
            context.remaining()
            if not any(block.kind != "image" for block in artifact.blocks):
                return []
            return chunk_text(
                artifact,
                filename=filename,
                strategy=request.chunking_strategy,
                max_characters=max_characters,
                new_after_n_chars=new_after_n_chars,
                json_source=json_source,
            )

        documents = await self._blocking(chunks, context=context)
        if metadata.model_type == "multi_embedding":
            documents.extend(await self._blocking(image_documents, artifact, self.image_objects,
                                                   actor=actor, limit=self.max_source_bytes, context=context))
        keys = []
        if progress is not None:
            await progress(0, len(documents))
        for start in range(0, len(documents), batch_size):
            if checkpoint is not None:
                await checkpoint()
            batch = documents[start : start + batch_size]
            embeddings = await self._embeddings(
                batch, expected, actor, info.dimensions, context=context,
                input_batch_size=10 if metadata.model_type == "multi_embedding" else batch_size,
            )
            if checkpoint is not None:
                await checkpoint()
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
                        "media_kind": "image" if "_image_ref" in item else "text",
                        "content": item["content"],
                        "filename": filename,
                        "location": {
                            **{key: value for key, value in item.get("metadata", {}).items()
                               if key not in {'kind', 'image_ref', PUBLIC_CHUNK_SOURCE_KEY}},
                            **({"kind": "image", "image_ref": item["_image_ref"]} if "_image_ref" in item else {}),
                            **(
                                {"language": item["language"]}
                                if "language" in item
                                else {}
                            ),
                            'path_or_url': source.key,
                            'file_size': source_display.size_bytes,
                            'create_time': source_display.created_at,
                            'source_type': 'file',
                        },
                    },
                    generation,
                )
                for index, (item, embedding) in enumerate(zip(batch, embeddings))
            )
            await self._blocking(self._upsert, rows, context=context)
            keys.extend(row.key.key for row in rows)
            if progress is not None:
                await progress(len(keys), len(documents))
        return IngestedChunks(tuple(keys), expected.revision)

    def _artifact(self, request, source, *, context):
        reference = request.artifact
        content = read_verified_object(
            self.objects, ObjectRef(reference.space, reference.key, Revision(reference.version)),
            sha256=reference.sha256, limit=self.max_artifact_bytes, context=context,
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
        return artifact
