# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from runtime.api.agent import execution


def test_authenticated_run_preserves_coordination_unavailable_status_and_retry_header(monkeypatch):
    monkeypatch.setattr(execution, 'verify_internal_runtime_jwt', lambda _: ('user', 'tenant'))
    monkeypatch.setattr(execution, 'run_agent_stream', AsyncMock(side_effect=HTTPException(
        status_code=503, detail='Runtime is not accepting execution', headers={'Retry-After': '1'})))
    app = FastAPI()
    app.include_router(execution.agent_runtime_router)
    with TestClient(app) as client:
        response = client.post('/agent/internal/northbound/run',
            headers={'Authorization': 'Bearer controlled-test-token'},
            json={'agent_id': 1, 'query': 'hello', 'conversation_id': 7})
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '1'
