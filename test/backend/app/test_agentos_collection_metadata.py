# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-META-03 keep batch metadata strict and signed in both directions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionDescription,
    KnowledgeCollectionEnsure,
    KnowledgeCollectionGrant,
    KnowledgeCollectionsAuthorization,
    KnowledgeCollectionsDescribe,
    KnowledgeCollectionsDescribed,
    KnowledgeCollectionsGrant,
)
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from pydantic import ValidationError
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
def protocol(monkeypatch):
    monkeypatch.setattr(environment, 'JWT_SECRET', 'owned-metadata-protocol')
    actor = ServicePrincipal('reader', 'tenant-a')
    request = KnowledgeCollectionsDescribe(knowledge_ids=[1], expected_revisions={1: 'a' * 64})
    result = KnowledgeCollectionsDescribed(items=[KnowledgeCollectionDescription(
        knowledge_id=1, expected_revision='a' * 64, present=True, metric='cosine')])
    service = SimpleNamespace(describe_collections=AsyncMock(return_value=result))
    app = FastAPI(root_path='/api'); app.add_middleware(AgentOSMiddleware)
    app.include_router(create_knowledge_router(service))
    client = AgentOSClient('http://runtime', lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kw))
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
async def test_signed_batch_roundtrip_keeps_actual_actor_and_json_integer_keys(protocol):
    s = protocol
    assert await s.client.describe_knowledge_collections(s.request, s.actor.user_id, s.actor.tenant_id) == s.result
    s.service.describe_collections.assert_awaited_once_with(s.request, s.actor)


@pytest.mark.asyncio
async def test_tampered_batch_never_reaches_service(protocol):
    s = protocol
    operation = KnowledgeOperation.DESCRIBE_COLLECTIONS
    body = s.request.model_dump_json().encode()
    token = sign_call(operation, body, s.actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url='http://runtime') as client:
        response = await client.post(operation.value, content=body + b' ', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401
    s.service.describe_collections.assert_not_awaited()


@pytest.mark.parametrize('change', [
    {'knowledge_ids': []}, {'knowledge_ids': [1, 1]}, {'knowledge_ids': [True]},
    {'knowledge_ids': list(range(1, 102))}, {'expected_revisions': {}},
    {'expected_revisions': {2: 'a' * 64}}, {'expected_revisions': {1: 'x' * 64}},
    {'include_statistics': 1}, {'view': 'admin'}, {'query': {'match_all': {}}},
])
def test_batch_contract_rejects_incomplete_or_provider_specific_inputs(change):
    with pytest.raises(ValidationError):
        KnowledgeCollectionsDescribe.model_validate({'knowledge_ids': [1], 'expected_revisions': {1: 'a' * 64}, **change})


def test_absence_cannot_carry_statistics_or_dimensions():
    with pytest.raises(ValidationError):
        KnowledgeCollectionDescription(knowledge_id=1, expected_revision='a' * 64, present=False, dimensions=3)


@pytest.mark.asyncio
async def test_signed_callback_preserves_view_and_uses_managed_si_action(protocol, mocker):
    s = protocol
    grant = KnowledgeCollectionsGrant(knowledge_bases=[KnowledgeCollectionGrant(knowledge_id=1,
        collection='kb', resource_tenant_id='tenant-a', revision='a' * 64)])
    calls = []
    def action(payload, actor, *, context):
        calls.append((payload, actor, context)); return grant
    async def blocking(name, function, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.knowledge_base'
        return function(*args, **kwargs)
    mocker.patch('management.api.knowledge_base.agentos_authorization.run_blocking', side_effect=blocking)
    app = FastAPI(root_path='/api'); app.include_router(create_knowledge_authorization_router(metadata_service=action))
    client = AgentOSClient('http://management', lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kw))
    payload = KnowledgeCollectionsAuthorization(knowledge_ids=[1], view='inventory')
    assert await client.authorize_collection_metadata(payload, s.actor.user_id, s.actor.tenant_id) == grant
    assert len(calls) == 1 and calls[0][:2] == (payload, s.actor)
    assert calls[0][2].remaining() > 0
    body = payload.model_dump_json().encode()
    token = sign_call(ManagementOperation.KNOWLEDGE_COLLECTION_AUTHORIZE, body, s.actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://management') as raw:
        response = await raw.post(ManagementOperation.KNOWLEDGE_COLLECTION_METADATA_AUTHORIZE.value,
            content=body, headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401 and len(calls) == 1


@pytest.mark.asyncio
async def test_write_contract_is_not_a_metadata_compatibility_payload(protocol):
    s = protocol
    payload = KnowledgeCollectionEnsure(knowledge_id=1, dimensions=3, expected_revision='a' * 64)
    with pytest.raises(RuntimeUpstreamError) as caught:
        await s.client.describe_knowledge_collections(payload, s.actor.user_id, s.actor.tenant_id)
    assert caught.value.status_code == 422
    s.service.describe_collections.assert_not_awaited()
