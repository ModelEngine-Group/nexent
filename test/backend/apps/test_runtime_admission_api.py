# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_run


def test_authenticated_run_preserves_coordination_unavailable_status(monkeypatch):
    reject = AsyncMock(side_effect=HTTPException(
        503, detail={"code": "AGENTOS_SANDBOX_OWNERSHIP_UNKNOWN"},
    ))
    monkeypatch.setattr(prepared_run, "start_prepared_run", reject)
    app = FastAPI()

    @app.middleware("http")
    async def inject_verified_request(request: Request, call_next):
        request.scope[PRINCIPAL_KEY] = ServicePrincipal("user", "tenant")
        request.scope[BODY_KEY] = await request.body()
        return await call_next(request)

    app.include_router(prepared_run.create_prepared_run_router())
    with TestClient(app) as client:
        response = client.post(AgentOperation.RUN.value, json={
            "mode": "nexent", "conversation_id": 7, "run_id": "a" * 32,
            "resource": {"agent_id": 1, "version_no": 1, "name": "agent", "description": "", "prompt_templates": {}},
            "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
            "input": {"query": "hello"},
        })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENTOS_SANDBOX_OWNERSHIP_UNKNOWN"
    reject.assert_awaited_once()
