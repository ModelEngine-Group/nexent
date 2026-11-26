# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Failure attribution remains safe, localized and independent of recovery."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import ValidationError

from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.errors import failure_error, public_error
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.contracts import ModelError, ToolCall
from nexent.core.model_service.service import ModelServiceError
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def adapter():
    info = AgentRunInfo(
        query="current",
        observer=MessageObserver(lang="zh"),
        stop_event=Event(),
        model_config_list=[],
        agent_config=AgentConfig(
            name="agent",
            description="Fixture",
            model_name="model",
            tools=[
                ToolConfig(name="remote", class_name="Remote", source="mcp"),
                ToolConfig(name="local", class_name="Local", source="local"),
            ],
        ),
    )
    instance = JiuwenAdapter(info)
    instance.tool_configs = list(info.agent_config.tools)
    instance.scope = RunCancellationScope(info.stop_event)
    return instance


@pytest.mark.parametrize("failed", [False, True])
def test_resource_completion_forwards_matched_provider_identity(adapter, mocker, failed):
    """FIX-JW-02: carry event correlation into maintenance on success and error."""
    adapter.context_bridge = mocker.Mock()
    arguments = {"key": "second"}
    adapter.events.calls.append(ToolCall(provider_call_id="provider-second", name="local", index=1,
        raw_arguments=json.dumps(arguments), parsed_arguments=arguments))
    if failed:
        with pytest.raises(ValueError, match="actual failure"):
            with adapter._observe_tool("local", arguments):
                raise ValueError("actual failure")
    else:
        with adapter._observe_tool("local", arguments):
            adapter._resource_result("actual result")
    callback = adapter.context_bridge.completed_tool.call_args
    assert callback.kwargs == {"provider_call_id": "provider-second", "parent_call_id": None}
    assert callback.args[0] == "local"
    assert callback.args[1] == ("Resource failed" if failed else "actual result")
    assert callback.args[2]
    adapter.context_bridge.completed_tool.assert_called_once()


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize(
    "source,prefix",
    [("mcp", "mcp"), ("tool", "tool"), ("sandbox", "sandbox"), ("subagent", "subagent"), ("a2a", "a2a")],
)
def test_failure_origin_is_known_boundary_not_exception_guess(lang, source, prefix):
    error = failure_error(
        httpx.ConnectError("Bearer private-token https://key@host/?api_key=secret"),
        request_id="run",
        lang=lang,
        source=source,
        name="lookup",
    )
    assert error.category.startswith(prefix + "_")
    assert "lookup" in error.safe_message
    assert not any(secret in error.safe_message for secret in ("private-token", "api_key", "secret", "https://"))


def test_model_failure_keeps_normalized_identity_inside_wrapper():
    model = ModelError(
        category="MODEL_AUTHENTICATION_ERROR",
        scope="provider",
        retryable=False,
        safe_message="Model service authentication failed.",
        request_id="provider-request",
    )
    cause = ModelServiceError(model)
    outer = RuntimeError("native wrapper with private data")
    outer.__cause__ = cause
    restored = failure_error(outer, request_id="run", lang="zh", source="mcp")
    assert restored.category == model.category and restored.request_id == "provider-request"
    assert "认证" in public_error(restored, "zh").safe_message
    assert "authentication" in public_error(restored, "en").safe_message


@pytest.mark.parametrize("signal", [asyncio.CancelledError(), RunTerminated(), KeyboardInterrupt()])
def test_control_signals_are_never_execution_failures(signal):
    assert failure_error(signal, request_id="run", source="tool", lang="zh") is None


def test_resource_exception_is_specific_but_does_not_poison_recovery(adapter):
    with pytest.raises(ValueError):
        with adapter._observe_tool("local", {"secret": "hidden"}):
            raise ValueError("private exception payload")
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    failed = next(item for item in events if item["type"] == "tool_result")
    assert failed["is_error"] and failed["error_code"] == "tool_execution_error"
    assert "local" in failed["result"] and "private exception" not in failed["result"]
    adapter.events.emit({"type": "answer", "payload": {"output": "Recovered"}})
    assert adapter.events.finish().status == "completed"


def test_swallowed_resource_failure_survives_native_generic_failure(adapter):
    with pytest.raises(TimeoutError):
        with adapter._observe_tool("remote", {}):
            raise TimeoutError("secret timeout")
    adapter.record_failure(RuntimeError("Jiuwen agent execution failed"))
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_timeout"
    assert "MCP" in result.error.safe_message and "超时" in result.error.safe_message
    assert "secret" not in result.error.safe_message


def test_later_model_failure_takes_precedence_over_recoverable_resource_failure(adapter):
    with pytest.raises(ValueError):
        with adapter._observe_tool("local", {}):
            raise ValueError("private")
    model = ModelError(
        category="MODEL_TIMEOUT",
        scope="transport",
        retryable=True,
        safe_message="The model request timed out.",
        request_id="model-request",
    )
    adapter.record_failure(ModelServiceError(model))
    adapter.record_failure(RuntimeError("cleanup wrapper"), phase="cleanup")
    result = adapter.events.finish("failed")
    assert result.error.category == "MODEL_TIMEOUT" and result.error.request_id == "model-request"


