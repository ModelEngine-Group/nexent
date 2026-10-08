"""Regressions for resource lifecycle and identity boundaries."""

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from nexent.core.agents.resources.managed_mcp import ManagedMCPToolCollection
from nexent.core.agents.resources.tool_user_context import (
    apply_model_visible_tool_schemas_to_context_items,
    apply_user_context_to_mcp_tool,
)
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager


def _owner(**overrides):
    kwargs = dict(
        manager=MagicMock(), server_parameters=[], cancellation_scope=RunCancellationScope(),
        tool_timeout_seconds=1, close_timeout_seconds=0.5,
    )
    kwargs.update(overrides)
    return ManagedMCPToolCollection(**kwargs)


@pytest.mark.parametrize("field", [
    "tool_timeout_seconds", "close_timeout_seconds", "request_timeout_seconds", "connect_timeout_seconds",
])
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_deadline_cannot_register_or_start_a_session(field, value):
    manager = MagicMock()
    with pytest.raises(ValueError, match="greater than zero"):
        _owner(manager=manager, **{field: value})
    manager.submit.assert_not_called()


def test_legacy_timeout_alias_only_sets_connection_deadline():
    owner = _owner(request_timeout_seconds=8, tool_timeout_seconds=2)
    assert owner.connect_timeout_seconds == 8
    assert owner.tool_timeout_seconds == 2
    assert _owner().connect_timeout_seconds == 30
    assert _owner(request_timeout_seconds=8, connect_timeout_seconds=3).connect_timeout_seconds == 3


def test_submit_failure_unregisters_the_run_closer():
    scope = MagicMock()
    scope.register_closer.return_value = "closer-token"
    manager = MagicMock()
    manager.submit.side_effect = RuntimeError("lane unavailable")
    owner = _owner(manager=manager, cancellation_scope=scope)
    with pytest.raises(RuntimeError, match="lane unavailable"):
        owner.__enter__()
    scope.unregister_closer.assert_called_once_with("closer-token")
    assert owner._scope_token is None


def test_context_startup_error_is_propagated_and_owner_is_cleaned_up():
    manager = ThreadManager("startup-error", {"mcp-session": LanePolicy("mcp-session", 1, 0)})
    manager.start()

    class BrokenContext:
        async def __aenter__(self):
            raise ValueError("invalid MCP handshake")

        async def __aexit__(self, *_args):
            return False

    owner = _owner(manager=manager, server_parameters=[{}], session_context_factory=lambda *_a, **_k: BrokenContext())
    try:
        with pytest.raises(ValueError, match="invalid MCP handshake"):
            owner.__enter__()
        assert owner._scope_token is None
        assert owner._loop is None
        assert owner._session_task is None
    finally:
        asyncio.run(manager.shutdown(timeout=1))


def test_cancelled_startup_never_returns_a_collection():
    scope = MagicMock(cancelled=True)
    owner = _owner(cancellation_scope=scope)
    owner._ready = MagicMock()
    owner._ready.wait.return_value = False
    owner.manager.submit.return_value = SimpleNamespace(future=Future(), execution_id="startup")
    with pytest.raises(RuntimeError, match="startup cancelled"):
        owner.__enter__()
    assert owner._scope_token is None
    scope.unregister_closer.assert_called_once()


def test_close_timeout_marks_execution_stuck_and_unregisters_once(caplog):
    scope = MagicMock()
    owner = _owner(cancellation_scope=scope, close_timeout_seconds=0.001)
    owner._scope_token = "closer-token"
    owner._execution = SimpleNamespace(future=Future(), execution_id="blocked-session")
    owner.close()
    assert "event=mcp_session_close_timeout" in caplog.text
    assert owner.manager.cancel.call_args.kwargs["mark_stuck_on_timeout"] is True
    scope.unregister_closer.assert_called_once_with("closer-token")
    owner.close()
    scope.unregister_closer.assert_called_once()


def test_close_preserves_resource_cleanup_when_execution_failed():
    owner = _owner()
    future = MagicMock()
    future.done.return_value = False
    future.result.side_effect = ValueError("worker failed")
    owner._execution = SimpleNamespace(future=future, execution_id="failed-session")
    owner._scope_token = owner.cancellation_scope.register_closer(owner.request_close)
    owner.close()
    assert owner._scope_token is None
    assert owner._close_requested.is_set()


