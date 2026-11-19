# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-APPEND-04 proves the standard signed append transport."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from contracts.agentos_knowledge import KnowledgeOperation
from contracts.constants import environment
from contracts.knowledge_documents import (
    KnowledgeDocument,
    KnowledgeDocumentsAppend,
    KnowledgeDocumentsAppended,
)
from fastapi import FastAPI
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "owned-document-append-protocol")
    request = KnowledgeDocumentsAppend(knowledge_id=1, resource_revision="a" * 64, embedding_model={"model_id": 2},
                                       documents=[KnowledgeDocument(content="text")])
    result = KnowledgeDocumentsAppended(knowledge_id=1, total_submitted=1, total_indexed=1, chunk_ids=["physical"])
    service = SimpleNamespace(append_documents=AsyncMock(return_value=result))
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_knowledge_router(service))
    return app, service, request, result


async def test_typed_client_and_router_preserve_identity_and_confirmed_counts(endpoint):
    app, service, request, result = endpoint
    client = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs))
    assert await client.append_knowledge_documents(request, "operator", "tenant-a") == result
    service.append_documents.assert_awaited_once_with(request, ServicePrincipal("operator", "tenant-a"))


@pytest.mark.parametrize("mode", ["missing", "tampered"])
async def test_unsigned_or_modified_append_never_reaches_service(endpoint, mode):
    app, service, request, _ = endpoint
    body = request.model_dump_json().encode()
    token = sign_call(KnowledgeOperation.APPEND_DOCUMENTS, body, ServicePrincipal("operator", "tenant-a"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        response = await client.post(KnowledgeOperation.APPEND_DOCUMENTS.value,
            content=body + (b" " if mode == "tampered" else b""),
            headers={} if mode == "missing" else {"Authorization": "Bearer " + token})
    assert response.status_code == 401
    service.append_documents.assert_not_called()
