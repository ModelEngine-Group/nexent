# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only, editor-scoped evidence for vectors lacking a recognized media kind."""

import argparse
import asyncio
import json
import os
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeChunksGrant, KnowledgeContentRequest
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionAuthorization,
    KnowledgeCollectionGrant,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import Comparison, Junction, OperationContext, PageRequest
from pydantic import ValidationError
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.data_revision import knowledge_data_revision
from runtime.knowledge_base.publication import published_files, published_job

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_runtime import knowledge_chunks_ports


def _evidence(record, resource, manifests, jobs, view, *, context):
    data = record.payload
    if record.key.collection != resource.collection or data.get("knowledge_id") != resource.knowledge_id:
        raise ScopeDenied()
    generation = record.generation.value if record.generation else None
    file_id, version, index = (data.get(field) for field in ("file_id", "file_version", "chunk_index"))
    if file_id is None:
        return "STANDALONE_PROVENANCE_UNAVAILABLE", None
    manifest = manifests.get(file_id)
    if manifest is None or (version, generation) != (manifest["visible_version"], manifest["visible_generation"]):
        return "NO_CURRENT_FILE_PUBLICATION", None
    if view.has_confirmed_mutation(record, context=context):
        return "CHUNK_HAS_MUTATION", None
    if file_id not in jobs:
        jobs[file_id] = published_job(view.records, resource, manifest, context=context)
    job = jobs[file_id]
    if (type(index) is not int or not 0 <= index < job["chunk_count"] or not data.get("parser_version")
        or record.key.key != f"{resource.knowledge_id}/{file_id}/{version}/{index}"):
        return "UNPROVEN_INGESTION_ORIGIN", None
    location = data.get("location", {})
    if "kind" not in location and "image_ref" not in location:
        return "CONFIRMED_INGESTED_TEXT", None
    if location.get("kind") != "image":
        return "UNPROVEN_IMAGE", None
    try:
        request = KnowledgeContentRequest(knowledge_id=resource.knowledge_id, file_id=file_id, file_version=version,
                                          image_ref=location["image_ref"])
        if request.image_ref is not None:
            return "PENDING_IMAGE_MANIFEST", request
    except (KeyError, ValidationError):
        pass
    return "UNPROVEN_IMAGE", None


def _page(vectors, resource, cursor, page_size, *, context):
    unknown = Junction("or", (
        Comparison("media_kind", "is_null", True),
        Junction("and", (Comparison("media_kind", "ne", "text"), Comparison("media_kind", "ne", "image"))),
    ))
    return vectors.scan(resource.collection, Junction("and", (
        Comparison("knowledge_id", "eq", resource.knowledge_id), unknown,
    )), PageRequest(limit=page_size, cursor=cursor), context=context, include_vector=False, vectors_only=True)


async def inspect_media(client, actor, knowledge_id, emit, *, context, page_size=100, ports=knowledge_chunks_ports):
    async def blocking(action):
        return await run_blocking("inspect-vector-media", action, lane="control-io", owner=__name__)

    async def authorize():
        result = await client.authorize_knowledge_collection(
            KnowledgeCollectionAuthorization(knowledge_id=knowledge_id), actor.user_id, actor.tenant_id)
        if (not isinstance(result, KnowledgeCollectionGrant) or result.knowledge_id != knowledge_id
            or result.resource_tenant_id != actor.tenant_id):
            raise ScopeDenied()
        return result

    async def check_image(request):
        try:
            grant = await client.authorize_knowledge_content(request, actor.user_id, actor.tenant_id)
        except RuntimeUpstreamError as error:
            if error.status_code in {403, 404, 409}:
                return "UNPROVEN_IMAGE"
            raise
        if (grant.knowledge_id, grant.file_id, grant.file_version, grant.object_ref) != (
            request.knowledge_id, request.file_id, request.file_version, request.image_ref):
            raise ScopeDenied()
        return "CONFIRMED_MANIFEST_IMAGE"

    async with asyncio.timeout(context.remaining()):
        grant = await authorize()
        resource = KnowledgeChunksGrant.model_validate(grant.model_dump(exclude={"embedding_model_id"}))
        counts, jobs, cursor = {}, {}, None
        with ports(actor, resource, context=context) as (records, vectors):
            for port in (records, vectors):
                scope = port.scope
                if (scope.system or scope.resource_prefix or scope.service_role != "runtime"
                    or scope.tenant_id != actor.tenant_id or scope.actor_id != actor.user_id):
                    raise ScopeDenied()
            if vectors.scope.namespaces != {resource.collection}:
                raise ScopeDenied()
            def snapshot():
                return (
                    knowledge_data_revision(records, knowledge_id, context=context),
                    {row["file_id"]: row for row in published_files(records, knowledge_id, context=context)},
                    ChunkReadView(records, knowledge_id, context=context),
                    vectors.collection_exists(resource.collection, context=context),
                )

            revision, manifests, view, present = await blocking(snapshot)

            def scan_page():
                page = _page(vectors, resource, cursor, page_size, context=context)
                findings = [(row, *_evidence(row, resource, manifests, jobs, view, context=context)) for row in page.items]
                return findings, page.next_cursor

            while present:
                findings, next_cursor = await blocking(scan_page)
                if await authorize() != grant:
                    raise Conflict()
                for row, reason, image in findings:
                    context.remaining()
                    if image is not None:
                        reason = await check_image(image)
                    counts[reason] = counts.get(reason, 0) + 1
                    emit({"kind": "vector", "chunk_id": row.key.key, "file_id": row.payload.get("file_id"),
                          "file_version": row.payload.get("file_version"),
                          "generation": row.generation.value if row.generation else None, "reason": reason})
                if next_cursor is None:
                    break
                if next_cursor == cursor:
                    raise Conflict()
                cursor = next_cursor
            if await authorize() != grant:
                raise Conflict()
            current = await blocking(lambda: knowledge_data_revision(records, knowledge_id, context=context))
            if current != revision:
                raise Conflict()
        context.remaining()
        return {"kind": "finished", "collection_present": present, "knowledge_revision": grant.revision,
                "data_revision": revision, "counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-id", type=int, required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.knowledge_id < 1 or not 1 <= args.timeout <= 3600:
        parser.error("Expected a positive knowledge ID and a timeout from 1 to 3600 seconds")
    context = OperationContext("knowledge-vector-media-" + uuid4().hex, monotonic() + args.timeout)
    actor = ServicePrincipal(args.user_id, args.tenant_id)
    client = AgentOSClient(environment.MANAGEMENT_AGENTOS_URL, create_httpx_client)

    async def run(emit):
        manager = ThreadManager(service_name="runtime-media-inspection",
                                lane_policies={"control-io": LanePolicy("control-io", 1, 0)})
        manager.start()
        set_default_thread_manager(manager)
        try:
            return await inspect_media(client, actor, args.knowledge_id, emit, context=context)
        finally:
            clear_default_thread_manager(manager)
            if (await manager.shutdown(timeout=15)).stuck_execution_ids:
                raise DeadlineExceeded(operation_id=context.operation_id)

    try:
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            def emit(value):
                stream.write(json.dumps(value) + "\n")
                stream.flush()

            emit({"kind": "start", "knowledge_id": args.knowledge_id, "user_id": actor.user_id, "tenant_id": actor.tenant_id})
            emit(asyncio.run(run(emit)))
    except (TimeoutError, DeadlineExceeded):
        parser.exit(1, "Vector media inspection deadline exceeded\n")
    except Exception as error:  # noqa: BLE001 - Do not print raw provider errors or references.
        parser.exit(1, f"Vector media inspection failed: {type(error).__name__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
