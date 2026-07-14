import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.events import RuntimeEventSink, RuntimeEventType
from services.agent_runtime.models import (
    AgentRunPlan,
    AgentSpec,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    PromptBundle,
    RunControl,
    ToolSource,
    ToolSpec,
)
from services.agent_runtime.openjiuwen_runtime import (
    OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY,
    OpenJiuwenRuntime,
    OpenJiuwenRuntimeDependencies,
    OpenJiuwenUnsupportedFeatureError,
    _to_openjiuwen_tool_schema,
)
from services.agent_runtime.tool_factory import ToolFactoryRegistry
from skill_tool_schema import get_builtin_skill_tool_input_schema


@dataclass
class FakeModelRequestConfig:
    values: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any):
        self.values = dict(kwargs)


@dataclass
class FakeModelClientConfig:
    values: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any):
        self.values = dict(kwargs)


@dataclass
class FakeContextEngineConfig:
    values: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any):
        self.values = dict(kwargs)


@dataclass
class FakeReActAgentConfig:
    model_config_obj: Any
    model_client_config: Any
    prompt_template: list[dict[str, Any]]
    max_iterations: int
    context_engine_config: Any = None
    model_name: str = ""
    model_provider: str = ""


@dataclass
class FakeAgentCard:
    id: str
    name: str = ""
    description: str = ""


@dataclass
class FakeToolCard:
    id: str
    name: str
    description: str = ""
    input_params: dict[str, Any] = field(default_factory=dict)
    stateless: bool = False


class FakeLocalFunction:
    def __init__(self, card: FakeToolCard, func):
        self.card = card
        self.func = func

    async def invoke(self, inputs: dict[str, Any]) -> Any:
        return await self.func(**inputs)


@dataclass
class FakeMcpServerConfig:
    server_id: str
    server_name: str
    server_path: str
    client_type: str = "sse"
    params: dict[str, Any] = field(default_factory=dict)
    auth_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeMessage:
    content: Any = ""
    role: str = "user"


class FakeUserMessage(FakeMessage):
    def __init__(self, content: Any = ""):
        super().__init__(content=content, role="user")


class FakeAssistantMessage(FakeMessage):
    def __init__(self, content: Any = ""):
        super().__init__(content=content, role="assistant")


class FakeSystemMessage(FakeMessage):
    def __init__(self, content: Any = ""):
        super().__init__(content=content, role="system")


class FakeAbilityManager:
    def __init__(self):
        self.abilities: list[Any] = []

    def add(self, ability: Any) -> None:
        self.abilities.append(ability)


class FakeContext:
    def __init__(self):
        self.messages: list[Any] = []

    async def add_messages(self, messages: list[Any]) -> list[Any]:
        self.messages.extend(messages)
        return messages


class FakeSession:
    def __init__(self, session_id: str, card: Any = None):
        self.session_id = session_id
        self.card = card
        self.post_run_called = False

    def get_session_id(self) -> str:
        return self.session_id

    async def post_run(self) -> None:
        self.post_run_called = True


class FakeContextEngine:
    def __init__(self, config: Any = None):
        self.config = config
        self.contexts: dict[str, FakeContext] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.clear_calls: list[dict[str, Any]] = []

    async def create_context(
        self,
        context_id: str = "default_context_id",
        session: FakeSession | None = None,
        *,
        history_messages: list[Any] | None = None,
        **_: Any,
    ) -> FakeContext:
        session_id = session.get_session_id() if session else "default"
        key = f"{session_id}:{context_id}"
        context = self.contexts.setdefault(key, FakeContext())
        if history_messages and not context.messages:
            await context.add_messages(history_messages)
        self.create_calls.append(
            {
                "context_id": context_id,
                "session": session,
                "history_messages": list(history_messages or []),
            }
        )
        return context

    async def clear_context(self, context_id: str, session_id: str) -> None:
        self.clear_calls.append({"context_id": context_id, "session_id": session_id})
        self.contexts.pop(f"{session_id}:{context_id}", None)


