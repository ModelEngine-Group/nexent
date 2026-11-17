# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed KB HTTP boundaries preserve status, identity and safe failure codes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeJobLookup,
    KnowledgeJobState,
    KnowledgeOperation,
    KnowledgeSample,
    KnowledgeSampleResult,
    KnowledgeSearch,
    KnowledgeSearchResult,
)
from contracts.constants import environment
from fastapi import FastAPI
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
)
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_identity import ServicePrincipal, sign_call


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-knowledge-api-key")
    lookup = KnowledgeJobLookup(
        knowledge_id=1, file_id="a" * 32, file_version=0, job_id="b" * 32
    )
    state = KnowledgeJobState(**lookup.model_dump(), status="queued")
    service = SimpleNamespace(
        inspect=AsyncMock(return_value=state),
        upload=AsyncMock(return_value=state),
        delete=AsyncMock(return_value=state),
        search=AsyncMock(),
        sample=AsyncMock(),
    )
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_knowledge_router(service))
    return app, service, lookup


async def send(app, operation, payload, *, tamper=False):
    body = payload.model_dump_json().encode()
    token = sign_call(operation, body, ServicePrincipal("user", "tenant"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime"
    ) as client:
        return await client.post(
            "/api" + operation.value,
            content=body + (b" " if tamper else b""),
            headers={"Authorization": "Bearer " + token},
        )


async def test_inspection_passes_only_signed_identity(setup):
    app, service, lookup = setup
    response = await send(app, KnowledgeOperation.INSPECT, lookup)
    assert response.status_code == 200 and response.json()["job_id"] == lookup.job_id
    service.inspect.assert_awaited_once_with(lookup, ServicePrincipal("user", "tenant"))


async def test_tampered_body_cannot_reach_service(setup):
    app, service, lookup = setup
    response = await send(app, KnowledgeOperation.INSPECT, lookup, tamper=True)
    assert response.status_code == 401
    service.inspect.assert_not_awaited()


async def test_search_requires_signature_and_preserves_model_scope(setup):
    app, service, _ = setup
    request = KnowledgeSearch(knowledge_ids=[1], query="worker", embedding_model={"model_id": 2, "revision": "v1"})
    service.search.return_value = KnowledgeSearchResult(hits=[], embedding_model=request.embedding_model)
    response = await send(app, KnowledgeOperation.SEARCH, request)
    assert response.status_code == 200 and response.json()["hits"] == []
    service.search.assert_awaited_once_with(request, ServicePrincipal("user", "tenant"))
    tampered = await send(app, KnowledgeOperation.SEARCH, request, tamper=True)
    assert tampered.status_code == 401
    service.search.assert_awaited_once()


async def test_sample_uses_signed_reader_and_rejects_tampering(setup):
    app, service, _ = setup
    request = KnowledgeSample(knowledge_id=1, expected_revision='a' * 64)
    service.sample.return_value = KnowledgeSampleResult(knowledge_id=1, knowledge_revision='a' * 64,
        data_revision='b' * 64, embedding_model={'model_id': 2, 'revision': 'v1'}, documents=[])
    response = await send(app, KnowledgeOperation.SAMPLE, request)
    assert response.status_code == 200 and response.json()['documents'] == []
    service.sample.assert_awaited_once_with(request, ServicePrincipal('user', 'tenant'))
    tampered = await send(app, KnowledgeOperation.SAMPLE, request, tamper=True)
    assert tampered.status_code == 401
    service.sample.assert_awaited_once()


async def test_deletion_reports_accepted_without_claiming_physical_completion(setup):
    app, service, lookup = setup
    request = KnowledgeFileDelete(
        knowledge_id=1, file_id=lookup.file_id, file_version=0, idempotency_key="delete"
    )
    service.delete.return_value = KnowledgeJobState(
        **lookup.model_dump(), status="cleanup_pending"
    )
    response = await send(app, KnowledgeOperation.DELETE, request)
    assert (
        response.status_code == 202 and not response.json()["physical_cleanup_complete"]
    )


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ScopeDenied(), 403, "KNOWLEDGE_FORBIDDEN"),
        (Conflict(), 409, "KNOWLEDGE_CONFLICT"),
        (DeadlineExceeded(), 504, "KNOWLEDGE_TIMEOUT"),
        (OutcomeUnknown(), 503, "KNOWLEDGE_OUTCOME_UNKNOWN"),
        (RuntimeError("private-secret"), 500, "KNOWLEDGE_REQUEST_FAILED"),
    ],
)
async def test_errors_remain_safe_and_explicit(setup, error, status, code):
    app, service, lookup = setup
    service.inspect.side_effect = error
    response = await send(app, KnowledgeOperation.INSPECT, lookup)
    assert response.status_code == status and response.json()["code"] == code
    assert "private-secret" not in response.text
