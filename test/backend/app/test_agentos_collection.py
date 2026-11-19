# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed collection setup/status and current-editor callbacks share typed contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.knowledge_collections import (
    KnowledgeCollectionAuthorization,
    KnowledgeCollectionEnsure,
    KnowledgeCollectionEnsured,
    KnowledgeCollectionGrant,
    KnowledgeCollectionLookup,
    KnowledgeCollectionStatus,
)
from fastapi import FastAPI
from management.api.knowledge_base import agentos_authorization
from management.services.knowledge_base.collection_authorization import (
    authorize_collection,
)
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
def protocol(monkeypatch):
    monkeypatch.setattr(environment, 'JWT_SECRET', 'owned-collection-protocol')
    actor = ServicePrincipal('operator', 'tenant-a')
    request = KnowledgeCollectionEnsure(knowledge_id=1, expected_revision='a' * 64, dimensions=3)
    result = KnowledgeCollectionEnsured(knowledge_id=1, expected_revision=request.expected_revision,
                                        present=True, dimensions=3, metric='cosine')
    status = KnowledgeCollectionStatus(knowledge_id=1, expected_revision=request.expected_revision, setup=None)
    service = SimpleNamespace(ensure_collection=AsyncMock(return_value=result), inspect_collection=AsyncMock(return_value=status))
    app = FastAPI(root_path='/api')
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_knowledge_router(service))
    client = AgentOSClient('http://runtime', lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs))
    return SimpleNamespace(**locals())


async def test_collection_client_roundtrip_uses_signed_actual_identity(protocol):
    s = protocol
    assert await s.client.ensure_knowledge_collection(s.request, s.actor.user_id, s.actor.tenant_id) == s.result
    lookup = KnowledgeCollectionLookup(knowledge_id=s.request.knowledge_id, expected_revision=s.request.expected_revision)
    assert await s.client.inspect_knowledge_collection(lookup, s.actor.user_id, s.actor.tenant_id) == s.status
    s.service.ensure_collection.assert_awaited_once_with(s.request, s.actor)
    assert s.service.inspect_collection.await_args.args[1] == s.actor


@pytest.mark.parametrize('operation', [KnowledgeOperation.ENSURE_COLLECTION, KnowledgeOperation.INSPECT_COLLECTION])
async def test_modified_collection_body_never_reaches_service(protocol, operation):
    s = protocol
    body = s.request.model_dump_json().encode()
    token = sign_call(operation, body, s.actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url='http://runtime') as client:
        response = await client.post(operation.value, content=body + b' ', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401
    s.service.ensure_collection.assert_not_called()
    s.service.inspect_collection.assert_not_called()


async def test_inspect_does_not_accept_ensure_fields_as_a_compatibility_payload(protocol):
    from contracts.errors.exceptions import RuntimeUpstreamError

    s = protocol
    with pytest.raises(RuntimeUpstreamError) as caught:
        await s.client.inspect_knowledge_collection(s.request, s.actor.user_id, s.actor.tenant_id)
    assert caught.value.status_code == 422
    s.service.inspect_collection.assert_not_called()


async def test_management_callback_is_signed_and_requires_current_edit_reader(protocol, mocker):
    s = protocol
    row = {'knowledge_id': 1, 'index_name': 'kb', 'tenant_id': s.actor.tenant_id, 'embedding_model_id': 2,
           'deletion_request': None, 'knowledge_sources': 'elasticsearch'}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))

    def action(request, actor, *, context):
        return authorize_collection(request, actor, context=context, reader=reader)

    async def blocking(name, function, *args, **kwargs):
        kwargs.pop('lane'); kwargs.pop('owner')
        return function(*args, **kwargs)

    mocker.patch.object(agentos_authorization, 'run_blocking', side_effect=blocking)
    app = FastAPI(root_path='/api')
    app.include_router(agentos_authorization.create_knowledge_authorization_router(collection_service=action))
    client = AgentOSClient('http://management', lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs))
    request = KnowledgeCollectionAuthorization(knowledge_id=1)
    grant = await client.authorize_knowledge_collection(request, s.actor.user_id, s.actor.tenant_id)
    assert isinstance(grant, KnowledgeCollectionGrant) and grant.collection == 'kb'
    assert reader.knowledge.call_args.args == (None, s.actor)
    assert reader.knowledge.call_args.kwargs['edit'] is True
    assert reader.knowledge.call_args.kwargs['knowledge_id'] == 1
    body = request.model_dump_json().encode()
    token = sign_call(ManagementOperation.KNOWLEDGE_COLLECTION_AUTHORIZE, body, s.actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://management') as raw:
        response = await raw.post(ManagementOperation.KNOWLEDGE_COLLECTION_AUTHORIZE.value,
                                  content=body + b' ', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401 and reader.knowledge.call_count == 1