class FakeReActAgent:
    instances: list["FakeReActAgent"] = []
    stream_chunks: list[Any] = []
    block_event: asyncio.Event | None = None
    stream_started: asyncio.Event | None = None

    def __init__(self, card: FakeAgentCard):
        self.card = card
        self.ability_manager = FakeAbilityManager()
        self.config = None
        self.stream_inputs = None
        self.context = FakeContext()
        self.context_engine = FakeContextEngine()
        self.prompt_sections: list[dict[str, Any]] = []
        FakeReActAgent.instances.append(self)

    def configure(self, config: FakeReActAgentConfig) -> "FakeReActAgent":
        self.config = config
        return self

    async def _init_context(self, session: Any) -> FakeContext:
        return await self.context_engine.create_context(session=session)

    async def stream(self, inputs: dict[str, Any], session: Any = None):
        self.stream_inputs = dict(inputs)
        if FakeReActAgent.stream_started is not None:
            FakeReActAgent.stream_started.set()
        if FakeReActAgent.block_event is not None:
            await FakeReActAgent.block_event.wait()
        for chunk in FakeReActAgent.stream_chunks:
            yield chunk

    def add_prompt_builder_section(
        self, name: str, content: str, *, priority: int
    ) -> None:
        self.prompt_sections.append(
            {
                "name": name,
                "content": content,
                "priority": priority,
            }
        )


@dataclass
class FakeLocalWorkConfig:
    sandbox_root: list[str] | None = None
    restrict_to_sandbox: bool = False
    shell_allowlist: list[str] | None = None


class FakeOperationMode:
    LOCAL = "local"


@dataclass
class FakeSysOperationCard:
    id: str
    name: str = ""
    description: str = ""
    mode: str = "local"
    work_config: FakeLocalWorkConfig | None = None

    @staticmethod
    def generate_tool_id(
        sys_operation_id: str, operation_name: str, tool_name: str
    ) -> str:
        return f"{sys_operation_id}.{operation_name}.{tool_name}"


class FakeSkillUtil:
    instances: list["FakeSkillUtil"] = []

    def __init__(self, sys_operation_id: str):
        self.sys_operation_id = sys_operation_id
        self.register_calls: list[dict[str, Any]] = []
        FakeSkillUtil.instances.append(self)

    async def register_skills(
        self, skill_path: str, agent: Any, session_id: str | None = None
    ) -> bool:
        self.register_calls.append(
            {
                "skill_path": skill_path,
                "agent": agent,
                "session_id": session_id,
            }
        )
        return True

    def get_skill_prompt(self) -> str:
        return "Native skill prompt with read_file."


class FakeResult:
    def __init__(self, ok: bool, message: str = ""):
        self.ok = ok
        self.message = message

    def is_ok(self) -> bool:
        return self.ok

    def msg(self) -> str:
        return self.message


class FakeResourceManager:
    def __init__(self):
        self.added_mcp_servers: list[Any] = []
        self.removed_mcp_servers: list[dict[str, Any]] = []
        self.added_tools: list[Any] = []
        self.removed_tools: list[Any] = []
        self.added_sys_operations: list[Any] = []
        self.removed_sys_operations: list[str] = []
        self.mcp_tool_requests: list[dict[str, Any]] = []
        self.add_mcp_server_result: Any = None

    async def add_mcp_server(
        self, server_config: Any, *, expiry_time: float | None = None
    ) -> None:
        self.added_mcp_servers.append((server_config, expiry_time))
        return self.add_mcp_server_result

    async def get_mcp_tool(self, name: str, server_id: str, **_: Any) -> list[Any]:
        self.mcp_tool_requests.append({"name": name, "server_id": server_id})

        class FakeMcpTool:
            def __init__(self):
                self.name = name

            async def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
                return {"name": name, "server_id": server_id, "inputs": inputs}

        return [FakeMcpTool()]

    async def remove_mcp_server(self, **kwargs: Any) -> None:
        self.removed_mcp_servers.append(dict(kwargs))

    def add_tool(self, tool: Any, **kwargs: Any) -> None:
        self.added_tools.append((tool, kwargs))

    def remove_tool(self, **kwargs: Any) -> None:
        self.removed_tools.append(dict(kwargs))

    def add_sys_operation(self, card: Any) -> None:
        self.added_sys_operations.append(card)

    def get_sys_op_tool_cards(
        self, sys_operation_id: str, **kwargs: Any
    ) -> FakeToolCard:
        return FakeToolCard(
            id=f"{sys_operation_id}.fs.read_file",
            name="read_file",
            description="Read a file",
        )

    def remove_sys_operation(self, sys_operation_id: str) -> None:
        self.removed_sys_operations.append(sys_operation_id)


