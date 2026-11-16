# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Observe production delete discovery and physical version/scope preservation."""

import asyncio
from time import monotonic

from contracts.agentos_knowledge import KnowledgeFileDelete, KnowledgeJobLookup
from nexent.storage.models import (
    Comparison,
    OperationContext,
    Revision,
    VectorKey,
    VectorRecord,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_vectors import bind_knowledge_vectors


def context():
    return OperationContext("delete-probe", monotonic() + 15)


async def prove_deletion(api, actor, request, vectors, original, workers, db, owned, calls):
    other = bind_knowledge_vectors(ServicePrincipal("user-b", "tenant-b"), "kb-worker", 2)
    owned.append(other)
    await db(other.ensure_collection, "kb-worker", context=context())
    await db(vectors.upsert, (
        VectorRecord(VectorKey("kb-worker", "new-version"), (1.0, 0.5),
                     {**original.payload, "file_version": 1}, generation=Revision("new")),
        VectorRecord(VectorKey("kb-worker", "other-file"), (1.0, 0.5),
                     {**original.payload, "file_id": "c" * 32}, generation=Revision("other")),
    ), context=context())
    await db(other.upsert, (
        VectorRecord(VectorKey("kb-worker", "same-file-other-tenant"), (1.0, 0.5),
                     original.payload, generation=Revision("other-tenant")),
    ), context=context())
    deleting = await api.delete(KnowledgeFileDelete(
        **request.model_dump(include={"knowledge_id", "file_id", "file_version"}),
        idempotency_key="physical-delete",
    ), actor)
    lookup = KnowledgeJobLookup(**deleting.model_dump(include={"knowledge_id", "file_id", "file_version", "job_id"}))
    async with asyncio.timeout(15):
        while True:
            final = await api.inspect(lookup, actor)
            if final.status == "deleted":
                break
            await asyncio.sleep(0.02)
    assert final.physical_cleanup_complete
    assert await db(vectors.get, original.key, context=context()) is None
    assert (await db(vectors.get, VectorKey("kb-worker", "new-version"), context=context())).payload["file_version"] == 1
    assert (await db(vectors.get, VectorKey("kb-worker", "other-file"), context=context())).payload["file_id"] == "c" * 32
    assert await db(other.count, "kb-worker", None, context=context()) == 1
    assert await db(vectors.count, "kb-worker", Comparison("file_version", "eq", 0), context=context()) == 1
    assert len(calls) == 1
    assert await workers["delete"].process(lookup, actor, owner_id="duplicate") == final
    assert len(calls) == 1
    return {"physical_cleanup": True, "newer_version_preserved": True,
            "other_scope_preserved": True, "delete_without_model": True}
