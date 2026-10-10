from __future__ import annotations

import logging
from concurrent.futures import TimeoutError as FutureTimeoutError

import pytest

from nexent.core.agents.managed_mcp import ManagedMCPToolCollection
from nexent.consts.mcp_errors import MCPConnectionTimeoutError


class FakeFuture:
    def __init__(self, *, done=True, timeout=False, result_value=None):
        self._done = done
        self._timeout = timeout
        self._result_value = result_value
        self.cancel_called = False

    def done(self):
        return self._done

    def result(self, timeout=None):
        if self._timeout:
            raise FutureTimeoutError()
        return self._result_value

    def cancel(self):
        self.cancel_called = True
        return True


class FakeExecution:
    def __init__(self, future, execution_id='exec-1'):
        self.execution_id = execution_id
        self.future = future


class FakeManager:
    def __init__(self, future=None):
        self._future = future
        self.submit_calls = []
        self.cancel_calls = []

    def submit(self, lane, spec, fn, *args, **kwargs):
        self.submit_calls.append((lane, spec, fn, args, kwargs))
        future = self._future if self._future is not None else FakeFuture()
        return FakeExecution(future, execution_id='exec-%d' % len(self.submit_calls))

    def cancel(self, execution_id, *, reason=None, wait_timeout=None, mark_stuck_on_timeout=None):
        self.cancel_calls.append({
            'execution_id': execution_id,
            'reason': reason,
            'wait_timeout': wait_timeout,
            'mark_stuck_on_timeout': mark_stuck_on_timeout,
        })


class FakeCancellationScope:
    def __init__(self):
        self.cancelled = False
        self.register_calls = []
        self.unregister_calls = []
        self._token = object()

    def register_closer(self, closer):
        self.register_calls.append(closer)
        return self._token

    def unregister_closer(self, token):
        self.unregister_calls.append(token)


class FakeTool:
    def __init__(self, name, result='ok'):
        self.name = name

        def forward(*args, **kwargs):
            return result

        self.forward = forward


def _make_collection(manager, scope, *, tool_timeout=1.0, close_timeout=1.0, connect_timeout=30.0):
    return ManagedMCPToolCollection(
        manager=manager,
        server_parameters=[],
        cancellation_scope=scope,
        tool_timeout_seconds=tool_timeout,
        close_timeout_seconds=close_timeout,
        connect_timeout_seconds=connect_timeout,
    )


def _assert_timeout_parameter_validation():
    manager = FakeManager()
    scope = FakeCancellationScope()

    with pytest.raises(ValueError, match='MCP tool timeout must be greater than zero'):
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[],
            cancellation_scope=scope,
            tool_timeout_seconds=0,
            close_timeout_seconds=1.0,
            connect_timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match='MCP tool timeout must be greater than zero'):
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[],
            cancellation_scope=scope,
            tool_timeout_seconds=-1.0,
            close_timeout_seconds=1.0,
            connect_timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match='MCP close timeout must be greater than zero'):
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[],
            cancellation_scope=scope,
            tool_timeout_seconds=1.0,
            close_timeout_seconds=0,
            connect_timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match='MCP connect timeout must be greater than zero'):
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[],
            cancellation_scope=scope,
            tool_timeout_seconds=1.0,
            close_timeout_seconds=1.0,
            connect_timeout_seconds=0,
        )


def _assert_tool_call_timeout():
    future = FakeFuture(done=True, timeout=True)
    manager = FakeManager(future=future)
    scope = FakeCancellationScope()
    collection = _make_collection(manager, scope, tool_timeout=1.0)

    tool = FakeTool('search')
    wrapped = collection._wrap_tools([tool])

    with pytest.raises(FutureTimeoutError):
        wrapped[0].forward('query')

    assert collection._close_requested.is_set()

    deadline_cancel = [c for c in manager.cancel_calls if c['reason'] == 'MCP tool deadline exceeded']
    assert len(deadline_cancel) == 1
    assert deadline_cancel[0]['mark_stuck_on_timeout'] is True
    assert deadline_cancel[0]['execution_id'] == 'exec-1'
    assert deadline_cancel[0]['wait_timeout'] == collection.close_timeout_seconds