class FakeRunner:
    resource_mgr = FakeResourceManager()


@pytest.fixture(autouse=True)
def reset_fake_openjiuwen_state():
    FakeReActAgent.instances = []
    FakeReActAgent.stream_chunks = []
    FakeReActAgent.block_event = None
    FakeReActAgent.stream_started = None
    FakeSkillUtil.instances = []
    FakeRunner.resource_mgr = FakeResourceManager()


@pytest.fixture
def openjiuwen_dependencies() -> OpenJiuwenRuntimeDependencies:
    return OpenJiuwenRuntimeDependencies(
        AgentCard=FakeAgentCard,
        ReActAgentConfig=FakeReActAgentConfig,
        ReActAgent=FakeReActAgent,
        ModelRequestConfig=FakeModelRequestConfig,
        ModelClientConfig=FakeModelClientConfig,
        McpServerConfig=FakeMcpServerConfig,
        ToolCard=FakeToolCard,
        LocalFunction=FakeLocalFunction,
        ContextEngineConfig=FakeContextEngineConfig,
        Runner=FakeRunner,
        UserMessage=FakeUserMessage,
        AssistantMessage=FakeAssistantMessage,
        SystemMessage=FakeSystemMessage,
        SkillUtil=FakeSkillUtil,
        SysOperationCard=FakeSysOperationCard,
        LocalWorkConfig=FakeLocalWorkConfig,
        OperationMode=FakeOperationMode,
        ContextEngine=FakeContextEngine,
        create_agent_session=lambda session_id, card=None: FakeSession(
            session_id, card
        ),
    )


class FakeFactory:
    name = "fake"

    def supports(self, tool: ToolSpec, context) -> bool:
        return True

    def create(self, tool: ToolSpec, context):
        def call_tool(**kwargs: Any) -> dict[str, Any]:
            return {
                "tool": tool.name,
                "kwargs": kwargs,
                "card": {"title": tool.name},
                "search_content": [{"title": "source"}],
                "picture_web": ["https://example.test/image.png"],
            }

        call_tool.name = tool.name
        return call_tool


def _tool_registry() -> ToolFactoryRegistry:
    registry = ToolFactoryRegistry()
    for source in (
        ToolSource.LOCAL,
        ToolSource.KNOWLEDGE,
        ToolSource.MEMORY,
        ToolSource.SKILL,
        ToolSource.PLUGIN,
    ):
        registry.register(source, FakeFactory())
    return registry


def _model_config() -> dict[str, Any]:
    return {
        "cite_name": "main_model",
        "model_name": "gpt-4o",
        "model_factory": "OpenAI",
        "api_key": "explicit-key",
        "url": "https://api.example/v1",
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 384000,
        "max_output_tokens": 1024,
        "ssl_verify": False,
        "custom_headers": {"X-Tenant": "tenant-1"},
    }


def _plan(**overrides: Any) -> AgentRunPlan:
    root_agent = overrides.pop(
        "root_agent",
        AgentSpec(
            agent_id=1,
            name="root",
            description="Root agent",
            model_name="main_model",
            max_steps=7,
            prompt=PromptBundle(
                fragments={
                    "duty": "Answer user questions.",
                    "skills": [{"name": "writer", "description": "Write files"}],
                    "memory": "Known user preference.",
                },
            ),
            tools=[],
            context_policy=ContextPolicy(mode=ContextMode.LEGACY),
        ),
    )
    run_control = overrides.pop(
        "run_control",
        RunControl(
            request_id="req-1",
            user_id="user-1",
            conversation_id=100,
            metadata={"tenant_id": "tenant-1"},
        ),
    )
    payload = {
        "request_id": "req-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN,
        "query": "hello",
        "history": [{"role": "user", "content": "previous question"}],
        "model_config_list": [_model_config()],
        "root_agent": root_agent,
        "mcp_connections": [],
        "runtime_resources": {},
        "monitoring_metadata": {},
        "run_control": run_control,
    }
    payload.update(overrides)
    return AgentRunPlan(**payload)


