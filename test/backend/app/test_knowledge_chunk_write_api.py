# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Both directions of chunk writes bind exact bodies and typed actor identities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.knowledge_chunk_mutation import (
    ChunkMutationAuthorization,
    ChunkMutationGrant,
    ChunkMutationIntent,
    ChunkMutationState,
)
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-chunk-write-api-key")
    manager = ThreadManager(
        service_name="chunk-write-api",
        lane_policies={
            "control-io": LanePolicy(
                "control-io",
                1,
                4,
                queue_timeout_seconds=1,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=3,
            )
        },
    )
    manager.start()
    set_default_thread_manager(manager)
    actor = ServicePrincipal("operator", "tenant")
    payload = ChunkMutationIntent(
        knowledge_id=1,
        chunk_id="manual",
        request_key="request",
        operation="create",
        resource_revision="a" * 64,
        changes={"content": "sensitive body"},
    )
    state = ChunkMutationState(
        knowledge_id=1,
        chunk_id="manual",
        operation="create",
        mutation_id="b" * 64,
        status="completed",
        writer_ended=True,
        count_delta=1,
        commit_epoch=1,
    )
    service = SimpleNamespace(mutate_chunk=AsyncMock(return_value=state))
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_knowledge_router(service))
    grant = ChunkMutationGrant(
        knowledge_id=1,
        chunk_id="manual",
        operation="create",
        collection="kb",
        resource_tenant_id="tenant",
        revision="a" * 64,
    )
    authorize = Mock(return_value=grant)
    management = FastAPI(root_path="/api")
    management.include_router(
        create_knowledge_authorization_router(chunk_mutation_service=authorize)
    )
    try:
        yield SimpleNamespace(**locals())
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids


@pytest.mark.parametrize("direction", ["runtime", "management"])
@pytest.mark.parametrize("credential", ["signed", "tampered", "missing"])
async def test_chunk_write_routes_bind_identity_and_exact_body(
    api, direction, credential
):
    s = api
    app = getattr(s, direction)
    operation = (
        KnowledgeOperation.MUTATE_CHUNK
        if direction == "runtime"
        else ManagementOperation.KNOWLEDGE_CHUNK_MUTATION_AUTHORIZE
    )
    payload = (
        s.payload
        if direction == "runtime"
        else ChunkMutationAuthorization(
            knowledge_id=1, chunk_id="manual", operation="create"
        )
    )
    body = payload.model_dump_json().encode()
    headers = (
        {}
        if credential == "missing"
        else {"Authorization": "Bearer " + sign_call(operation, body, s.actor)}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://service"
    ) as client:
        response = await client.post(
            "/api" + operation.value,
            content=body + (b" " if credential == "tampered" else b""),
            headers=headers,
        )
    if credential == "signed":
        assert response.status_code == 200
        if direction == "runtime":
            s.service.mutate_chunk.assert_awaited_once_with(payload, s.actor)
        else:
            assert s.authorize.call_args.args == (payload, s.actor)
    else:
        assert response.status_code == 401
        s.service.mutate_chunk.assert_not_awaited()
        s.authorize.assert_not_called()


async def test_typed_transport_roundtrips_both_directions(api):
    s = api

    def factory(app):
        return lambda **kwargs: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), **kwargs
        )

    runtime = AgentOSClient("http://runtime", factory(s.runtime))
    management = AgentOSClient("http://management", factory(s.management))
    assert (
        await runtime.mutate_knowledge_chunk(
            s.payload, s.actor.user_id, s.actor.tenant_id
        )
        == s.state
    )
    request = ChunkMutationAuthorization(
        knowledge_id=1, chunk_id="manual", operation="create"
    )
    assert (
        await management.authorize_knowledge_chunk_mutation(
            request, s.actor.user_id, s.actor.tenant_id
        )
        == s.grant
    )


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ScopeDenied(), 403, "KNOWLEDGE_FORBIDDEN"),
        (DeadlineExceeded(), 504, "KNOWLEDGE_TIMEOUT"),
    ],
)
async def test_write_errors_are_redacted_and_not_replayed(api, error, status, code):
    s = api
    s.service.mutate_chunk.side_effect = error
    operation = KnowledgeOperation.MUTATE_CHUNK
    body = s.payload.model_dump_json().encode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=s.runtime), base_url="http://runtime"
    ) as client:
        response = await client.post(
            "/api" + operation.value,
            content=body,
            headers={"Authorization": "Bearer " + sign_call(operation, body, s.actor)},
        )
    assert response.status_code == status and response.json() == {"code": code}
    assert s.service.mutate_chunk.await_count == 1
