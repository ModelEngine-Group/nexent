"""Contract tests against the installed OpenJiuwen 0.1.15 package."""

import asyncio
import importlib
import inspect
import os
import sys
import uuid

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
    load_openjiuwen_sandbox_api,
    validate_openjiuwen_version,
)
from services.agent_runtime.models import (  # noqa: E402
    AgentRunPlan,
    AgentSpec,
    PromptBundle,
    RunControl,
)
from services.agent_runtime.openjiuwen_runtime import (  # noqa: E402
    OpenJiuwenRuntime,
    _to_openjiuwen_tool_schema,
)
from services.agent_runtime.events import RuntimeEventSink, RuntimeEventType  # noqa: E402
from skill_tool_schema import (  # noqa: E402
    get_builtin_skill_tool_input_schema,
)


@pytest.fixture(scope="module", autouse=True)
def _restore_real_sqlalchemy_after_backend_test_module_stubs():
    sqlalchemy_module = sys.modules.get("sqlalchemy")
    if sqlalchemy_module is not None and not hasattr(sqlalchemy_module, "__path__"):
        for module_name in list(sys.modules):
            if module_name == "sqlalchemy" or module_name.startswith("sqlalchemy."):
                sys.modules.pop(module_name, None)
    importlib.import_module("sqlalchemy.ext.asyncio")


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


def test_openjiuwen_real_sandbox_import_and_provider_contract():
    api = load_openjiuwen_sandbox_api()

    assert api.OperationMode.SANDBOX.value == "sandbox"
    assert api.ContainerScope.SYSTEM.value == "system"
    assert api.SandboxRegistry.get_provider_cls("aio", "fs") is not None
    assert api.SandboxRegistry.get_provider_cls("aio", "shell") is not None
    assert api.SandboxRegistry.get_provider_cls("aio", "code") is not None
    assert callable(api.Runner.resource_mgr.add_sys_operation)
    assert callable(api.Runner.resource_mgr.remove_sys_operation)


def test_openjiuwen_real_sys_operation_add_remove_contract_without_endpoint_io():
    api = load_openjiuwen_sandbox_api()
    sys_operation_id = f"nexent_contract_{uuid.uuid4().hex}"
    card = api.SysOperationCard(
        id=sys_operation_id,
        mode=api.OperationMode.SANDBOX,
        gateway_config=api.SandboxGatewayConfig(
            isolation=api.SandboxIsolationConfig(
                container_scope=api.ContainerScope.SYSTEM,
                prefix="nexent-contract",
            ),
            launcher_config=api.PreDeployLauncherConfig(
                base_url="http://127.0.0.1:9",
                sandbox_type="aio",
                on_stop="keep",
            ),
            timeout_seconds=1,
        ),
    )

    try:
        add_result = api.Runner.resource_mgr.add_sys_operation(card)

        assert add_result.is_ok()
        assert api.Runner.resource_mgr.get_sys_operation(sys_operation_id) is not None
        generated_cards = api.Runner.resource_mgr.get_sys_op_tool_cards(
            sys_operation_id
        )
        assert generated_cards
        assert any(card.name == "execute_cmd" for card in generated_cards)
    finally:
        remove_result = api.Runner.resource_mgr.remove_sys_operation(
            sys_operation_id=sys_operation_id
        )

    assert remove_result.is_ok()
    assert api.Runner.resource_mgr.get_sys_operation(sys_operation_id) is None


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
async def test_real_local_function_accepts_omitted_builtin_skill_optional_inputs():
    api = load_openjiuwen_public_api()
    calls: list[tuple[str, object]] = []

    async def read_skill_md(
        skill_name: str,
        additional_files: list[str] | None = None,
    ) -> str:
        calls.append((skill_name, additional_files))
        return "skill guide"

    async def run_skill_script(
        skill_name: str,
        script_path: str,
        params: str | None = None,
    ) -> str:
        calls.append((f"{skill_name}:{script_path}", params))
        return "script result"

    read_tool = api.LocalFunction(
        card=api.ToolCard(
            name="read_skill_md",
            input_params=_to_openjiuwen_tool_schema(
                get_builtin_skill_tool_input_schema("read_skill_md")
            ),
        ),
        func=read_skill_md,
    )
    run_tool = api.LocalFunction(
        card=api.ToolCard(
            name="run_skill_script",
            input_params=_to_openjiuwen_tool_schema(
                get_builtin_skill_tool_input_schema("run_skill_script")
            ),
        ),
        func=run_skill_script,
    )

    assert await read_tool.invoke({"skill_name": "csv-data-analyzer"}) == (
        "skill guide"
    )
    assert await read_tool.invoke(
        {
            "skill_name": "csv-data-analyzer",
            "additional_files": [],
        }
    ) == "skill guide"
    assert await read_tool.invoke(
        {
            "skill_name": "csv-data-analyzer",
            "additional_files": ["reference.md"],
        }
    ) == "skill guide"
    assert await run_tool.invoke(
        {
            "skill_name": "csv-data-analyzer",
            "script_path": "scripts/analyze.py",
        }
    ) == "script result"
    assert await run_tool.invoke(
        {
            "skill_name": "csv-data-analyzer",
            "script_path": "scripts/analyze.py",
            "params": "--input sales.csv",
        }
    ) == "script result"
    assert calls == [
        ("csv-data-analyzer", []),
        ("csv-data-analyzer", []),
        ("csv-data-analyzer", ["reference.md"]),
        ("csv-data-analyzer:scripts/analyze.py", None),
        ("csv-data-analyzer:scripts/analyze.py", "--input sales.csv"),
    ]


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