def test_openjiuwen_capabilities_match_initial_spike_contract():
    runtime = OpenJiuwenRuntime()

    assert runtime.capabilities.streaming is True
    assert runtime.capabilities.token_streaming is True
    assert runtime.capabilities.reasoning_streaming is True
    assert runtime.capabilities.mcp is True
    assert runtime.capabilities.tool_call_events is True
    assert runtime.capabilities.token_usage_events is True
    assert runtime.capabilities.tool_artifacts is True
    assert runtime.capabilities.interruptible is True
    assert runtime.capabilities.managed_agents is False
    assert runtime.capabilities.external_a2a_agents is False
    assert runtime.capabilities.code_execution is False
    assert runtime.capabilities.context_compression is False
    assert runtime.capabilities.resumable_stream is False
    assert runtime.capabilities.process_type_compatibility == "partial"


def test_openjiuwen_process_type_coverage_matrix_lists_all_legacy_process_types():
    assert set(OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY) == {
        "agent_new_run",
        "agent_finish",
        "card",
        "error",
        "execution_logs",
        "final_answer",
        "max_steps_reached",
        "memory_search",
        "model_output_code",
        "model_output_deep_thinking",
        "model_output_thinking",
        "other",
        "parse",
        "picture_web",
        "search_content",
        "step_count",
        "token_count",
        "tool",
        "verification",
    }
    assert OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY["model_output_code"] == "no-op"
    assert OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY["tool"] == "complete"


def test_openjiuwen_tool_schema_converts_builtin_skill_shorthand():
    schema = _to_openjiuwen_tool_schema(
        {
            "skill_name": "str",
            "script_path": "str",
            "params": "dict",
            "additional_files": "list[str]",
        }
    )

    assert schema == {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "script_path": {"type": "string"},
            "params": {"type": "object"},
            "additional_files": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "skill_name",
            "script_path",
            "params",
            "additional_files",
        ],
    }


def test_openjiuwen_tool_schema_preserves_builtin_skill_optional_defaults():
    read_skill_schema = _to_openjiuwen_tool_schema(
        get_builtin_skill_tool_input_schema("read_skill_md")
    )
    run_skill_schema = _to_openjiuwen_tool_schema(
        get_builtin_skill_tool_input_schema("run_skill_script")
    )

    assert read_skill_schema["required"] == ["skill_name"]
    assert read_skill_schema["properties"]["additional_files"] == {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
    }
    assert run_skill_schema["required"] == ["skill_name", "script_path"]
    assert run_skill_schema["properties"]["params"] == {
        "type": ["string", "null"],
        "default": None,
    }


def test_agent_model_prompt_and_history_mapping_do_not_read_env(
    monkeypatch, openjiuwen_dependencies
):
    def fail_getenv(*args: Any, **kwargs: Any):
        raise AssertionError("OpenJiuwenRuntime must not read env directly")

    monkeypatch.setattr(os, "getenv", fail_getenv)
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    bundle = runtime.to_agent_bundle(_plan())

    assert bundle.agent_card.id == "1"
    assert bundle.agent_card.name == "root"
    assert bundle.react_agent_config.max_iterations == 7
    assert bundle.model_request_config.values == {
        "model": "gpt-4o",
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 1024,
    }
    assert bundle.model_client_config.values == {
        "client_provider": "NexentOpenAI",
        "api_key": "explicit-key",
        "api_base": "https://api.example/v1",
        "timeout": 60.0,
        "verify_ssl": False,
        "custom_headers": {"X-Tenant": "tenant-1"},
    }
    system_prompt = bundle.prompt_template[0]["content"]
    assert "Answer user questions." in system_prompt
    assert "writer" in system_prompt
    assert isinstance(bundle.history_messages[0], FakeUserMessage)


@pytest.mark.asyncio
async def test_history_is_injected_once_through_agent_owned_context(
    openjiuwen_dependencies,
):
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    FakeReActAgent.stream_chunks = [
        {"type": "answer", "payload": {"output": "done", "result_type": "answer"}}
    ]

    _ = [chunk async for chunk in runtime.run(_plan(), RuntimeEventSink("req-1"))]

    context_engine = FakeReActAgent.instances[-1].context_engine
    seeded_calls = [
        call for call in context_engine.create_calls if call["history_messages"]
    ]
    assert len(seeded_calls) == 1
    assert [message.content for message in seeded_calls[0]["history_messages"]] == [
        "previous question"
    ]
    assert context_engine.clear_calls == [
        {"context_id": "default_context_id", "session_id": "req-1:session:root"}
    ]


