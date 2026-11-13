# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""D2 error-contract test for the agent runtime overload endpoints.

Verifies that ``POST /agent/run`` and
``POST /agent/internal/northbound/run`` map ``RuntimeCapacityExceededError``
and ``RuntimeQueueTimeoutError`` to the documented HTTP 429 contract instead
of falling through to the generic 500 handler.
"""

from __future__ import annotations

import pytest
import httpx
from fastapi import FastAPI

from gateway.downstream.identity import IDENTITY_HEADER, sign_identity
from gateway.downstream import internal_tokens
from gateway.downstream.middleware import GatewayIdentityMiddleware
from runtime.api.agent import execution
from runtime.api.identity_routes import is_runtime_service_request
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeCapacityExceededError, RuntimeQueueTimeoutError

_SIGNING_KEY = "synthetic-runtime-overload-signing-key"
_IDENTITY = {"user_id": "test_user_id", "tenant_id": "test_tenant_id", "kind": "session"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        GatewayIdentityMiddleware, audience="runtime", required=True,
        internal_runtime_request=is_runtime_service_request,
    )
    app.include_router(execution.agent_runtime_router)
    return app


# Each scenario exercises one endpoint against one runtime overload error type.
_SCENARIOS = [
    {
        "name": "agent-run capacity full",
        "path": "/agent/run",
        "error_factory": lambda: RuntimeCapacityExceededError(),
        "expected_code": "RUNTIME_CAPACITY_FULL",
        "expected_message": "Agent runtime is at capacity.",
        "expected_retry_after": "1",
    },
    {
        "name": "agent-run queue timeout",
        "path": "/agent/run",
        "error_factory": lambda: RuntimeQueueTimeoutError(30),
        "expected_code": "RUNTIME_QUEUE_TIMEOUT",
        "expected_message": "Agent runtime queue wait timed out.",
        "expected_retry_after": str(
            RuntimeQueueTimeoutError(30).retry_after_seconds
        ),
    },
    {
        "name": "northbound-run capacity full",
        "path": "/agent/internal/northbound/run",
        "error_factory": lambda: RuntimeCapacityExceededError(),
        "expected_code": "RUNTIME_CAPACITY_FULL",
        "expected_message": "Agent runtime is at capacity.",
        "expected_retry_after": "1",
    },
    {
        "name": "northbound-run queue timeout",
        "path": "/agent/internal/northbound/run",
        "error_factory": lambda: RuntimeQueueTimeoutError(30),
        "expected_code": "RUNTIME_QUEUE_TIMEOUT",
        "expected_message": "Agent runtime queue wait timed out.",
        "expected_retry_after": str(
            RuntimeQueueTimeoutError(30).retry_after_seconds
        ),
    },
]


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-7CBDF5C068165594")
@pytest.mark.asyncio
async def test_runtime_overload_error_contract(monkeypatch) -> None:
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", _SIGNING_KEY)
    monkeypatch.setattr(environment, "JWT_SECRET", _SIGNING_KEY)
    monkeypatch.setattr(internal_tokens, "JWT_SECRET", _SIGNING_KEY)
    transport = httpx.ASGITransport(app=_build_app())

    for scenario in _SCENARIOS:
        exc = scenario["error_factory"]()

        async def fake_run_agent_stream(**kwargs):
            assert (kwargs["user_id"], kwargs["tenant_id"]) == ("test_user_id", "test_tenant_id")
            raise exc

        monkeypatch.setattr(execution, "run_agent_stream", fake_run_agent_stream)
        path = scenario["path"]
        if path == "/agent/run":
            headers = {IDENTITY_HEADER: sign_identity(_IDENTITY, "runtime", "POST", path, b"", key=_SIGNING_KEY)}
        else:
            headers = {"Authorization": "Bearer " + internal_tokens.generate_internal_runtime_jwt(
                "test_user_id", "test_tenant_id",
            )}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(path, json={"query": "hello"}, headers=headers)

        assert response.status_code == 429, (
            f"{scenario['name']}: expected HTTP 429, got {response.status_code}; "
            f"body={response.text!r}"
        )
        body = response.json()
        assert body.get("code") == scenario["expected_code"], body
        assert body.get("message") == scenario["expected_message"], body
        assert body.get("retryable") is True, body
        assert response.headers.get("Retry-After") == scenario["expected_retry_after"]
        assert body.get("detail") is None
        assert "Agent run error." not in str(body)