def test_mcp_result_carrier_keeps_exact_payload_and_failure_identity(adapter):
    payload = {"result": '{"success":false,"error":"business rejection"}'}
    with adapter._observe_tool("remote", {}):
        adapter._resource_result(payload)
    adapter.record_failure(RuntimeError("native failure"))
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_execution_error"
    saved = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    tool = next(item for item in saved if item["type"] == "tool_result")
    assert tool["is_error"] and json.loads(tool["result"]) == payload


def test_nested_code_error_preserves_the_actual_resource_origin(adapter):
    with pytest.raises(RuntimeError) as outer:
        with adapter._observe_tool("nexent_execute_python", {}):
            try:
                with adapter._observe_tool("remote", {}):
                    raise ConnectionRefusedError("private endpoint")
            except ConnectionRefusedError as error:
                raise RuntimeError("code executor wrapper") from error
    adapter.record_failure(outer.value)
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_connection_refused"
    assert "remote" in result.error.safe_message and "private" not in result.error.safe_message


@pytest.mark.parametrize(
    "category", ["MODEL_STREAM_INCOMPLETE", "JIUWEN_UNAUTHORIZED_TOOL", "JIUWEN_FINAL_OUTPUT_INVALID"]
)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_internal_protocol_codes_have_readable_messages(category, lang):
    raw = ModelError(category=category, scope="protocol", retryable=False, safe_message=category, request_id="run")
    visible = public_error(raw, lang)
    assert visible.category == category and visible.safe_message != category
    assert raw.safe_message == category


@pytest.mark.parametrize("signal", [asyncio.CancelledError(), RunTerminated()])
def test_cancelled_resource_is_not_a_failed_tool_or_terminal(adapter, signal):
    with pytest.raises(type(signal)):
        with adapter._observe_tool("remote", {}):
            raise signal
    assert adapter.events.resource_error is None
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    assert next(item for item in events if item["type"] == "tool_result")["is_error"] is False
    assert adapter.events.finish("stopped").error is None


@pytest.mark.asyncio
async def test_parallel_resource_errors_keep_their_own_call_ids_and_sources(adapter):
    async def fail(name):
        with adapter._observe_tool(name, {}):
            await asyncio.sleep(0)
            raise ValueError("private")

    results = await asyncio.gather(fail("local"), fail("remote"), return_exceptions=True)
    assert all(isinstance(item, ValueError) for item in results)
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    calls = {item["local_call_id"]: item["tool_name"] for item in events if item["type"] == "tool"}
    failures = {calls[item["local_call_id"]]: item["error_code"] for item in events if item["type"] == "tool_result"}
    assert failures == {"local": "tool_execution_error", "remote": "mcp_execution_error"}


@pytest.mark.parametrize("kind", [FileNotFoundError, PermissionError, ModuleNotFoundError, TypeError])
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_specific_tool_conditions_are_actionable_without_exposing_paths(kind, lang):
    error = failure_error(
        kind("/private/secret.py api_key=private"), request_id="run", source="tool", name="lookup", lang=lang
    )
    assert error.category == "tool_execution_error"
    assert kind.__name__ in error.safe_message or kind is ModuleNotFoundError and "ImportError" in error.safe_message
    assert "private" not in error.safe_message and "secret" not in error.safe_message


def test_wait_for_timeout_cancellation_cause_is_a_deadline_not_user_cancellation():
    timeout = TimeoutError()
    timeout.__cause__ = asyncio.CancelledError()
    outer = RuntimeError("native wrapper")
    outer.__cause__ = timeout
    diagnostic = failure_error(outer, source="mcp", request_id="run", lang="en")
    assert diagnostic.category == "mcp_timeout" and "timed out" in diagnostic.safe_message
    outer.__cause__ = asyncio.CancelledError()
    assert failure_error(outer, source="mcp", request_id="run") is None


@pytest.mark.parametrize("source", ["a2a", "subagent"])
def test_collaborator_failure_keeps_authorized_origin_and_exact_exception(adapter, source):
    child = SimpleNamespace(name="child", invocation_name="delegate")
    if source == "a2a":
        adapter.external_agents = [child]
    else:
        adapter.run_info.agent_config.worker_agents = [child]
    original = ValueError("private collaborator payload")
    with pytest.raises(ValueError) as found:
        with adapter._observe_tool("delegate", {}):
            raise original
    assert found.value is original
    assert adapter.events.resource_error.category == f"{source}_execution_error"
    assert "delegate" in adapter.events.resource_error.safe_message
    assert "private" not in adapter.events.resource_error.safe_message
    assert adapter._active_resource.get() is None


