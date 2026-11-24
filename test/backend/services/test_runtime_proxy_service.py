# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise evaluation case forwarding through the signed AgentOS client."""

from unittest.mock import AsyncMock

import httpx
import pytest

from contracts.agentos import AgentOperation, EvaluationAgentRun, PreparedEvaluationRun
from contracts.constants import environment
from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError, ValidationError,
)
from infrastructure.agentos_identity import ServicePrincipal, verify_call
from management.services.agent import runtime_client as proxy


@pytest.fixture
def prepared_case():
    return PreparedEvaluationRun.model_validate({
        "mode": "nexent",
        "resource": {
            "agent_id": 1, "version_no": 2, "name": "agent",
            "description": "agent", "prompt_templates": {},
        },
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
        "input": {"query": "question"},
        "conversation_id": -42,
    })


@pytest.fixture
def evaluation_case(monkeypatch, prepared_case):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-test-agentos-secret")
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    monkeypatch.setattr(
        "management.services.agent.preparation.evaluation_snapshot.prepare_evaluation_snapshot",
        AsyncMock(return_value=prepared_case),
    )
    return EvaluationAgentRun(agent_id=1, version_no=2, query="question", conversation_id=-42)


@pytest.mark.asyncio
async def test_evaluation_case_binds_principal_and_preserves_events(monkeypatch, evaluation_case, prepared_case):
    events = [{"type": "thought", "content": "step"}, {"type": "final_answer", "content": "answer"}]

    def handler(request):
        assert request.url.path == f"/api{AgentOperation.EVALUATION_CASE.value}"
        token = request.headers["authorization"].removeprefix("Bearer ")
        assert verify_call(token, AgentOperation.EVALUATION_CASE, request.content) == ServicePrincipal("actor", "tenant")
        assert PreparedEvaluationRun.model_validate_json(request.content) == prepared_case
        return httpx.Response(200, json={"answer": "answer", "events": events})

    monkeypatch.setattr(proxy, "create_httpx_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    result = await proxy.forward_evaluation_case(evaluation_case, "actor", "tenant")
    assert result.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize(("outcome", "expected"), [
    (httpx.ConnectError("failed"), RuntimeServiceUnavailableError),
    (httpx.ReadTimeout("timeout"), RuntimeServiceTimeoutError),
    (httpx.Response(401, json={"code": "AGENTOS_UNAUTHORIZED"}), RuntimeUpstreamError),
    (httpx.Response(200, json={"answer": "answer", "events": "bad"}), RuntimeServiceUnavailableError),
    (httpx.Response(200, content=b"bad JSON"), RuntimeServiceUnavailableError),
])
async def test_evaluation_case_rejects_transport_and_response_failures(monkeypatch, evaluation_case, outcome, expected):
    def handler(_request):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(proxy, "create_httpx_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(expected):
        await proxy.forward_evaluation_case(evaluation_case, "actor", "tenant")


@pytest.mark.asyncio
async def test_prepared_evaluation_routes_once_and_never_retries_legacy(mocker, monkeypatch, evaluation_case, prepared_case):
    payload = prepared_case
    prepare = mocker.patch(
        "management.services.agent.preparation.evaluation_snapshot.prepare_evaluation_snapshot",
        new_callable=AsyncMock, return_value=payload,
    )
    requests = []

    def handler(request):
        requests.append(request.url.path)
        token = request.headers["authorization"].removeprefix("Bearer ")
        assert verify_call(token, AgentOperation.EVALUATION_CASE, request.content) == ServicePrincipal("actor", "tenant")
        assert PreparedEvaluationRun.model_validate_json(request.content) == payload
        return httpx.Response(500, json={"detail": "execution failed"})

    monkeypatch.setattr(proxy, "create_httpx_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(RuntimeUpstreamError):
        await proxy.forward_evaluation_case(evaluation_case, "actor", "tenant")
    prepare.assert_awaited_once_with(evaluation_case, "actor", "tenant")
    assert requests == [f"/api{AgentOperation.EVALUATION_CASE.value}"]


@pytest.mark.asyncio
async def test_missing_evaluation_snapshot_does_not_contact_runtime(mocker, evaluation_case):
    prepare = mocker.patch(
        "management.services.agent.preparation.evaluation_snapshot.prepare_evaluation_snapshot",
        new_callable=AsyncMock, return_value=None,
    )
    create_client = mocker.patch.object(proxy, "_agentos_client")

    with pytest.raises(ValidationError, match="Evaluation resources could not be prepared for AgentOS"):
        await proxy.forward_evaluation_case(evaluation_case, "actor", "tenant")

    prepare.assert_awaited_once_with(evaluation_case, "actor", "tenant")
    create_client.assert_not_called()
