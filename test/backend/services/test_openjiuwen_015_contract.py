"""Contract tests against the installed OpenJiuwen 0.1.15 package."""

import asyncio
import inspect
import os
import sys

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

pytest.importorskip("openjiuwen")

from adapters.openjiuwen_compat import (  # noqa: E402
    NEXENT_OPENAI_CLIENT_PROVIDER,
    flatten_message_content,
    load_openjiuwen_public_api,
    validate_openjiuwen_version,
)
from services.agent_runtime.models import (  # noqa: E402
    AgentRunPlan,
    AgentSpec,
    PromptBundle,
    RunControl,
)
from services.agent_runtime.openjiuwen_runtime import OpenJiuwenRuntime  # noqa: E402
from services.agent_runtime.events import RuntimeEventSink, RuntimeEventType  # noqa: E402


def _real_plan() -> AgentRunPlan:
    return AgentRunPlan(
        request_id="contract-run",
        runtime_provider="openjiuwen",
        query="hello",
        history=[
            {
                "role": "user",
                "content": ["first", {"type": "text", "text": " second"}],
            }
        ],
        model_config_list=[
            {
                "cite_name": "main_model",
                "model_name": "gpt-4o-mini",
                "model_factory": "ModelEngine",
                "api_key": "test-key",
                "url": "https://api.example.test/v1",
                "ssl_verify": True,
                "temperature": 0.2,
                "top_p": 0.8,
                "max_output_tokens": 512,
                "timeout_seconds": 45,
                "custom_headers": {"X-Tenant": "tenant-1"},
                "extra_body": {"thinking": {"type": "disabled"}},
            }
        ],
        root_agent=AgentSpec(
            agent_id=1,
            name="root",
            model_name="main_model",
            max_steps=4,
            prompt=PromptBundle(
                fragments={
                    "identity": "Nexent assistant",
                    "duty": "Answer the user.",
                    "runtime_instructions": "Use function tools when needed.",
                },
                rendered_legacy_system_prompt="Use Python and final_answer().",
            ),
        ),
        run_control=RunControl(request_id="contract-run", user_id="user-1"),
    )


def test_openjiuwen_version_and_real_react_config_contract():
    assert str(validate_openjiuwen_version()) == "0.1.15"
    bundle = OpenJiuwenRuntime().to_agent_bundle(_real_plan())

    assert bundle.react_agent_config.model_name == "gpt-4o-mini"
    assert bundle.react_agent_config.model_provider == NEXENT_OPENAI_CLIENT_PROVIDER
    assert bundle.model_request_config.model_name == "gpt-4o-mini"
    assert bundle.model_request_config.max_tokens == 512
    assert bundle.model_request_config.extra_body == {"thinking": {"type": "disabled"}}
    assert bundle.model_client_config.client_provider == NEXENT_OPENAI_CLIENT_PROVIDER
    assert bundle.model_client_config.timeout == 45
    assert bundle.model_client_config.verify_ssl is True
    assert bundle.model_client_config.ssl_cert is None
    assert bundle.history_messages[0].content == "first second"
    prompt = bundle.prompt_template[0]["content"]
    assert "Answer the user." in prompt
    assert "final_answer()" not in prompt


def test_nexent_openai_client_accepts_system_ca_and_flattens_modelengine_content():
    api = load_openjiuwen_public_api()
    plan = _real_plan()
    bundle = OpenJiuwenRuntime().to_agent_bundle(plan)

    client = api.NexentOpenAIModelClient(
        bundle.model_request_config,
        bundle.model_client_config,
    )
    converted = client._convert_messages_to_dict(
        [api.UserMessage(content=[{"text": "hello"}, {"content": " world"}])]
    )

    assert converted == [{"role": "user", "content": "hello world"}]
    assert flatten_message_content(["a", {"text": "b"}]) == "ab"


