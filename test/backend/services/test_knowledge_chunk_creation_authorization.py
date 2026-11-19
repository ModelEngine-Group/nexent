# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public creation keeps real Management SI authorization before any Runtime request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge import ChunkCreateRequest, ChunkUpdateRequest
from management.services.knowledge_base.chunk_creation import create_manual_chunk
from management.services.knowledge_base.chunk_update import update_manual_chunk
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import DeadlineExceeded, ScopeDenied, Unavailable

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_file_reader import (
    reader as reader,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture(autouse=True)
def database_threads(sqlite_threads):
    """Construct the controlled SQLite provider before its first managed worker call."""


@pytest.fixture
async def client():
    manager = ThreadManager(service_name="public-create-auth-ut", lane_policies={
        "control-io": LanePolicy("control-io", 1, 4, queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=3)})
    manager.start()
    set_default_thread_manager(manager)
    try:
        yield SimpleNamespace(inspect_knowledge_chunk=AsyncMock(), mutate_knowledge_chunk=AsyncMock())
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids


@pytest.fixture(params=["create", "update"])
def public_write(request):
    async def invoke(index_name, actor, *, reader, client):
        if request.param == "create":
            return await create_manual_chunk(index_name, ChunkCreateRequest(content="body"), actor, reader=reader, client=client)
        return await update_manual_chunk(index_name, "manual", ChunkUpdateRequest(content="body"), actor, reader=reader, client=client)
    return invoke


@pytest.mark.parametrize("changes", [
    {"created_by": "other", "ingroup_permission": "READ_ONLY"},
    {"created_by": "other", "ingroup_permission": "PRIVATE"},
    {"deletion_request": {"scope": "full"}},
    {"knowledge_sources": "datamate"},
])
async def test_unauthorized_or_closed_resource_prevents_all_runtime_requests(reader, client, changes, public_write):
    reader.update("cleanse_knowledge", **changes)
    with pytest.raises(ScopeDenied):
        await public_write("kb-one", reader.actor,
                                  reader=reader.service, client=client)
    client.inspect_knowledge_chunk.assert_not_awaited()
    client.mutate_knowledge_chunk.assert_not_awaited()


async def test_shared_read_does_not_grant_create_permission(reader, client, public_write):
    with pytest.raises(ScopeDenied):
        await public_write("shared", reader.actor,
                                  reader=reader.service, client=client)
    client.inspect_knowledge_chunk.assert_not_awaited()


@pytest.mark.parametrize("failure", [Unavailable(), DeadlineExceeded()])
async def test_resource_failures_never_become_plaintext_writes(reader, client, monkeypatch, failure, public_write):
    monkeypatch.setattr(reader.service, "knowledge", Mock(side_effect=failure))
    with pytest.raises(type(failure)):
        await public_write("kb-one", reader.actor,
                                  reader=reader.service, client=client)
    client.inspect_knowledge_chunk.assert_not_awaited()
