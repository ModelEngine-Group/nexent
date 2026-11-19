# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SOURCES-01/02 prove strict sources and real managed read ownership."""

import asyncio
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos_knowledge import KnowledgeChunksGrant
from contracts.knowledge_sources import KnowledgeSources, KnowledgeSourcesResult
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied, Unavailable
from nexent.storage.models import OperationContext, StorageScope, VectorGroup
from pydantic import ValidationError
from runtime.knowledge_base.sources import KnowledgeSourcesService

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
async def boundary():
    actor = ServicePrincipal("reader", "tenant-a")
    grant = KnowledgeChunksGrant(
        knowledge_id=1,
        collection="kb",
        resource_tenant_id="tenant-a",
        revision="a" * 64,
    )
    client = SimpleNamespace(authorize_knowledge_chunks=AsyncMock(return_value=grant))
    vectors = SimpleNamespace(
        scope=StorageScope("runtime", "tenant-a", "reader", {"kb"}),
        collection_exists=Mock(return_value=True),
        group=Mock(
            return_value=(
                VectorGroup(
                    "kb",
                    "one",
                    3,
                    {
                        "path": "one",
                        "filename": ["raw", None],
                        "size": 9,
                        "created": None,
                    },
                ),
            )
        ),
    )
    opened, closed, contexts = [], [], []

    @contextmanager
    def ports(principal, resource, *, context):
        assert principal == actor
        opened.append(resource)
        contexts.append(context)
        try:
            yield vectors
        finally:
            closed.append(True)

    manager = ThreadManager(
        service_name="sources-unit",
        lane_policies={"control-io": LanePolicy("control-io", 1, 8)},
    )
    manager.start()
    set_default_thread_manager(manager)
    service = KnowledgeSourcesService(client, ports=ports)
    request = KnowledgeSources(knowledge_id=1, expected_revision="a" * 64, limit=2)
    try:
        yield SimpleNamespace(**locals())
    finally:
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids
        clear_default_thread_manager(manager)


async def test_read_keeps_json_metadata_two_grants_and_no_body_or_model(boundary):
    s = boundary
    result = await s.service.list_sources(s.request, s.actor)
    assert result.present and result.knowledge_id == 1 and result.revision == "a" * 64
    assert result.sources[0].model_dump() == {
        "source_key": "one",
        "path_or_url": "one",
        "filename": ["raw", None],
        "file_size": 9,
        "create_time": None,
        "chunk_count": 3,
    }
    assert s.client.authorize_knowledge_chunks.await_count == 2 and s.closed == [True]
    call = s.vectors.group.call_args
    assert call.args[0] == "kb" and call.args[1].limit == 2
    assert {f.name for f in call.args[1].sample_fields} == {
        "path",
        "filename",
        "size",
        "created",
    }
    assert (
        call.kwargs["where"].field == "knowledge_id" and call.kwargs["where"].value == 1
    )
    assert s.contexts[0].cancelled.is_set()


async def test_missing_collection_is_empty_without_group_query(boundary):
    s = boundary
    s.vectors.collection_exists.return_value = False
    result = await s.service.list_sources(s.request, s.actor)
    assert (
        not result.present
        and result.sources == []
        and s.client.authorize_knowledge_chunks.await_count == 2
    )
    s.vectors.group.assert_not_called()


async def test_stale_resource_never_opens_provider(boundary):
    s = boundary
    with pytest.raises(Conflict):
        await s.service.list_sources(
            s.request.model_copy(update={"expected_revision": "b" * 64}), s.actor
        )
    assert not s.opened