@pytest.mark.asyncio
async def test_runtime_lifecycle_logs_do_not_include_sensitive_payloads(
    caplog,
    openjiuwen_dependencies,
):
    caplog.set_level(
        logging.DEBUG,
        logger="services.agent_runtime.openjiuwen_runtime",
    )
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    FakeReActAgent.stream_chunks = [
        {"type": "answer", "payload": {"output": "done", "result_type": "answer"}}
    ]
    model_config = {
        **_model_config(),
        "model_name": "gpt-log",
        "api_key": "secret-api-key",
        "custom_headers": {"Authorization": "Bearer secret-token"},
    }

    _ = [
        chunk
        async for chunk in runtime.run(
            _plan(
                query="secret-query",
                history=[{"role": "user", "content": "secret-history"}],
                model_config_list=[model_config],
            ),
            RuntimeEventSink("req-1"),
        )
    ]

    messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "services.agent_runtime.openjiuwen_runtime"
    )
    assert "OpenJiuwen runtime run starting" in messages
    assert "OpenJiuwen agent bundle created" in messages
    assert "OpenJiuwen runtime run finished" in messages
    assert "model_name=gpt-log" in messages
    assert "secret-query" not in messages
    assert "secret-history" not in messages
    assert "secret-api-key" not in messages
    assert "secret-token" not in messages


@pytest.mark.asyncio
async def test_stop_logs_missing_active_openjiuwen_run(caplog, openjiuwen_dependencies):
    caplog.set_level(
        logging.DEBUG,
        logger="services.agent_runtime.openjiuwen_runtime",
    )
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    await runtime.stop("missing-request")

    assert any(
        "OpenJiuwen runtime stop ignored" in record.getMessage()
        and "request_id=missing-request" in record.getMessage()
        for record in caplog.records
    )


def test_runtime_native_context_window_maps_to_context_engine_config(
    openjiuwen_dependencies,
):
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    plan = _plan(
        root_agent=AgentSpec(
            agent_id=1,
            name="root",
            model_name="main_model",
            max_steps=3,
            prompt=PromptBundle(
                fragments={"duty": "system"},
                rendered_legacy_system_prompt="legacy code-agent system",
            ),
            context_policy=ContextPolicy(mode=ContextMode.RUNTIME_NATIVE),
            runtime_hints={
                "context_engine": {
                    "max_context_message_num": 20,
                    "default_window_message_num": 8,
                    "default_window_round_num": 4,
                    "context_window_tokens": 4096,
                }
            },
        )
    )

    bundle = runtime.to_agent_bundle(plan)

    assert bundle.context_engine_config.values == {
        "max_context_message_num": 20,
        "default_window_message_num": 8,
        "default_window_round_num": 4,
        "context_window_tokens": 4096,
        "model_name": "main_model",
    }


@pytest.mark.asyncio
async def test_run_maps_stream_chunks_to_runtime_events(openjiuwen_dependencies):
    FakeReActAgent.stream_chunks = [
        {"type": "llm_output", "payload": {"content": "hello"}},
        {"type": "llm_reasoning", "payload": {"content": "because"}},
        {
            "type": "llm_usage",
            "payload": {"usage_metadata": {"input_tokens": 1, "output_tokens": 2}},
        },
        {"type": "answer", "payload": {"output": "done", "result_type": "answer"}},
    ]
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    sink = RuntimeEventSink(request_id="req-1")

    chunks = [chunk async for chunk in runtime.run(_plan(), sink)]

    assert chunks == FakeReActAgent.stream_chunks
    assert [event.type for event in sink.events] == [
        RuntimeEventType.RUN,
        RuntimeEventType.STEP,
        RuntimeEventType.MODEL_DELTA,
        RuntimeEventType.MODEL_REASONING,
        RuntimeEventType.TOKEN_COUNT,
        RuntimeEventType.FINAL_ANSWER,
        RuntimeEventType.RUN_FINISHED,
    ]
    assert sink.events[2].delta == "hello"
    assert sink.events[3].reasoning == "because"
    assert sink.events[4].token_usage == {"input_tokens": 1, "output_tokens": 2}
    assert sink.events[5].content == "done"
    assert _plan().monitoring_metadata.get("openjiuwen.process_type_coverage") is None


