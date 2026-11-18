# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB transport has one total deadline, no retry and an owned closed HTTP client."""

import asyncio

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import KnowledgeAuthorizationRequest
from contracts.constants import environment
from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
)

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, verify_call


def request():
    return KnowledgeAuthorizationRequest(knowledge_id=1, file_id="a" * 32, file_version=0, action="inspect")


async def test_deadline_cancels_transport_and_closes_client_once(monkeypatch, caplog):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-kb-client-key")
    monkeypatch.setattr("infrastructure.agentos_client._KNOWLEDGE_DEADLINE_SECONDS", 0.05)
    calls, cancelled, closed, clients = [], [], [], []

    async def hanging(message):
        calls.append(message)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    class Client(httpx.AsyncClient):
        async def __aexit__(self, *args):
            try:
                return await super().__aexit__(*args)
            finally:
                closed.append(self.is_closed)

    def create(**kwargs):
        client = Client(transport=httpx.MockTransport(hanging), **kwargs)
        clients.append(client)
        return client

    with pytest.raises(RuntimeServiceTimeoutError):
        await asyncio.wait_for(AgentOSClient("http://management", create).authorize_knowledge(request(), "user", "tenant"), timeout=1)
    assert len(calls) == 1 and cancelled == [True] and closed == [True]
    assert len(clients) == 1 and clients[0].is_closed
    assert len(caplog.records) == 1 and "agentos_knowledge_timeout" in caplog.text
    assert "Authorization" not in caplog.text and "file_id" not in caplog.text


async def test_callback_uses_reverse_body_bound_signature_and_validates_response(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-kb-client-key")
    clients = []

    async def reply(message):
        assert message.url.path == "/api" + ManagementOperation.KNOWLEDGE_AUTHORIZE.value
        token = message.headers["Authorization"].removeprefix("Bearer ")
        assert verify_call(token, ManagementOperation.KNOWLEDGE_AUTHORIZE, message.content) == ServicePrincipal("user", "tenant")
        return httpx.Response(200, json={"unexpected": "not-a-grant"})

    def create(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
        clients.append(client)
        return client

    with pytest.raises(RuntimeServiceUnavailableError):
        await AgentOSClient("http://management", create).authorize_knowledge(request(), "user", "tenant")
    assert len(clients) == 1 and clients[0].is_closed


async def test_search_total_deadline_closes_the_only_client(monkeypatch):
    from contracts.agentos_knowledge import KnowledgeSearch

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-search-client-key")
    monkeypatch.setattr("infrastructure.agentos_client._KNOWLEDGE_SEARCH_DEADLINE_SECONDS", 0.05)
    clients, requests = [], []

    async def wait(message):
        requests.append(message)
        await asyncio.Event().wait()

    def create(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(wait), **kwargs)
        clients.append(client)
        return client

    with pytest.raises(RuntimeServiceTimeoutError):
        await AgentOSClient("http://runtime", create).search_knowledge(
            KnowledgeSearch(knowledge_ids=[1], query="private query", embedding_model={"model_id": 2, "revision": "v1"}), "user", "tenant")
    assert len(requests) == len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize('mutation', [False, True])
async def test_knowledge_total_deadline_cancels_and_closes_without_retry(monkeypatch, mutation):
    from contracts.agentos_knowledge import KnowledgeOperation, KnowledgeSample
    from contracts.knowledge_chunk_mutation import ChunkMutationIntent

    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-sample-client-key')
    monkeypatch.setattr('infrastructure.agentos_client._KNOWLEDGE_SEARCH_DEADLINE_SECONDS', 0.1)
    clients, calls, cancelled = [], [], []
    operation = KnowledgeOperation.MUTATE_CHUNK if mutation else KnowledgeOperation.SAMPLE
    async def blocked(message):
        calls.append(message)
        assert message.url.path == '/api' + operation.value
        token = message.headers['Authorization'].removeprefix('Bearer ')
        assert verify_call(token, operation, message.content) == ServicePrincipal('user', 'tenant')
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    def create(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(blocked), **kwargs)
        clients.append(client)
        return client
    with pytest.raises(RuntimeServiceTimeoutError):
        client = AgentOSClient('http://runtime', create)
        payload = ChunkMutationIntent(knowledge_id=1,chunk_id='manual',request_key='request',operation='create',
            resource_revision='a'*64,changes={'content':'body'}) if mutation else KnowledgeSample(knowledge_id=1, expected_revision='a' * 64)
        await (client.mutate_knowledge_chunk if mutation else client.sample_knowledge)(payload, 'user', 'tenant')
    assert len(clients) == len(calls) == 1 and clients[0].is_closed and cancelled == [True]


async def test_chunks_use_standard_signature_and_close_transport(monkeypatch):
    from contracts.agentos_knowledge import KnowledgeChunks, KnowledgeOperation

    monkeypatch.setattr(environment,'JWT_SECRET','synthetic-chunks-client-key')
    clients=[]
    async def reply(message):
        assert message.url.path=='/api'+KnowledgeOperation.CHUNKS.value
        token=message.headers['Authorization'].removeprefix('Bearer ')
        assert verify_call(token,KnowledgeOperation.CHUNKS,message.content)==ServicePrincipal('reader','tenant')
        return httpx.Response(200,json={'knowledge_id':1,'knowledge_revision':'a'*64,'data_revision':'b'*64,
            'total':0,'chunks':[],'next_offset':None})
    def create(**kwargs):
        client=httpx.AsyncClient(transport=httpx.MockTransport(reply),**kwargs);clients.append(client);return client
    result=await AgentOSClient('http://runtime',create).knowledge_chunks(
        KnowledgeChunks(knowledge_id=1,expected_revision='a'*64),'reader','tenant')
    assert result.total==0 and len(clients)==1 and clients[0].is_closed