def _assert_close_timeout():
    future = FakeFuture(done=False, timeout=True)
    manager = FakeManager(future=future)
    scope = FakeCancellationScope()
    collection = _make_collection(manager, scope, close_timeout=2.0)

    collection._execution = FakeExecution(future, execution_id='session-1')
    collection._scope_token = scope._token

    collection.close()

    assert collection._scope_token is None
    assert scope.unregister_calls == [scope._token]

    close_timeout_cancel = [c for c in manager.cancel_calls if c['reason'] == 'MCP session close timed out']
    assert len(close_timeout_cancel) == 1
    assert close_timeout_cancel[0]['mark_stuck_on_timeout'] is True
    assert close_timeout_cancel[0]['execution_id'] == 'session-1'


def _assert_concurrent_close():
    manager = FakeManager()
    scope = FakeCancellationScope()
    collection = _make_collection(manager, scope)

    in_flight = FakeFuture(done=False)
    with collection._active_calls_lock:
        collection._active_calls.add(in_flight)

    collection.request_close()

    assert collection._close_requested.is_set()
    assert in_flight.cancel_called is True

    collection._loop = object()
    fake_session = object()
    with pytest.raises(RuntimeError, match='MCP session is closing'):
        collection._call_tool(fake_session, 'search', {'q': 'x'})


def _assert_startup_timeout():
    future = FakeFuture(done=False, result_value=None)
    manager = FakeManager(future=future)
    scope = FakeCancellationScope()
    collection = _make_collection(manager, scope, connect_timeout=0.02)

    with pytest.raises(MCPConnectionTimeoutError, match='MCP connection timed out'):
        collection.__enter__()

    assert len(scope.register_calls) == 1
    assert scope.unregister_calls == [scope._token]


def _assert_startup_cancelled():
    future = FakeFuture(done=False, result_value=None)
    manager = FakeManager(future=future)
    scope = FakeCancellationScope()
    scope.cancelled = True
    collection = _make_collection(manager, scope, connect_timeout=30.0)

    with pytest.raises(RuntimeError, match='MCP session startup cancelled'):
        collection.__enter__()

    assert scope.unregister_calls == [scope._token]


def _assert_scope_registration():
    future = FakeFuture(done=True, result_value=None)
    manager = FakeManager(future=future)
    scope = FakeCancellationScope()
    collection = _make_collection(manager, scope)
    collection._ready.set()

    public = collection.__enter__()

    assert public is None
    assert len(scope.register_calls) == 1
    assert scope.register_calls[0] == collection.request_close
    assert collection._scope_token is scope._token

    returned = collection.__exit__(None, None, None)

    assert returned is False
    assert collection._scope_token is None
    assert scope.unregister_calls == [scope._token]


def _assert_no_secret_leakage(caplog):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='managed_mcp'):
        future = FakeFuture(done=True, timeout=True)
        manager = FakeManager(future=future)
        scope = FakeCancellationScope()
        collection = _make_collection(manager, scope, tool_timeout=1.0)
        tool = FakeTool('search')
        wrapped = collection._wrap_tools([tool])
        with pytest.raises(FutureTimeoutError):
            wrapped[0].forward('query')

    text = caplog.text
    assert 'event=mcp_tool_timeout' in text
    assert 'search' in text
    lowered = text.lower()
    for secret_word in ('api_key', 'apikey', 'secret', 'password', 'bearer token'):
        assert secret_word not in lowered


@pytest.mark.case_id('UT-SDK-AUTO-E6DDFB4661E0D8B4')
@pytest.mark.stage('D1')
def test_managed_mcp_tool_collection_timeout_and_cancellation_contracts(caplog):
    _assert_timeout_parameter_validation()
    _assert_tool_call_timeout()
    _assert_close_timeout()
    _assert_concurrent_close()
    _assert_startup_timeout()
    _assert_startup_cancelled()
    _assert_scope_registration()
    _assert_no_secret_leakage(caplog)