@pytest.mark.asyncio
async def test_run_does_not_emit_user_visible_noop_diagnostic(openjiuwen_dependencies):
    FakeReActAgent.stream_chunks = [
        {"type": "llm_output", "payload": {"content": "hello"}},
        {"type": "answer", "payload": {"output": "done", "result_type": "answer"}},
    ]
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    sink = RuntimeEventSink(request_id="req-1")

    _ = [chunk async for chunk in runtime.run(_plan(), sink)]

    assert not any(event.compat_process_type == "other" for event in sink.events)


def test_error_answer_maps_to_error_instead_of_final_answer(openjiuwen_dependencies):
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    event = runtime.runtime_event_from_openjiuwen_chunk(
        {
            "type": "answer",
            "payload": {"output": "model failed", "result_type": "error"},
        },
        request_id="req-1",
        agent_name="root",
    )

    assert event.type == RuntimeEventType.ERROR
    assert event.error == "model failed"


def test_max_iterations_answer_maps_to_max_steps(openjiuwen_dependencies):
    event = OpenJiuwenRuntime(
        dependencies=openjiuwen_dependencies
    ).runtime_event_from_openjiuwen_chunk(
        {
            "type": "answer",
            "payload": {
                "output": "Max iterations reached before a final answer",
                "result_type": "answer",
            },
        },
        request_id="req-1",
        agent_name="root",
    )

    assert event.type == RuntimeEventType.MAX_STEPS


@pytest.mark.asyncio
async def test_mcp_connection_uses_request_scoped_id_and_cleans_up(
    openjiuwen_dependencies,
):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    runtime = OpenJiuwenRuntime(
        dependencies=openjiuwen_dependencies, mcp_expiry_time=600
    )
    plan = _plan(
        mcp_connections=[
            MCPConnectionConfig(
                name="docs server",
                url="https://mcp.example/mcp",
                transport="streamable-http",
                headers={"Authorization": "Bearer token"},
            )
        ],
    )

    _ = [chunk async for chunk in runtime.run(plan, RuntimeEventSink("req-1"))]

    mcp_config, expiry_time = FakeRunner.resource_mgr.added_mcp_servers[0]
    assert mcp_config.server_id == "req-1:mcp:docs_server"
    assert mcp_config.server_name == "docs server"
    assert mcp_config.server_path == "https://mcp.example/mcp"
    assert mcp_config.client_type == "streamable_http"
    assert mcp_config.auth_headers == {"Authorization": "Bearer token"}
    assert expiry_time == 600
    assert FakeRunner.resource_mgr.removed_mcp_servers == [
        {"server_id": "req-1:mcp:docs_server", "ignore_exception": True}
    ]
    assert FakeReActAgent.instances[0].ability_manager.abilities == []


@pytest.mark.asyncio
async def test_mcp_ability_uses_only_plan_allowlist_wrappers(openjiuwen_dependencies):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    allowed_tool = ToolSpec(
        name="docs_search",
        class_name="search",
        source=ToolSource.MCP,
        usage="docs",
    )
    plan = _plan(
        root_agent=_plan().root_agent.model_copy(update={"tools": [allowed_tool]}),
        mcp_connections=[
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/sse",
                transport="sse",
            )
        ],
    )

    _ = [
        chunk
        async for chunk in OpenJiuwenRuntime(dependencies=openjiuwen_dependencies).run(
            plan, RuntimeEventSink("req-1")
        )
    ]

    assert FakeRunner.resource_mgr.mcp_tool_requests == [
        {"name": "search", "server_id": "req-1:mcp:docs"}
    ]
    registered_tools = [tool for tool, _kwargs in FakeRunner.resource_mgr.added_tools]
    assert [tool.card.name for tool in registered_tools] == ["docs_search"]
    assert FakeReActAgent.instances[0].ability_manager.abilities == [
        registered_tools[0].card
    ]


