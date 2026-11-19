# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SOURCES-03 exercise signed sources with both real AgentOS directions."""

from types import SimpleNamespace

import httpx
import pytest
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from nexent.storage.errors import ScopeDenied
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import sign_call
from test.backend.services import test_knowledge_sources as source_units

boundary = source_units.boundary


@pytest.fixture
def protocol(boundary, monkeypatch):
    s = boundary
    monkeypatch.setattr(environment, "JWT_SECRET", "owned-sources-protocol")
    seen = []

    def authorize(request, actor, *, context):
        if actor != s.actor:
            raise ScopeDenied()
        seen.append(actor)
        return s.grant

    management = FastAPI(root_path="/api")
    management.include_router(
        create_knowledge_authorization_router(chunks_service=authorize)
    )
    s.service.client = AgentOSClient(
        "http://management",
        lambda **kw: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=management), **kw
        ),
    )
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_knowledge_router(s.service))
    client = AgentOSClient(
        "http://runtime",
        lambda **kw: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), **kw
        ),
    )
    return SimpleNamespace(**locals())


async def test_signed_roundtrip_keeps_json_and_actual_identity(protocol):
    p = protocol
    s = p.s
    value = await p.client.list_knowledge_sources(
        s.request, s.actor.user_id, s.actor.tenant_id
    )
    assert value.present and value.sources[0].filename == ["raw", None]
    assert p.seen == [s.actor, s.actor] and s.closed == [True]


async def test_tampered_request_never_reaches_authorization_or_provider(protocol):
    p = protocol
    s = p.s
    body = s.request.model_dump_json().encode()
    token = sign_call(KnowledgeOperation.SOURCES, body, s.actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=p.runtime), base_url="http://runtime"
    ) as client:
        response = await client.post(
            KnowledgeOperation.SOURCES.value,
            content=body + b" ",
            headers={"authorization": "Bearer " + token},
        )
    assert response.status_code == 401 and not p.seen and not s.opened


async def test_signed_provider_dsl_is_rejected_before_authorization(protocol):
    p = protocol
    s = p.s
    body = s.request.model_dump_json().removesuffix("}") + ',"query":{"match_all":{}}}'
    encoded = body.encode()
    token = sign_call(KnowledgeOperation.SOURCES, encoded, s.actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=p.runtime), base_url="http://runtime"
    ) as client:
        response = await client.post(
            KnowledgeOperation.SOURCES.value,
            content=encoded,
            headers={"authorization": "Bearer " + token},
        )
    assert response.status_code == 422 and not p.seen and not s.opened


async def test_different_actor_is_denied_by_management_without_payload_read(protocol):
    p = protocol
    with pytest.raises(RuntimeUpstreamError) as error:
        await p.client.list_knowledge_sources(p.s.request, "other", "tenant-a")
    assert error.value.status_code == 403 and not p.s.opened
