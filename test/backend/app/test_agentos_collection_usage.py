# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-USAGE-03 keep quota scalar RPC signed and schema-bound."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionGrant,
    KnowledgeCollectionsGrant,
    KnowledgeCollectionsUsage,
)
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import VectorCollectionStatistics, VectorFieldStatistics
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.knowledge_base.collection_usage import KnowledgeCollectionUsageService

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import sign_call
from test.backend.services.test_knowledge_sources import boundary  # noqa: F401


@pytest.fixture
def protocol(boundary, mocker):  # noqa: F811
    s = boundary
    mocker.patch.object(environment, "JWT_SECRET", "owned-usage-test")
    seen = []

    def authorize(payload, actor, *, context):
        if actor != s.actor:
            raise ScopeDenied()
        assert payload.view == "usage" and payload.knowledge_ids == [1]
        seen.append(actor)
        return KnowledgeCollectionsGrant(
            knowledge_bases=[
                KnowledgeCollectionGrant(
                    knowledge_id=1,
                    collection="kb",
                    resource_tenant_id="tenant-a",
                    revision="a" * 64,
                )
            ]
        )

    management = FastAPI(root_path="/api")
    management.include_router(
        create_knowledge_authorization_router(metadata_service=authorize)
    )
    callbacks = AgentOSClient(
        "http://management",
        lambda **kw: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=management), **kw
        ),
    )
    s.vectors.statistics = Mock(
        return_value=VectorCollectionStatistics(
            "kb",
            4,
            10,
            100,
            0,
            0,
            (VectorFieldStatistics("source", 2, ("private-source",)),),
        )
    )
    service = KnowledgeCollectionUsageService(callbacks, ports=s.ports)
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(
        create_knowledge_router(SimpleNamespace(collection_usage=service.describe))
    )
    client = AgentOSClient(
        "http://runtime",
        lambda **kw: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), **kw
        ),
    )
    request = KnowledgeCollectionsUsage(
        knowledge_ids=[1], expected_revisions={1: "a" * 64}
    )
    return SimpleNamespace(**locals())


async def test_actual_both_direction_signature_and_scalar_roundtrip(protocol):
    p = protocol
    s = p.s
    result = await p.client.knowledge_collection_usage(
        p.request, s.actor.user_id, s.actor.tenant_id
    )
    assert result.items[0].statistics.model_dump() == {
        "record_count": 4,
        "size_bytes": 10,
        "source_count": 2,
    }
    assert "private-source" not in result.model_dump_json()
    assert p.seen == [s.actor, s.actor] and s.closed == [True]


async def test_tampered_usage_request_never_reaches_callback_or_provider(protocol):
    p = protocol
    body = p.request.model_dump_json().encode()
    token = sign_call(KnowledgeOperation.COLLECTION_USAGE, body, p.s.actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=p.runtime), base_url="http://runtime"
    ) as client:
        response = await client.post(
            KnowledgeOperation.COLLECTION_USAGE.value,
            content=body + b" ",
            headers={"authorization": "Bearer " + token},
        )
    assert response.status_code == 401 and not p.seen and not p.s.opened


async def test_signed_provider_query_is_refused_before_authorization(protocol):
    p = protocol
    body = (p.request.model_dump_json()[:-1] + ',"query":{}}').encode()
    token = sign_call(KnowledgeOperation.COLLECTION_USAGE, body, p.s.actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=p.runtime), base_url="http://runtime"
    ) as client:
        response = await client.post(
            KnowledgeOperation.COLLECTION_USAGE.value,
            content=body,
            headers={"authorization": "Bearer " + token},
        )
    assert response.status_code == 422 and not p.seen and not p.s.opened


async def test_other_actor_cannot_borrow_usage_authorization(protocol):
    p = protocol
    with pytest.raises(RuntimeUpstreamError) as error:
        await p.client.knowledge_collection_usage(p.request, "other", "tenant-a")
    assert error.value.status_code == 403 and not p.s.opened


async def test_usage_client_total_deadline_closes_unresponsive_transport_once(
    mocker, caplog
):
    import asyncio

    from contracts.errors.exceptions import RuntimeServiceTimeoutError

    from infrastructure import agentos_client as transport

    mocker.patch.object(environment, "JWT_SECRET", "owned-usage-timeout")
    mocker.patch.object(transport, "_COLLECTION_USAGE_DEADLINE_SECONDS", 0.03)
    state = {"calls": 0, "exited": 0, "closed": 0}

    class Unresponsive(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            state["calls"] += 1
            try:
                await asyncio.sleep(1)
            finally:
                state["exited"] += 1

        async def aclose(self):
            state["closed"] += 1

    client = AgentOSClient(
        "http://runtime", lambda **kw: httpx.AsyncClient(transport=Unresponsive(), **kw)
    )
    payload = KnowledgeCollectionsUsage(
        knowledge_ids=[1], expected_revisions={1: "a" * 64}
    )
    with pytest.raises(RuntimeServiceTimeoutError):
        await client.knowledge_collection_usage(payload, "reader", "tenant-a")
    assert state == {"calls": 1, "exited": 1, "closed": 1}
    assert (
        sum(
            "agentos_knowledge_collection_usage_timeout" in r.message
            and r.levelname == "WARNING"
            for r in caplog.records
        )
        == 1
    )