@pytest.mark.asyncio
async def test_mcp_required_failure_blocks_and_optional_failure_warns(
    openjiuwen_dependencies,
):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    FakeRunner.resource_mgr.add_mcp_server_result = FakeResult(
        False, "connection failed"
    )
    required_plan = _plan(
        mcp_connections=[
            MCPConnectionConfig(
                name="required",
                url="https://mcp.example/sse",
                transport="sse",
                required=True,
            )
        ]
    )

    with pytest.raises(Exception, match="connection failed"):
        _ = [
            chunk
            async for chunk in OpenJiuwenRuntime(
                dependencies=openjiuwen_dependencies
            ).run(required_plan, RuntimeEventSink("req-1"))
        ]

    FakeRunner.resource_mgr = FakeResourceManager()
    FakeRunner.resource_mgr.add_mcp_server_result = FakeResult(False, "optional failed")
    optional_plan = _plan(
        mcp_connections=[
            MCPConnectionConfig(
                name="optional",
                url="https://mcp.example/sse",
                transport="sse",
                required=False,
            )
        ]
    )
    _ = [
        chunk
        async for chunk in OpenJiuwenRuntime(dependencies=openjiuwen_dependencies).run(
            optional_plan, RuntimeEventSink("req-1")
        )
    ]

    assert optional_plan.monitoring_metadata["runtime_warnings"][0]["server_name"] == (
        "optional"
    )


@pytest.mark.asyncio
async def test_local_knowledge_memory_skill_and_plugin_tools_use_tool_factory(
    openjiuwen_dependencies,
):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    tools = [
        ToolSpec(
            name="local_tool",
            source=ToolSource.LOCAL,
            input_schema={"query": {"type": "string"}},
        ),
        ToolSpec(name="knowledge_tool", source=ToolSource.KNOWLEDGE),
        ToolSpec(name="memory_tool", source=ToolSource.MEMORY),
        ToolSpec(name="skill_tool", source=ToolSource.SKILL),
        ToolSpec(name="plugin_tool", source=ToolSource.PLUGIN),
        ToolSpec(
            name="mcp_tool", source=ToolSource.MCP, usage="docs", class_name="search"
        ),
    ]
    plan = _plan(
        root_agent=AgentSpec(
            agent_id=1,
            name="root",
            model_name="main_model",
            max_steps=3,
            prompt=PromptBundle(fragments={"duty": "system"}),
            tools=tools,
        )
    )
    sink = RuntimeEventSink("req-1")
    runtime = OpenJiuwenRuntime(
        dependencies=openjiuwen_dependencies,
        tool_factory_registry=_tool_registry(),
    )

    _ = [chunk async for chunk in runtime.run(plan, sink)]

    registered_tools = [item[0] for item in FakeRunner.resource_mgr.added_tools]
    assert [tool.card.name for tool in registered_tools] == [
        "local_tool",
        "knowledge_tool",
        "memory_tool",
        "skill_tool",
        "plugin_tool",
    ]
    assert registered_tools[0].card.id == "req-1:tool:local_tool"
    assert registered_tools[0].card.input_params == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    result = await registered_tools[0].invoke({"query": "docs"})
    assert result["tool"] == "local_tool"
    assert [event.type for event in sink.events if event.tool_name == "local_tool"] == [
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.LEGACY_PROCESS,
        RuntimeEventType.TOOL_DISPLAY,
        RuntimeEventType.RETRIEVAL,
        RuntimeEventType.IMAGE,
    ]
    assert FakeRunner.resource_mgr.removed_tools == [
        {
            "tool_id": [
                "req-1:tool:local_tool",
                "req-1:tool:knowledge_tool",
                "req-1:tool:memory_tool",
                "req-1:tool:skill_tool",
                "req-1:tool:plugin_tool",
            ]
        }
    ]


@pytest.mark.asyncio
async def test_native_skill_util_is_not_used_by_runtime(openjiuwen_dependencies):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    plan = _plan(
        runtime_resources={
            "openjiuwen.skill_util.enabled": True,
            "skill.local_skills_dir": "/tmp/skills",
            "skill.enabled_skills": [{"name": "writer", "description": "Write files"}],
            "openjiuwen.sys_operation": {
                "sandbox_root": ["/tmp/skills"],
                "restrict_to_sandbox": True,
                "shell_allowlist": ["ls", "cat"],
            },
        }
    )
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    _ = [chunk async for chunk in runtime.run(plan, RuntimeEventSink("req-1"))]

    assert FakeSkillUtil.instances == []
    assert FakeRunner.resource_mgr.added_sys_operations == []
    assert FakeRunner.resource_mgr.removed_sys_operations == []