@pytest.mark.asyncio
async def test_public_context_engine_history_injection_contract():
    api = load_openjiuwen_public_api()
    bundle = OpenJiuwenRuntime().to_agent_bundle(_real_plan())
    session = api.create_agent_session(
        session_id="contract-session",
        card=bundle.agent_card,
    )
    context = await bundle.react_agent.context_engine.create_context(
        session=session,
        history_messages=bundle.history_messages,
    )

    assert [message.content for message in context.get_messages()] == ["first second"]
    await bundle.react_agent.context_engine.clear_context(
        context_id="default_context_id",
        session_id=session.get_session_id(),
    )


def test_runtime_and_prompt_adapter_do_not_install_import_hooks_or_skillutil_path():
    before = tuple(sys.meta_path)
    from adapters import jiuwen_sdk_adapter

    assert tuple(sys.meta_path) == before
    assert jiuwen_sdk_adapter._install_jiuwen_bypasser() is False
    source = inspect.getsource(sys.modules[OpenJiuwenRuntime.__module__])
    assert "openjiuwen.core.skills" not in source
    assert "openjiuwen.core.single_agent.skills" not in source


@pytest.mark.asyncio
async def test_real_react_agent_runs_offline_with_fake_registered_llm(monkeypatch):
    api = load_openjiuwen_public_api()
    from openjiuwen.core.foundation.llm import AssistantMessageChunk, UsageMetadata

    async def fake_stream(self, messages, **kwargs):
        _ = (self, messages, kwargs)
        yield AssistantMessageChunk(
            content="offline answer",
            reasoning_content="offline reasoning",
            finish_reason="stop",
            usage_metadata=UsageMetadata(
                input_tokens=3,
                output_tokens=2,
                total_tokens=5,
            ),
        )

    monkeypatch.setattr(api.NexentOpenAIModelClient, "stream", fake_stream)
    plan = _real_plan().model_copy(update={"history": []})
    sink = RuntimeEventSink(plan.request_id)

    chunks = [chunk async for chunk in OpenJiuwenRuntime().run(plan, sink)]

    assert chunks
    assert any(event.type == RuntimeEventType.MODEL_REASONING for event in sink.events)
    assert any(event.type == RuntimeEventType.MODEL_DELTA for event in sink.events)
    assert any(event.type == RuntimeEventType.TOKEN_COUNT for event in sink.events)
    assert any(
        event.type == RuntimeEventType.FINAL_ANSWER
        and event.content == "offline answer"
        for event in sink.events
    )


@pytest.mark.asyncio
async def test_real_react_agent_propagates_fake_llm_error_as_runtime_error(monkeypatch):
    api = load_openjiuwen_public_api()

    async def failing_stream(self, messages, **kwargs):
        _ = (self, messages, kwargs)
        raise RuntimeError("offline llm failed")
        if False:
            yield None

    monkeypatch.setattr(api.NexentOpenAIModelClient, "stream", failing_stream)
    plan = _real_plan().model_copy(update={"history": []})
    sink = RuntimeEventSink(plan.request_id)

    _ = [chunk async for chunk in OpenJiuwenRuntime().run(plan, sink)]

    assert any(
        event.type == RuntimeEventType.ERROR
        and "offline llm failed" in str(event.error)
        for event in sink.events
    )
    assert not any(event.type == RuntimeEventType.FINAL_ANSWER for event in sink.events)


@pytest.mark.asyncio
async def test_real_react_agent_cancellation_stops_offline_fake_llm(monkeypatch):
    api = load_openjiuwen_public_api()
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()

    async def blocking_stream(self, messages, **kwargs):
        _ = (self, messages, kwargs)
        stream_started.set()
        await release_stream.wait()
        if False:
            yield None

    monkeypatch.setattr(api.NexentOpenAIModelClient, "stream", blocking_stream)
    plan = _real_plan().model_copy(update={"history": []})
    runtime = OpenJiuwenRuntime()
    sink = RuntimeEventSink(plan.request_id)

    async def consume() -> list[object]:
        return [chunk async for chunk in runtime.run(plan, sink)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(stream_started.wait(), timeout=2)
    await runtime.stop(plan.request_id)

    with pytest.raises(asyncio.CancelledError):
        await task
    assert plan.run_control.cancelled is True
    assert any(
        event.type == RuntimeEventType.RUN_FINISHED
        and event.metadata.get("status") == "stopped"
        for event in sink.events
    )
