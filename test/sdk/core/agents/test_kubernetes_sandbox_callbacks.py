# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from contextvars import ContextVar

import pytest

from nexent.core.agents.sandbox.execution import _ToolBridge
from nexent.core.agents.sandbox_callbacks import SandboxCallbackRegistry
from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def registry():
    return SandboxCallbackRegistry(SandboxOwner('release', 'test', 'runtime', 'uid', '10.0.0.1', 'epoch'))


def test_fixed_bridge_never_starts_a_listener_and_restores_context(registry, mocker):
    listener = mocker.patch('nexent.core.agents.sandbox.execution.ThreadingHTTPServer')
    bridge = _ToolBridge(logging.getLogger(__name__), registry=registry,
                         endpoint='http://10.0.0.1:5014/internal/sandbox/tool-invoke')
    value = ContextVar('value', default='missing')
    value.set('owner-value')
    bridge.register({'read_value': lambda: value.get()})
    try:
        with bridge.execution_context() as execution_id:
            value.set('request-value')
            result = registry.invoke('Bearer ' + bridge._token, {'execution_id': execution_id, 'tool': 'read_value'})
            assert result == 'owner-value'
            code = bridge.proxy_code({'read_value': lambda: None})
            assert 'http://10.0.0.1:5014/internal/sandbox/tool-invoke' in code
        with pytest.raises(ValueError, match='expired'):
            registry.invoke('Bearer ' + bridge._token, {'execution_id': execution_id, 'tool': 'read_value'})
    finally:
        bridge.close()
    listener.assert_not_called()
    with pytest.raises(PermissionError):
        registry.authorize('Bearer ' + bridge._token)


def test_token_is_bound_to_the_process_registry_and_close_is_idempotent(registry):
    other = SandboxCallbackRegistry(registry.owner)
    bridge = _ToolBridge(logging.getLogger(__name__), registry=registry, endpoint='http://10.0.0.1:5014/invoke')
    with pytest.raises(PermissionError):
        other.authorize('Bearer ' + bridge._token)
    with pytest.raises(PermissionError):
        registry.authorize('Bearer ' + bridge._token + 'x')
    bridge.close()
    bridge.close()


def test_closed_context_cannot_invoke_a_tool(registry):
    bridge = _ToolBridge(logging.getLogger(__name__), registry=registry, endpoint='http://10.0.0.1:5014/invoke')
    bridge.register({'call': lambda: 'unexpected'})
    with bridge.execution_context() as execution_id:
        bridge.close()
        with pytest.raises(ValueError, match='expired'):
            bridge._invoke_tool({'execution_id': execution_id, 'tool': 'call'})