@pytest.mark.asyncio
async def test_unsupported_managed_context_compression_and_agents_fail_fast(
    openjiuwen_dependencies,
):
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    unsupported_plans = [
        _plan(
            root_agent=AgentSpec(
                agent_id=1,
                name="root",
                model_name="main_model",
                max_steps=1,
                managed_agents=[
                    AgentSpec(
                        agent_id=2, name="child", model_name="main_model", max_steps=1
                    )
                ],
            )
        ),
        _plan(
            root_agent=AgentSpec(
                agent_id=1,
                name="root",
                model_name="main_model",
                max_steps=1,
                external_a2a_agents=[{"agent_id": "remote"}],
            )
        ),
        _plan(
            root_agent=AgentSpec(
                agent_id=1,
                name="root",
                model_name="main_model",
                max_steps=1,
                context_policy=ContextPolicy(mode=ContextMode.MANAGED),
            )
        ),
        _plan(
            root_agent=AgentSpec(
                agent_id=1,
                name="root",
                model_name="main_model",
                max_steps=1,
                context_policy=ContextPolicy(compression={"enabled": True}),
            )
        ),
    ]

    for plan in unsupported_plans:
        with pytest.raises(OpenJiuwenUnsupportedFeatureError):
            _ = [chunk async for chunk in runtime.run(plan, RuntimeEventSink("req-1"))]


@pytest.mark.asyncio
async def test_stop_cancels_active_task_and_cleans_resources(openjiuwen_dependencies):
    FakeReActAgent.block_event = asyncio.Event()
    FakeReActAgent.stream_started = asyncio.Event()
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)
    run_control = RunControl(
        request_id="req-1",
        user_id="user-1",
        conversation_id=100,
        metadata={"tenant_id": "tenant-1"},
    )
    plan = _plan(
        run_control=run_control,
        mcp_connections=[
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/sse",
                transport="sse",
            )
        ],
    )

    async def consume_run():
        return [chunk async for chunk in runtime.run(plan, RuntimeEventSink("req-1"))]

    task = asyncio.create_task(consume_run())
    await asyncio.wait_for(FakeReActAgent.stream_started.wait(), timeout=1)

    await runtime.stop("req-1")

    with pytest.raises(asyncio.CancelledError):
        await task
    assert run_control.is_cancelled() is True
    assert FakeRunner.resource_mgr.removed_mcp_servers == [
        {"server_id": "req-1:mcp:docs", "ignore_exception": True}
    ]


@pytest.mark.asyncio
async def test_concurrent_runs_use_distinct_request_scoped_resources(
    openjiuwen_dependencies,
):
    FakeReActAgent.stream_chunks = [{"type": "answer", "payload": {"output": "done"}}]
    runtime = OpenJiuwenRuntime(dependencies=openjiuwen_dependencies)

    def concurrent_plan(request_id: str) -> AgentRunPlan:
        return _plan(
            request_id=request_id,
            run_control=RunControl(
                request_id=request_id,
                user_id="user-1",
                conversation_id=request_id,
                metadata={"tenant_id": "tenant-1"},
            ),
            mcp_connections=[
                MCPConnectionConfig(
                    name="docs",
                    url="https://mcp.example/sse",
                    transport="sse",
                )
            ],
        )

    await asyncio.gather(
        *(
            asyncio.create_task(
                _consume_openjiuwen_run(
                    runtime,
                    concurrent_plan(request_id),
                    RuntimeEventSink(request_id),
                )
            )
            for request_id in ("req-a", "req-b")
        )
    )

    added_ids = {
        config.server_id
        for config, _expiry in FakeRunner.resource_mgr.added_mcp_servers
    }
    removed_ids = {
        item["server_id"] for item in FakeRunner.resource_mgr.removed_mcp_servers
    }
    assert added_ids == {"req-a:mcp:docs", "req-b:mcp:docs"}
    assert removed_ids == added_ids
    assert runtime._active_runs == {}


async def _consume_openjiuwen_run(
    runtime: OpenJiuwenRuntime,
    plan: AgentRunPlan,
    sink: RuntimeEventSink,
) -> list[Any]:
    return [chunk async for chunk in runtime.run(plan, sink)]
