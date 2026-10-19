"""Regression coverage for history replay at the native model boundary."""

import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentHistory,
    AgentRunInfo,
    ModelConfig,
)
from nexent.core.agents.core_adapters.jiuwen import (
    JiuwenAdapter,
    _prepend_context_messages,
)
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.model_service.contracts import AssistantMessage as ServiceMessage
from nexent.core.model_service.contracts import ModelEvent
from nexent.core.utils.observer import MessageObserver
from openjiuwen.core.foundation.llm.model_clients.base_model_client import (
    BaseModelClient,
)
from openjiuwen.core.foundation.llm.schema.message import (
    AssistantMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from test_jiuwen_model_service import saved_profile as _saved_profile

saved_profile = _saved_profile


def adapter_with_history(history, profile):
    info = AgentRunInfo(
        query="Current question", observer=MessageObserver(lang="en"), stop_event=Event(),
        agent_config=AgentConfig(name="history", description="History fixture", model_name="fixture", tools=[]),
        tenant_id="tenant",
        model_config_list=[ModelConfig(cite_name="fixture", model_name=profile.identity.request_model_id,
                                      url=profile.connection.base_url, resolved_profile=profile)],
        history=history,
    )
    adapter = JiuwenAdapter(info)
    adapter.validate()
    adapter.scope = RunCancellationScope(info.stop_event)
    adapter._compile_context()
    return adapter


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("dictionary_input", [False, True])
async def test_history_reaches_native_model_in_order(monkeypatch, streaming, dictionary_input, saved_profile):
    adapter = adapter_with_history([
        AgentHistory(role="user", content="Remember blue"),
        AgentHistory(role="assistant", content="I remember blue"),
    ], saved_profile)
    captured = []

    result = ServiceMessage(content_parts=[{"type": "text", "text": "answer"}], finish_reason="stop")

    def capture(request):
        roles = {"application_instruction": "system", "user_input": "user", "assistant_history": "assistant"}
        captured.extend({"role": roles[item.semantic_role], "content": item.content_parts[0]["text"]}
                        for item in request.messages)

    async def invoke(request, profile, **kwargs):
        capture(request)
        return result

    @asynccontextmanager
    async def stream(request, profile, **kwargs):
        capture(request)
        async def events():
            yield ModelEvent(request_id=request.request_id, message_id=result.message_id, sequence=1,
                             type="message_completed", message=result, finish_reason="stop")
        yield events()

    adapter.run_info.model_service = SimpleNamespace(ainvoke=invoke, astream=stream)
    messages = [SystemMessage(content="Business instructions"), UserMessage(content="Current question")]
    if dictionary_input:
        messages = [message.model_dump() for message in messages]
    model = adapter._create_model()
    if streaming:
        assert "".join([chunk.content async for chunk in model.stream(messages)]) == "answer"
    else:
        assert (await model.invoke(messages)).content == "answer"
    assert [(message["role"], message["content"]) for message in captured] == [
        ("system", "Business instructions"), ("user", "Remember blue"),
        ("assistant", "I remember blue"), ("user", "Current question"),
    ]
    assert len(messages) == 2


async def test_empty_history_keeps_native_input(monkeypatch, saved_profile):
    adapter = adapter_with_history([], saved_profile)
    messages = [SystemMessage(content="Instructions"), UserMessage(content="New question")]

    async def invoke(request, profile, **kwargs):
        assert [item.content_parts[0]["text"] for item in request.messages] == ["Instructions", "New question"]
        raise RuntimeError("Provider unavailable")

    adapter.run_info.model_service = SimpleNamespace(ainvoke=invoke)
    with pytest.raises(RuntimeError, match="Provider unavailable"):
        await adapter._create_model().invoke(messages)


@pytest.mark.parametrize("dictionary_input", [False, True])
def test_history_preserves_native_tool_calls_and_structured_content(dictionary_input):
    assistant = AssistantMessage(content="", tool_calls=[
        {"id": "call-1", "type": "function", "function": {"name": "add", "arguments": '{"a": 2}'}}
    ], reasoning_content="Tool reasoning")
    tool = ToolMessage(content="2", tool_call_id="call-1")
    prefix = [{"role": "user", "content": [{"type": "text", "text": "Earlier question"}]}]
    messages = [SystemMessage(content="Instructions"), assistant, tool]
    if dictionary_input:
        messages = [message.model_dump() for message in messages]
    original = deepcopy(messages)
    actual = _prepend_context_messages(messages, prefix)
    serialized = BaseModelClient._convert_messages_to_dict(actual)
    assert serialized[1]["content"] == prefix[0]["content"]
    assert serialized[2]["tool_calls"][0]["id"] == "call-1"
    assert serialized[2]["reasoning_content"] == "Tool reasoning"
    assert serialized[3]["tool_call_id"] == "call-1"
    assert messages == original
    if not dictionary_input:
        assert actual[2] is assistant and actual[3] is tool


def test_native_prompt_and_retry_configuration(monkeypatch, saved_profile):
    from nexent.core.agents.core_adapters import jiuwen

    adapter = adapter_with_history([AgentHistory(role="user", content="Analyze an old image")], saved_profile)
    adapter.run_info.thread_manager = SimpleNamespace()
    monkeypatch.setattr(adapter, "_skill_rails", list)
    monkeypatch.setattr(jiuwen, "NexentAgent", lambda **kwargs: SimpleNamespace(
        _prepare_file_workspace=lambda query: query,
    ))
    factory = Mock()
    factory_module = ModuleType("openjiuwen.harness.factory")
    factory_module.create_deep_agent = factory
    monkeypatch.setitem(sys.modules, "openjiuwen.harness.factory", factory_module)
    retry_rail = SimpleNamespace()
    retry_factory = Mock(return_value=retry_rail)
    retry_module = ModuleType("openjiuwen.harness.rails.model_anomaly_detection_rail")
    retry_module.ModelAnomalyDetectionRail = retry_factory
    monkeypatch.setitem(sys.modules, retry_module.__name__, retry_module)
    adapter.prepare()
    options = factory.call_args.kwargs
    assert "only the latest user request" in options["system_prompt"]
    assert "not pending tasks" in options["system_prompt"]
    assert "Do not repeat earlier requests or tool calls" in options["system_prompt"]
    assert options["enable_model_anomaly_detection_rail"] is False
    assert options["enable_tool_resilience_rail"] is False
    assert options["enable_skill_discovery"] is False
    assert options["rails"] == []
    assert options["parallel_tool_calls"] is False
    retry_factory.assert_not_called()