async def test_revoked_read_or_changed_revision_never_returns_snapshot(boundary):
    s = boundary
    s.client.authorize_knowledge_chunks.side_effect = [s.grant, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await s.service.list_sources(s.request, s.actor)
    assert s.closed == [True]
    s.client.authorize_knowledge_chunks.side_effect = [
        s.grant,
        s.grant.model_copy(update={"revision": "b" * 64}),
    ]
    with pytest.raises(Conflict):
        await s.service.list_sources(s.request, s.actor)


@pytest.mark.parametrize("failure", ["storage", "scope", "invalid-result"])
async def test_failures_do_not_become_empty_success(boundary, failure):
    s = boundary
    if failure == "storage":
        s.vectors.group.side_effect = Unavailable()
    elif failure == "scope":
        s.vectors.scope = StorageScope("runtime", "foreign", "reader", {"kb"})
    else:
        s.vectors.group.return_value = (
            VectorGroup("kb", "one", True, {"path": "one"}),
        )
    with pytest.raises(ScopeDenied if failure == "scope" else Unavailable):
        await s.service.list_sources(s.request, s.actor)
    assert s.closed == [True]


async def test_shared_resource_keeps_original_reader(boundary):
    s = boundary
    s.client.authorize_knowledge_chunks.return_value = s.grant.model_copy(
        update={"resource_tenant_id": "asset_owner_tenant_id"}
    )
    s.vectors.scope = StorageScope("runtime", "asset_owner_tenant_id", "reader", {"kb"})
    assert (await s.service.list_sources(s.request, s.actor)).present
    assert s.client.authorize_knowledge_chunks.await_args.args[1:] == (
        "reader",
        "tenant-a",
    )


async def test_total_authorization_deadline_is_one_warning(boundary, caplog):
    s = boundary

    async def delayed(*args):
        await asyncio.sleep(0.1)
        return s.grant

    s.client.authorize_knowledge_chunks.side_effect = delayed
    service = KnowledgeSourcesService(s.client, ports=s.ports, operation_seconds=0.01)
    with pytest.raises(DeadlineExceeded):
        await service.list_sources(s.request, s.actor)
    assert not s.opened
    assert sum("knowledge_sources_timeout" in r.message for r in caplog.records) == 1


async def test_cancelled_reader_stops_and_closes_owned_provider(boundary):
    s = boundary
    started, ended = Event(), Event()

    def blocked(*args, context, **kwargs):
        started.set()
        try:
            while not context.cancelled.is_set():
                sleep(0.005)
            context.remaining()
        finally:
            ended.set()

    s.vectors.group.side_effect = blocked
    task = asyncio.create_task(s.service.list_sources(s.request, s.actor))
    async with asyncio.timeout(2):
        while not started.is_set():
            await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(2):
        while not ended.is_set():
            await asyncio.sleep(0.005)
    assert s.closed == [True] and s.client.authorize_knowledge_chunks.await_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 0},
        {"limit": 1001},
        {"limit": True},
        {"knowledge_id": True},
        {"expected_revision": "invalid"},
        {"query": {"match_all": {}}},
        {"fields": ["content"]},
    ],
)
def test_source_request_is_strict_and_has_no_provider_dsl(changes):
    with pytest.raises(ValidationError):
        KnowledgeSources.model_validate(
            {"knowledge_id": 1, "expected_revision": "a" * 64, **changes}
        )


def test_absence_cannot_carry_sources_and_duplicate_keys_are_rejected():
    item = {
        "source_key": "one",
        "path_or_url": "one",
        "filename": "name",
        "file_size": 0,
        "create_time": None,
        "chunk_count": 1,
    }
    for present, items in [(False, [item]), (True, [item, item])]:
        with pytest.raises(ValidationError):
            KnowledgeSourcesResult(
                knowledge_id=1, revision="a" * 64, present=present, sources=items
            )


def test_production_source_composition_keeps_actual_actor_and_closes(mocker):
    from infrastructure import knowledge_sources as composition

    actor = ServicePrincipal("reader", "tenant-a")
    grant = KnowledgeChunksGrant(
        knowledge_id=1,
        collection="kb",
        resource_tenant_id="asset_owner_tenant_id",
        revision="a" * 64,
    )
    factory = mocker.patch.object(composition, "bind_knowledge_vectors")
    context = OperationContext("source-composition", monotonic() + 5)
    with composition.knowledge_source_ports(actor, grant, context=context) as port:
        assert port is factory.return_value
    factory.assert_called_once_with(
        actor, "kb", None, writable=False, resource_tenant_id="asset_owner_tenant_id"
    )
    port.close.assert_called_once()


@pytest.mark.parametrize("bad_type", [False, True])
def test_production_source_composition_rejects_unattested_namespaces(mocker, bad_type):
    from infrastructure import knowledge_sources as composition

    actor = ServicePrincipal("reader", "tenant-a")
    grant = (
        SimpleNamespace(collection="kb", resource_tenant_id="tenant-a")
        if bad_type
        else KnowledgeChunksGrant(
            knowledge_id=1,
            collection="kb",
            resource_tenant_id="foreign",
            revision="a" * 64,
        )
    )
    factory = mocker.patch.object(composition, "bind_knowledge_vectors")
    with (
        pytest.raises(ScopeDenied),
        composition.knowledge_source_ports(
            actor, grant, context=OperationContext("bad-source", monotonic() + 5)
        ),
    ):
        pass
    factory.assert_not_called()
