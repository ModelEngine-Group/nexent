# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime factory arguments preserve Gateway identity and monitoring lifetime."""

import ast
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.http.server import app_factory
from gateway.identity import downstream, internal_tokens, middleware


@pytest.mark.parametrize("monitoring_enabled", [False, True])
def test_real_runtime_factory_call_preserves_identity_and_lifespan(monkeypatch, monitoring_enabled):
    events = []

    @asynccontextmanager
    async def producer():
        events.append("producer-start")
        yield
        events.append("producer-stop")

    @asynccontextmanager
    async def business(app):
        events.append("runtime-start")
        yield
        events.append("runtime-stop")

    key = "runtime-factory-isolated-gateway-signature"
    monkeypatch.setattr("contracts.constants.environment.OPS_MONITORING_ENABLED", monitoring_enabled)
    monkeypatch.setattr(app_factory, "monitoring_manager", None)
    monkeypatch.setattr("infrastructure.monitoring.runtime.producer_lifespan", producer)
    monkeypatch.setattr(middleware, "enabled", lambda: True)
    monkeypatch.setattr(middleware, "signing_key", lambda: key)
    monkeypatch.setattr(downstream, "signing_key", lambda: key)
    monkeypatch.setattr(internal_tokens, "JWT_SECRET", "runtime-factory-isolated-service-signature")

    source = Path(__file__).resolve().parents[3] / "backend/runtime/api/application.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    call = next(node.value for node in module.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets))
    app = eval(compile(ast.Expression(call), str(source), "eval"), {
        "create_app": app_factory.create_app, "runtime_lifespan": business,
    })

    def current_identity():
        return downstream.identity_context.get()

    internal_path = "/legacy-service-probe"
    public_path = "/factory-probe"
    app.add_api_route(internal_path, current_identity, methods=["POST"])
    app.add_api_route(public_path, current_identity, methods=["POST"])
    service_token = internal_tokens.generate_internal_runtime_jwt("user", "tenant")
    with TestClient(app) as client:
        response = client.post(internal_path, headers={"Authorization": f"Bearer {service_token}"})
        # AgentOS owns service authentication; the shared factory must not admit legacy JWTs.
        assert response.status_code == 401
        assert client.post(internal_path).status_code == 401
        assert client.post(internal_path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.post(public_path, headers={"Authorization": f"Bearer {service_token}"}).status_code == 401
        session = {"kind": "session", "user_id": "user", "tenant_id": "tenant"}
        signature = downstream.sign_identity(session, "runtime", "POST", public_path, b"", key=key)
        assert client.post(public_path, headers={downstream.IDENTITY_HEADER: signature}).json() == session
        assert client.post(public_path).status_code == 401
        assert client.get("/health/live").status_code == 200
    assert downstream.identity_context.get() is None
    assert events == (["producer-start"] if monitoring_enabled else []) + [
        "runtime-start", "runtime-stop",
    ] + (["producer-stop"] if monitoring_enabled else [])
