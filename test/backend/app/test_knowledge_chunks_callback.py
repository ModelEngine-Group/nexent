# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime chunk grants require a body-bound signature and the actual actor."""

from unittest.mock import Mock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import (
    KnowledgeChunksAuthorization,
    KnowledgeChunksGrant,
)
from contracts.constants import environment
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
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
async def callback(monkeypatch):
    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-chunks-callback-key')
    manager = ThreadManager(service_name='chunks-callback-ut', lane_policies={
        'control-io': LanePolicy('control-io', 1, 4, queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=3)})
    manager.start()
    set_default_thread_manager(manager)
    service = Mock(return_value=KnowledgeChunksGrant(knowledge_id=1, collection='kb', resource_tenant_id='tenant', revision='a' * 64))
    app = FastAPI(root_path='/api')
    app.include_router(create_knowledge_authorization_router(chunks_service=service))
    try:
        yield app, service
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids


@pytest.mark.parametrize('tamper', [False, True])
async def test_chunks_callback_binds_identity_and_exact_body(callback, tamper):
    app, service = callback
    operation = ManagementOperation.KNOWLEDGE_CHUNKS_AUTHORIZE
    payload = KnowledgeChunksAuthorization(knowledge_id=1)
    body = payload.model_dump_json().encode()
    actor = ServicePrincipal('reader', 'tenant')
    token = sign_call(operation, body, actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://management') as client:
        response = await client.post('/api' + operation.value, content=body + (b' ' if tamper else b''),
                                     headers={'Authorization': 'Bearer ' + token})
    if tamper:
        assert response.status_code == 401
        service.assert_not_called()
    else:
        assert response.status_code == 200 and response.json()['resource_tenant_id'] == 'tenant'
        assert service.call_args.args == (payload, actor)


async def test_chunks_callback_preserves_denial_without_details(callback):
    app, service = callback
    service.side_effect = ScopeDenied()
    operation = ManagementOperation.KNOWLEDGE_CHUNKS_AUTHORIZE
    body = KnowledgeChunksAuthorization(knowledge_id=1).model_dump_json().encode()
    token = sign_call(operation, body, ServicePrincipal('reader', 'tenant'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://management') as client:
        response = await client.post('/api' + operation.value, content=body, headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 403 and response.json()['code'] == 'KNOWLEDGE_FORBIDDEN'
