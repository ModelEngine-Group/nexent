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

from apps.agent_app import agent_runtime_router
from consts.exceptions import (
    RuntimeCapacityExceededError,
    RuntimeQueueTimeoutError,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agent_runtime_router)
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
    import apps.agent_app as agent_app

    transport = httpx.ASGITransport(app=_build_app())

    async def fake_run_agent_stream(**kwargs):
        raise exc

    def fake_verify_internal_runtime_jwt(authorization):
        return "test_user_id", "test_tenant_id"

    for scenario in _SCENARIOS:
        exc = scenario["error_factory"]()
        fake_run_agent_stream.__globals__["exc"] = exc

        original_run = agent_app.run_agent_stream
        original_verify = agent_app.verify_internal_runtime_jwt
        monkeypatch.setattr(agent_app, "run_agent_stream", fake_run_agent_stream)
        monkeypatch.setattr(
            agent_app, "verify_internal_runtime_jwt", fake_verify_internal_runtime_jwt
        )
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    scenario["path"],
                    json={"query": "hello"},
                    headers={"Authorization": "Bearer dummy"},
                )
        finally:
            agent_app.run_agent_stream = original_run
            agent_app.verify_internal_runtime_jwt = original_verify

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
