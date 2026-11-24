# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Behavioural coverage for the dark automation action gates.

The action capabilities stay declared-but-dark at the gateway (no routing
row, indistinguishable from nonexistent). Their handler bodies must still be
correct for the day a declaration flips to enabled: envelope on success, an
audit trail on success and denial, and async facade methods awaited. These
tests drive the handlers over the real routers with the business lane mocked.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.errors.exceptions import AutomationNotFoundError, ForbiddenError
from backend.http.server.app_factory import create_app

IDENTITY = AuthenticatedIdentity("user-1", "tenant-1", kind=CredentialKind.API_KEY, token_id=42)

# (capability, method, path template, facade method, awaited)
DARK_ACTIONS = [
    ("automations.pause", "POST", "/nb/v1/automations/5/pause", "pause_task", False),
    ("automations.resume", "POST", "/nb/v1/automations/5/resume", "resume_task", False),
    ("automations.run", "POST", "/nb/v1/automations/5/run", "run_task_now", True),
    ("automations.delete", "DELETE", "/nb/v1/automations/5", "delete_task", True),
    ("automations.run_cancel", "POST", "/nb/v1/automations/runs/9/cancel", "cancel_run", True),
]


@pytest.fixture()
def dark_client(monkeypatch):
    """Real gate routers with a mocked automation facade and audit sink."""
    import management.api.northbound_gates.automations as auto_gates

    facade = MagicMock()
    facade.pause_task.return_value = {"id": 5, "status": "paused"}
    facade.resume_task.return_value = {"id": 5, "status": "active"}
    facade.run_task_now = AsyncMock(return_value={"run_id": 9, "status": "queued"})
    facade.delete_task = AsyncMock(return_value=True)
    facade.cancel_run = AsyncMock(return_value={"run_id": 9, "status": "cancelled"})
    facade.list_runs.return_value = {"items": [], "total": 0}
    monkeypatch.setattr(auto_gates, "agent_automation_facade", facade)

    audit_calls = []
    from management.services.monitor import audit as audit_mod
    from management.services.permission.identity import northbound as nb_ident

    monkeypatch.setattr(
        audit_mod, "record_security_event", lambda *a, **k: audit_calls.append((a, k))
    )
    monkeypatch.setattr(nb_ident, "submit_api_key_usage", lambda principal, request=None: None)

    app = create_app(title="nb-dark-gates", enable_monitoring=False)
    from management.api.northbound_gates import nb_capability_routers
    from management.services.permission.identity import dependency as dep

    for router in nb_capability_routers():
        app.include_router(router)
    app.dependency_overrides[dep.unified_identity] = lambda: IDENTITY
    # The dark gates re-raise domain failures; Starlette's ServerErrorMiddleware
    # renders the registered handler's response but always re-raises for server
    # logging, so the TestClient must not surface that re-raise.
    return TestClient(app, raise_server_exceptions=False), facade, audit_calls


@pytest.mark.parametrize("capability,method,path,facade_method,_awaited", DARK_ACTIONS)
def test_dark_action_success_envelopes_and_audits(
    dark_client, capability, method, path, facade_method, _awaited
):
    client, facade, audit_calls = dark_client
    response = client.request(method, path)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["message"] == "success"
    assert body["requestId"]
    getattr(facade, facade_method).assert_called_once()
    assert len(audit_calls) == 1
    kwargs = audit_calls[0][1]
    assert kwargs["details"]["capability"] == capability
    assert kwargs["details"]["token_id"] == 42
    assert kwargs["result"] == "success"


@pytest.mark.parametrize("capability,method,path,facade_method,_awaited", DARK_ACTIONS)
def test_dark_action_denied_records_audit(
    dark_client, capability, method, path, facade_method, _awaited
):
    client, facade, audit_calls = dark_client
    getattr(facade, facade_method).side_effect = ForbiddenError("not yours")
    response = client.request(method, path)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert len(audit_calls) == 1
    assert audit_calls[0][1]["result"] == "denied"


@pytest.mark.parametrize("capability,method,path,facade_method,_awaited", DARK_ACTIONS)
def test_dark_action_missing_task_maps_to_404(
    dark_client, capability, method, path, facade_method, _awaited
):
    client, facade, _ = dark_client
    getattr(facade, facade_method).side_effect = AutomationNotFoundError("Automation task not found.")
    response = client.request(method, path)
    assert response.status_code == 404
    assert response.json()["code"] == "AUTOMATION_TASK_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("facade_method", ["delete_task", "cancel_run"])
async def test_async_facade_methods_are_awaited(dark_client, facade_method):
    """Regression: an un-awaited coroutine would be enveloped as a raw value.

    delete_task and cancel_run are async on the facade; the gate must await
    them so the business actually runs and its result is enveloped.
    """
    client, facade, audit_calls = dark_client
    if facade_method == "delete_task":
        response = client.delete("/nb/v1/automations/5")
    else:
        response = client.post("/nb/v1/automations/runs/9/cancel")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data is True or isinstance(data, dict)
    assert not hasattr(data, "__await__")
    getattr(facade, facade_method).assert_awaited_once()


def test_dark_runs_query_returns_envelope(dark_client):
    client, facade, _ = dark_client
    response = client.get("/nb/v1/automations/5/runs")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}
    facade.list_runs.assert_called_once()


def test_dark_declarations_emit_no_gateway_rows():
    """Every action capability above stays enabled=False on its declaration."""
    import management.api.northbound_gates.automations as auto_gates
    from contracts.northbound_exposure import iter_declared_capabilities

    declared = {meta.capability_id: meta for meta, _ in iter_declared_capabilities(auto_gates.nb_automation_router)}
    for capability, _, _, _, _ in DARK_ACTIONS:
        assert declared[capability].enabled is False
    assert declared["automations.runs"].enabled is False
    assert declared["automations.list"].enabled is True
    assert declared["automations.detail"].enabled is True
