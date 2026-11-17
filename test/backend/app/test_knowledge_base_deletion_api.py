# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-COLLECTION-01: standard clients and both signed route directions agree."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteAuthorization,
    KnowledgeBaseDeleteGrant,
    KnowledgeBaseDeleteLookup,
    KnowledgeBaseDeleteState,
    knowledge_base_deletion_id,
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
from pydantic import ValidationError
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
async def setup(monkeypatch):
    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-base-deletion-test-secret')
    actor = ServicePrincipal('user', 'tenant')
    request = KnowledgeBaseDelete(knowledge_id=1, idempotency_key='base-delete')
    lookup = KnowledgeBaseDeleteLookup(knowledge_id=1, job_id=knowledge_base_deletion_id(request, 'tenant', 'user'))
    state = KnowledgeBaseDeleteState(**lookup.model_dump(), status='cleanup_pending')
    grant = KnowledgeBaseDeleteGrant(knowledge_id=1, collection='authorized-only')
    manager = ThreadManager(service_name='kb-collection-http-ut', lane_policies={
        'control-io': LanePolicy(name='control-io', max_workers=1, max_queue_size=8,
                                queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=2),
    })
    manager.start()
    set_default_thread_manager(manager)
    action = Mock(return_value=grant)
    service = SimpleNamespace(delete_base=AsyncMock(return_value=state), inspect_base_deletion=AsyncMock(return_value=state))
    runtime, management = FastAPI(root_path='/api'), FastAPI(root_path='/api')
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_knowledge_router(service))
    management.include_router(create_knowledge_authorization_router(base_deletion_service=action))
    clients = []

    def client(app):
        def create(**kwargs):
            instance = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)
            clients.append(instance)
            return instance
        return AgentOSClient('http://service', create)

    try:
        yield SimpleNamespace(**locals())
    finally:
        assert all(c.is_closed for c in clients)
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


async def test_standard_typed_clients_reach_both_signed_boundaries(setup):
    s = setup
    forward, reverse = s.client(s.runtime), s.client(s.management)
    assert await forward.delete_knowledge_base(s.request, 'user', 'tenant') == s.state
    assert await forward.inspect_knowledge_base_deletion(s.lookup, 'user', 'tenant') == s.state
    authorization = KnowledgeBaseDeleteAuthorization(knowledge_id=1)
    assert await reverse.authorize_knowledge_base_deletion(authorization, 'user', 'tenant') == s.grant
    s.service.delete_base.assert_awaited_once_with(s.request, s.actor)
    s.service.inspect_base_deletion.assert_awaited_once_with(s.lookup, s.actor)
    assert s.action.call_args.args == (authorization, s.actor)
    assert s.action.call_args.kwargs['context'].remaining() > 0


@pytest.mark.parametrize('reverse', [False, True])
async def test_tampered_body_never_reaches_either_service(setup, reverse):
    s = setup
    app = s.management if reverse else s.runtime
    operation = ManagementOperation.KNOWLEDGE_BASE_DELETION_AUTHORIZE if reverse else KnowledgeOperation.DELETE_BASE
    payload = KnowledgeBaseDeleteAuthorization(knowledge_id=1) if reverse else s.request
    body = payload.model_dump_json().encode()
    token = sign_call(operation, body, s.actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://service') as client:
        response = await client.post('/api' + operation.value, content=body + b' ', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401
    s.service.delete_base.assert_not_awaited()
    s.action.assert_not_called()


@pytest.mark.parametrize('method,payload', [
    ('delete_knowledge_base', KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete')),
    ('inspect_knowledge_base_deletion', KnowledgeBaseDeleteLookup(knowledge_id=1, job_id='a' * 32)),
    ('authorize_knowledge_base_deletion', KnowledgeBaseDeleteAuthorization(knowledge_id=1)),
])
async def test_each_operation_has_total_deadline_and_one_closed_client(monkeypatch, method, payload):
    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-base-timeout-secret')
    monkeypatch.setattr('infrastructure.agentos_client._KNOWLEDGE_DEADLINE_SECONDS', .05)
    clients, calls, cancelled = [], [], []

    async def hanging(request):
        calls.append(request)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    def create(**kwargs):
        instance = httpx.AsyncClient(transport=httpx.MockTransport(hanging), **kwargs)
        clients.append(instance)
        return instance

    with pytest.raises(RuntimeServiceTimeoutError):
        await getattr(AgentOSClient('http://service', create), method)(payload, 'user', 'tenant')
    assert len(calls) == len(clients) == 1 and clients[0].is_closed and cancelled == [True]


@pytest.mark.parametrize('extra', [{'collection': 'other'}, {'tenant_id': 'foreign'}, {'user_id': 'admin'}])
def test_caller_cannot_supply_storage_authority(extra):
    with pytest.raises(ValidationError):
        KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete', **extra)


def test_terminal_and_stable_identity_are_strict():
    request = KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete')
    keys = {knowledge_base_deletion_id(request, tenant, actor) for tenant, actor in [('a', 'a'), ('a', 'b'), ('b', 'a')]}
    assert len(keys) == 3 and knowledge_base_deletion_id(request, 'a', 'a') in keys
    with pytest.raises(ValidationError):
        KnowledgeBaseDeleteState(knowledge_id=1, job_id='a' * 32, status='deleted')
