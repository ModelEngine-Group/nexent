# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit update dimensions reach the existing maintenance binding through AgentOS service."""

from contextlib import contextmanager

from nexent.storage.models import WriteReceipt

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