@pytest.mark.parametrize("rejection", [AttributeError, TypeError])
def test_unannotatable_exception_still_records_safe_resource_failure(adapter, rejection):
    class ImmutableError(ValueError):
        def __setattr__(self, name, value):
            if name == "_nexent_resource_error":
                raise rejection("immutable exception")
            super().__setattr__(name, value)

    original = ImmutableError("private tool payload")
    with pytest.raises(ImmutableError) as found:
        with adapter._observe_tool("local", {}):
            raise original
    assert found.value is original
    assert not hasattr(original, "_nexent_resource_error")
    assert adapter.events.resource_error.category == "tool_execution_error"
    assert "private" not in adapter.events.resource_error.safe_message
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    assert next(item for item in events if item["type"] == "tool_result")["is_error"] is True


@pytest.mark.parametrize("signal", [asyncio.CancelledError(), RunTerminated(), SystemExit()])
def test_recording_control_signal_does_not_replace_existing_diagnostic(adapter, signal):
    adapter.record_failure(TimeoutError("private"), source="mcp")
    original = adapter.events.last_error
    adapter.record_failure(signal)
    assert adapter.events.last_error is original
    assert original.category == "mcp_timeout"


def test_generic_execution_wrapper_preserves_specific_protocol_diagnostic(adapter):
    original = adapter.events.error("JIUWEN_UNAUTHORIZED_TOOL")
    adapter.events.record_error(original)
    adapter.record_failure(RuntimeError("private native wrapper"))
    assert adapter.events.last_error is original
    assert adapter.events.finish("failed").error.category == "JIUWEN_UNAUTHORIZED_TOOL"


@pytest.mark.parametrize("carrier", ["plain transport text", {"success": False, "error": "business data"}])
def test_mcp_non_json_or_structured_carrier_is_preserved_without_false_failure(adapter, carrier):
    payload = {"result": carrier}
    with adapter._observe_tool("remote", {}):
        adapter._resource_result(payload)
    assert adapter.events.resource_error is None
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    result = next(item for item in events if item["type"] == "tool_result")
    assert result["is_error"] is False
    assert json.loads(result["result"]) == payload


def test_mcp_startup_failure_is_attributed_before_run_loop_and_reraised(adapter, mocker):
    original = ConnectionRefusedError("private MCP endpoint")
    mocker.patch.object(adapter, "_connect_mcp", side_effect=original)
    loop = mocker.patch("nexent.core.agents.cores.jiuwen.execution_loop.get_execution_loop")
    with pytest.raises(ConnectionRefusedError) as found:
        adapter.run()
    assert found.value is original
    loop.assert_not_called()
    assert adapter._run_completed is False
    diagnostic = adapter.events.finish("failed").error
    assert diagnostic.category == "mcp_connection_refused"
    assert diagnostic.retryable is True
    assert "private" not in diagnostic.safe_message


def test_exception_group_prefers_nested_model_error_and_terminates_on_repeated_members():
    model = ModelError(category="MODEL_TIMEOUT", scope="transport", retryable=True,
                       safe_message="The model request timed out.", request_id="model-request")
    repeated = ValueError("private repeated error")
    nested = ExceptionGroup("private group", [repeated, repeated, ModelServiceError(model)])
    diagnostic = failure_error(nested, source="tool", request_id="run")
    assert diagnostic is model


def test_cyclic_exception_chain_does_not_loop_or_expose_private_messages():
    outer, inner = RuntimeError("private wrapper"), ValueError("private cause")
    outer.__cause__ = inner
    inner.__context__ = outer
    diagnostic = failure_error(outer, source="tool", name="lookup", request_id="run")
    assert diagnostic.category == "tool_execution_error"
    assert diagnostic.request_id == "run" and diagnostic.retryable is False
    assert "lookup" in diagnostic.safe_message and "private" not in diagnostic.safe_message


@pytest.mark.parametrize("lang,expected", [("zh-CN", "模型输出格式"), ("en", "output format")])
def test_unknown_protocol_code_keeps_identity_with_safe_localized_fallback(lang, expected):
    original = ModelError(category="JIUWEN_FUTURE_PROTOCOL", scope="protocol", retryable=False,
                          safe_message="JIUWEN_FUTURE_PROTOCOL", request_id="run")
    diagnostic = public_error(original, lang)
    assert diagnostic.category == original.category and diagnostic.request_id == "run"
    assert expected in diagnostic.safe_message and diagnostic.retryable is False
    assert original.safe_message == "JIUWEN_FUTURE_PROTOCOL"


@pytest.mark.parametrize("source", ["tool", "mcp"])
@pytest.mark.parametrize("lang,expected", [("zh", "参数不符合"), ("en", "do not match")])
def test_schema_error_is_nonretryable_and_does_not_publish_validation_payload(source, lang, expected):
    diagnostic = failure_error(ValidationError("private input and schema"), source=source,
                               name="lookup", request_id="run", lang=lang)
    assert diagnostic.category == f"{source}_invalid_arguments"
    assert diagnostic.retryable is False and diagnostic.request_id == "run"
    assert expected in diagnostic.safe_message and "private" not in diagnostic.safe_message
