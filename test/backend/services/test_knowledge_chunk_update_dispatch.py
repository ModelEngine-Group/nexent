# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit update dimensions reach the existing maintenance binding through AgentOS service."""

from contextlib import contextmanager

from nexent.storage.models import DeleteReceipt, VectorKey, VectorRecord, WriteReceipt
from runtime.knowledge_base.chunk_view import ChunkReadView

from test.backend.services.test_knowledge_chunk_write_service import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    write as write,  # noqa: PLC0414
)


async def test_service_passes_only_explicit_dimensions_and_never_invokes_a_model(write):
    s = write
    await s.service.mutate(s.s.value, s.s.s.actor)
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(update={"operation": "update"})
    opened = []

    @contextmanager
    def maintenance(actor, collection, *, dimensions, context):
        assert actor == s.s.s.actor and collection == "collection"
        opened.append(dimensions)
        yield s.s.vectors

    s.service.maintenance_ports = maintenance
    s.s.vectors.put.return_value = WriteReceipt("put", True)
    result = await s.service.mutate(s.s.value.model_copy(update={"operation": "update", "request_key": "update",
        "changes": {"embedding": [0, 1, 0], "content": "changed"}}), s.s.s.actor)
    assert result.status == "completed" and result.count_delta == 0 and opened == [3]
    assert s.s.stored[0].vector == (0, 1, 0) and s.s.stored[0].payload["content"] == "changed"
    s.s.models.invoke.assert_not_awaited()


async def test_native_legacy_delete_uses_revision_without_affecting_managed_chunk_history(write):
    s = write
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(update={"operation": "delete"})
    opened = []

    @contextmanager
    def native(actor, grant, *, storage_revision, context):
        assert actor == s.s.s.actor and grant.collection == "collection"
        opened.append(storage_revision)
        yield s.s.vectors

    s.service.native_port = native
    s.s.vectors.get.side_effect = None
    s.s.vectors.get.return_value = VectorRecord(VectorKey("collection", "manual"), (), {"knowledge_id": 1}, None)
    s.s.vectors.delete_key.return_value = DeleteReceipt("native-delete", True)
    payload = s.s.value.model_copy(update={"operation": "delete", "request_key": "native-delete",
        "native_documents": True, "storage_revision": "b" * 64, "changes": {}})
    result = await s.service.mutate(payload, s.s.s.actor)
    assert result.status == "completed" and result.count_delta == -1 and opened == ["b" * 64]
    assert await s.service.mutate(payload, s.s.s.actor) == result
    s.s.vectors.delete_key.assert_called_once()

    def count(*, context):
        return ChunkReadView(s.s.s.mutation_records, 1, context=context).standalone_count(context=context)

    from test.backend.services.test_knowledge_chunk_creation import context
    assert await s.s.db(count, context=context()) == 0