def test_closed_owner_rejects_tool_call_before_creating_coroutine():
    owner = _owner()
    session = MagicMock()
    with pytest.raises(RuntimeError, match="session is closing"):
        owner._call_tool(session, "tool")
    session.call_tool.assert_not_called()
    owner._loop = MagicMock()
    owner.request_close()
    with pytest.raises(RuntimeError, match="session is closing"):
        owner._call_tool(session, "tool")
    session.call_tool.assert_not_called()


def test_failed_coroutine_submission_does_not_leak_coroutine(monkeypatch):
    owner = _owner()
    owner._loop = MagicMock()
    coroutine = MagicMock()
    session = MagicMock()
    session.call_tool.return_value = coroutine
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", MagicMock(side_effect=RuntimeError("loop stopped")))
    with pytest.raises(RuntimeError, match="loop stopped"):
        owner._call_tool(session, "tool")
    coroutine.close.assert_called_once()
    assert not owner._active_calls


def test_cancelled_scope_rejects_wrapped_tool_before_dispatch():
    scope = RunCancellationScope()
    owner = _owner(cancellation_scope=scope)
    tool = SimpleNamespace(name="lookup", forward=MagicMock())
    owner._wrap_tools([tool])
    scope.cancel()
    with pytest.raises(RuntimeError, match="tool call cancelled"):
        tool.forward()
    owner.manager.submit.assert_not_called()


def test_close_handles_a_stopped_loop_without_losing_cancellation():
    owner = _owner()
    owner._loop = MagicMock()
    owner._loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
    future = Future()
    owner._active_calls.add(future)
    owner.request_close()
    assert future.cancelled()
    assert owner._close_requested.is_set()


def test_default_and_supplied_factories_remain_available_after_relocation():
    import mcpadapt.core
    import mcpadapt.smolagents_adapter

    owner = _owner()
    assert owner._session_factory() is mcpadapt.core.mcptools
    assert isinstance(owner._adapter_factory()(), mcpadapt.smolagents_adapter.SmolAgentsAdapter)
    session_factory = lambda: None
    adapter_factory = lambda: object()
    owner = _owner(session_context_factory=session_factory, tool_adapter_factory=adapter_factory)
    assert owner._session_factory() is session_factory
    assert owner._adapter_factory() is adapter_factory


@pytest.mark.asyncio
async def test_async_tool_discards_spoofed_identity_in_positional_and_keyword_calls():
    observed = []

    async def forward(*args, **kwargs):
        observed.append(args[0] if args else kwargs)
        return "ok"

    tool = SimpleNamespace(inputs={"query": {}, "tenant_id": {}}, forward=forward)
    apply_user_context_to_mcp_tool(tool, {"tenant_id": "trusted-tenant"})
    assert await tool.forward(query="lookup", tenant_id="spoofed") == "ok"
    assert await tool.forward({"query": "lookup", "tenant_id": "spoofed"}) == "ok"
    assert observed == [{"query": "lookup", "tenant_id": "trusted-tenant"}] * 2
    assert tool.inputs == {"query": {}}


def test_uninspectable_forward_still_hides_and_replaces_identity(monkeypatch):
    import inspect

    forward = MagicMock(return_value="ok")
    tool = SimpleNamespace(inputs={"tenant_id": {}}, forward=forward)
    monkeypatch.setattr(inspect, "signature", MagicMock(side_effect=ValueError("uninspectable callable")))
    apply_user_context_to_mcp_tool(tool, {"tenant_id": "trusted"})
    assert tool.forward(tenant_id="spoofed") == "ok"
    forward.assert_called_once_with(tenant_id="trusted")
    assert tool.inputs == {}


def test_foreign_context_object_is_preserved_without_mutation():
    tool = SimpleNamespace(name="lookup", inputs={"query": {}}, _nexent_user_context_wrapped=True)
    content = {"name": "lookup", "inputs": {"query": {}, "tenant_id": {}}}
    foreign = SimpleNamespace(type="tool", content=content)
    result = apply_model_visible_tool_schemas_to_context_items([foreign], [tool])
    assert result == [foreign]
    assert result[0] is foreign
    assert foreign.content is content
    assert "tenant_id" in content["inputs"]
    assert apply_model_visible_tool_schemas_to_context_items(None, [tool]) == []
