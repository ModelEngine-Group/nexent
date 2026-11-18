# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.http.server.app_factory import create_app
from contracts.constants import environment
from runtime.api import sandbox

from nexent.core.agents.sandbox.execution import _ToolBridge
from nexent.core.agents.sandbox_callbacks import SandboxCallbackPublicError, SandboxCallbackRegistry
from nexent.core.agents.sandbox_contracts import SandboxOwner
from nexent.core.tools.run_skill_script_tool import SkillScriptExecutionError


@pytest.fixture
def callback(monkeypatch, request):
    registry = SandboxCallbackRegistry(SandboxOwner('release', 'test', 'runtime', 'uid', '10.0.0.1', 'epoch'))
    bridge = _ToolBridge(logging.getLogger(__name__), registry=registry,
                         endpoint='http://10.0.0.1:5014/internal/sandbox/tool-invoke')
    bridge.register({'add': lambda a, b: a + b})
    calls = []

    async def dispatch(lane, spec, fn, *args):
        calls.append((lane, spec))
        return fn(*args)

    monkeypatch.setattr(sandbox, 'current_callback_registry', lambda: registry)
    monkeypatch.setattr(sandbox, 'runtime_thread_manager', SimpleNamespace(run=dispatch))
    if getattr(request, "param", False):
        monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
        monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "sandbox-callback-fixture-signing-key")
        app = create_app(enable_monitoring=False, gateway_identity_audience="runtime")
    else:
        app = FastAPI()
    app.add_api_route("/protected", lambda: {"ok": True}, methods=["POST"])
    app.include_router(sandbox.router)
    with TestClient(app) as client:
        with bridge.execution_context() as execution_id:
            yield client, bridge, execution_id, calls
    bridge.close()


def test_authenticated_callback_dispatches_on_bounded_managed_lane(callback):
    client, bridge, execution_id, calls = callback
    response = client.post('/internal/sandbox/tool-invoke', headers={'Authorization': 'Bearer ' + bridge._token},
                           json={'execution_id': execution_id, 'tool': 'add', 'args': [2, 3]})
    assert response.status_code == 200 and response.json() == {'result': 5}
    assert calls[0][0] == 'sandbox' and calls[0][1].task_name == 'sandbox-host-callback'


def test_invalid_token_and_old_context_do_not_invoke_tool(callback):
    client, bridge, _, calls = callback
    response = client.post('/internal/sandbox/tool-invoke', json={'tool': 'add', 'args': [2, 3]})
    assert response.status_code == 403 and not calls
    response = client.post('/internal/sandbox/tool-invoke', headers={'Authorization': 'Bearer ' + bridge._token},
                           json={'execution_id': 'old', 'tool': 'add', 'args': [2, 3]})
    assert response.status_code == 403


@pytest.mark.parametrize("callback", [True], indirect=True)
def test_gateway_auth_preserves_only_the_exact_sandbox_callback(callback):
    client, bridge, execution_id, calls = callback
    headers = {"Authorization": "Bearer " + bridge._token}
    payload = {"execution_id": execution_id, "tool": "add", "args": [2, 3]}
    path = "/internal/sandbox/tool-invoke"

    assert client.post(path, json=payload).status_code == 403
    assert client.get(path, headers=headers).status_code == 401
    assert client.post("/internal/sandbox/drain", headers=headers).status_code == 401
    assert client.post("/protected", headers=headers).status_code == 401
    assert not calls

    assert client.post(path, headers=headers, json={**payload, "execution_id": "old"}).status_code == 403
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json() == {"result": 5}


@pytest.mark.parametrize('content,status', [('[]', 400), ('{broken', 400), ('x' * (1024 * 1024 + 1), 413)],
                         ids=['not-object', 'invalid-json', 'over-limit'])
def test_callback_body_is_bounded_and_validated_before_dispatch(callback, content, status):
    client, bridge, _, calls = callback
    response = client.post('/internal/sandbox/tool-invoke', headers={'Authorization': 'Bearer ' + bridge._token},
                           content=content)
    assert response.status_code == status and not calls


@pytest.mark.parametrize('error_type', [SandboxCallbackPublicError, SkillScriptExecutionError])
def test_public_business_error_uses_existing_bridge_error_payload(callback, error_type):
    client, bridge, _, _ = callback

    def fail():
        raise error_type('Tool rejected input')

    bridge.register({'fail': fail})
    with bridge.execution_context() as execution_id:
        response = client.post('/internal/sandbox/tool-invoke', headers={'Authorization': 'Bearer ' + bridge._token},
                               json={'execution_id': execution_id, 'tool': 'fail'})
    assert response.status_code == 500 and response.json() == {'error': 'Tool rejected input'}


@pytest.mark.parametrize('error_type', [RuntimeError, ValueError])
def test_unexpected_callback_errors_do_not_expose_exception_text(callback, error_type, caplog):
    client, bridge, _, _ = callback

    def fail():
        raise error_type('private-fixture-value')

    bridge.register({'fail': fail})
    with bridge.execution_context() as execution_id:
        response = client.post('/internal/sandbox/tool-invoke', headers={'Authorization': 'Bearer ' + bridge._token},
                               json={'execution_id': execution_id, 'tool': 'fail'})
    assert response.status_code == 500 and response.json() == {'error': 'Sandbox tool invocation failed'}
    assert error_type.__name__ in caplog.text and 'private-fixture-value' not in caplog.text


def test_removed_drain_route_is_unavailable_even_with_a_callback_capability(callback):
    client, bridge, _, calls = callback
    response = client.post('/internal/sandbox/drain', headers={'Authorization': 'Bearer ' + bridge._token})
    assert response.status_code == 404
    assert calls == []
