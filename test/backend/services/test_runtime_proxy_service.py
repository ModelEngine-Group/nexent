# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise evaluation case forwarding through the signed AgentOS client."""

import httpx
import pytest

from contracts.agentos import CompatibilityOperation, EvaluationAgentRun
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from infrastructure.agentos_identity import ServicePrincipal, verify_call
from management.services.agent import runtime_client as proxy


@pytest.fixture
def evaluation_case(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-test-agentos-secret")
    monkeypatch.setattr(proxy, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    return EvaluationAgentRun(agent_id=1, version_no=2, query="question", conversation_id=-42)


@pytest.mark.asyncio
async def test_evaluation_case_binds_principal_and_preserves_events(monkeypatch, evaluation_case):
    events = [{"type": "thought", "content": "step"}, {"type": "final_answer", "content": "answer"}]

    def handler(request):
        assert request.url.path == f"/api{CompatibilityOperation.EVALUATION_CASE.value}"
        token = request.headers["authorization"].removeprefix("Bearer ")
        assert verify_call(token, CompatibilityOperation.EVALUATION_CASE, request.content) == ServicePrincipal("actor", "tenant")
        assert EvaluationAgentRun.model_validate_json(request.content) == evaluation_case
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
