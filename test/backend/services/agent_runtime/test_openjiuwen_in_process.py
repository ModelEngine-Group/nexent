import asyncio
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexent.core.agents.agent_model import MCPBinding, ToolConfig

from backend.services.agent_runtime.execution import AgentRuntimeExecution
from backend.services.agent_runtime.openjiuwen_spec import OpenJiuwenRunSpec
from backend.services.agent_runtime.providers import openjiuwen_in_process as provider


class FakeAddResult:
    def __init__(self, added=True):
        self.added = added


class FakeAbilityManager:
    def __init__(self):
        self.abilities = []

    def add(self, card):
        self.abilities.append((card, None))
        return FakeAddResult()

    def add_ability(self, card, resource):
        self.abilities.append((card, resource))
        return FakeAddResult()

    def teardown_tools(self):
        return None


class FakeMcpResult:
    def __init__(self, error=False):
        self.error = error

    def is_err(self):
        return self.error


class FakeMcpConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeResourceManager:
    def __init__(self, discovered=(), connection_error=False):
        self.discovered = list(discovered)
        self.connection_error = connection_error
        self.added_configs = []
        self.requested_tools = []
        self.removed_servers = []

    async def add_mcp_server(self, config, tag=None):
        self.added_configs.append((config, tag))
        return FakeMcpResult(self.connection_error)

    async def get_mcp_tool_infos(self, server_id):
        return [SimpleNamespace(name=name) for name in self.discovered]

    async def get_mcp_tool(self, name, server_id):
        self.requested_tools.append((name, server_id))
        return [SimpleNamespace(card=SimpleNamespace(name=name, id=name))]

    async def remove_mcp_server(self, server_id, **kwargs):
        self.removed_servers.append(server_id)


class FakeLocalFunction:
    def __init__(self, card, func):
        self.card = card
        self.func = func


class FakeToolCard:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def make_spec(*, bindings=(), tools=(), depth=0):
    config = SimpleNamespace(
        tools=list(tools),
        mcp_bindings=list(bindings),
        external_a2a_agents=[],
    )
    return OpenJiuwenRunSpec(
        agent_id=1,
        name="root",
        description="root",
        agent_config=config,
        parent_agent_id=None,
        depth=depth,
        children=(),
    )


def make_execution(spec):
    run_info = SimpleNamespace(
        observer=SimpleNamespace(lang="en"),
        model_config_list=[],
        stop_event=Event(),
        agent_config=spec.agent_config,
        query="hello",
        history=[],
    )
    return AgentRuntimeExecution(
        run_id="run-1",
        agent_run_info=run_info,
        conversation_id=1,
        user_id="user-1",
        tenant_id="tenant-1",
        version_no=1,
    )


def make_scope(spec, resource_manager, scope_id="scope-1"):
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._bindings = SimpleNamespace(
        Runner=SimpleNamespace(resource_mgr=resource_manager),
        McpServerConfig=FakeMcpConfig,
    )
    queue = asyncio.Queue()
    scope = provider._NodeScope(
        runtime=runtime,
        execution=make_execution(spec),
        spec=spec,
        emitter=provider._EventEmitter(queue),
        cancel_event=asyncio.Event(),
        scope_id=scope_id,
    )
    scope.agent = SimpleNamespace(
        ability_manager=FakeAbilityManager(),
        agent_callback_manager=SimpleNamespace(clear=AsyncMock()),
        context_engine=SimpleNamespace(clear_context=AsyncMock()),
    )
    return scope, queue


def test_load_bindings_uses_openjiuwen_016_core_api():
    bindings = provider._load_openjiuwen_bindings()

    assert bindings.Runner.__name__ == "Runner"
    assert bindings.ReActAgent.__name__ == "ReActAgent"
    assert bindings.ReActAgentConfig.__name__ == "ReActAgentConfig"
    assert bindings.LocalFunction.__name__ == "LocalFunction"
    assert bindings.McpServerConfig.__name__ == "McpServerConfig"


def test_model_config_disables_016_ssl_verification_without_certificate():
    spec = make_spec()
    spec.agent_config.model_name = "model-alias"
    spec.agent_config.max_steps = 5
    spec.agent_config.context_components = []
    spec.agent_config.prompt_templates = {"system_prompt": "system"}
    spec.agent_config.instructions = None
    model = SimpleNamespace(
        cite_name="model-alias",
        model_factory="openai-api-compatible",
        api_key="secret",
        url="https://model.example/v1",
        ssl_verify=True,
        timeout_seconds=60,
        model_name="test-model",
        temperature=0.2,
        top_p=0.8,
        max_output_tokens=256,
        extra_body=None,
        context_window_tokens=8192,
    )
    execution = make_execution(spec)
    execution.agent_run_info.model_config_list = [model]
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._bindings = provider._load_openjiuwen_bindings()

    config = runtime._build_agent_config(execution, spec)

    assert config.model_client_config.verify_ssl is False
    assert config.model_client_config.ssl_cert is None


@pytest.mark.asyncio
async def test_error_result_closes_agent_stream_in_current_task(monkeypatch):
    class FakeSession:
        @staticmethod
        def get_session_id():
            return "session-1"

    class FakeStream:
        def __init__(self):
            self.closed = False
            self._emitted = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._emitted:
                raise StopAsyncIteration
            self._emitted = True
            return SimpleNamespace(
                type="answer",
                payload={"result_type": "error", "output": "model failed"},
            )

        async def aclose(self):
            self.closed = True

    stream = FakeStream()

    class FakeAgent:
        @staticmethod
        def stream(inputs, session):
            return stream

    class FakeScope:
        def __init__(self, **kwargs):
            self.session = FakeSession()
            self.agent = FakeAgent()

        async def setup(self):
            return None

        async def cleanup(self):
            return None

    monkeypatch.setattr(provider, "_NodeScope", FakeScope)
    spec = make_spec()
    runtime = provider.OpenJiuwenInProcessRuntime()

    with pytest.raises(RuntimeError, match="error result"):
        await runtime._execute_node(
            execution=make_execution(spec),
            spec=spec,
            query="hello",
            emitter=provider._EventEmitter(asyncio.Queue()),
            cancel_event=asyncio.Event(),
        )

    assert stream.closed is True


@pytest.mark.asyncio
async def test_mcp_binds_only_selected_allowlist_and_cleans_request_resources():
    binding = MCPBinding(
        server_id="configured-1",
        server_name="existing-server",
        url="https://mcp.example/mcp",
        transport="streamable-http",
        headers={"Authorization": "Bearer request-secret"},
        tool_names=["selected_tool"],
        required_tool_names=["selected_tool"],
    )
    tool = ToolConfig(
        class_name="selected_tool",
        name="selected_tool",
        description="selected",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        usage="existing-server",
    )
    resource_manager = FakeResourceManager(discovered=["selected_tool", "unselected_tool"])
    scope, _queue = make_scope(make_spec(bindings=[binding], tools=[tool]), resource_manager)

    await scope._setup_mcp_tools(scope.runtime._bindings)

    config = resource_manager.added_configs[0][0]
    assert config.server_path == "https://mcp.example/mcp"
    assert config.client_type == "streamable-http"
    assert config.auth_headers == {"Authorization": "Bearer request-secret"}
    assert [name for name, _server_id in resource_manager.requested_tools] == ["selected_tool"]
    assert [card.name for card, _resource in scope.agent.ability_manager.abilities] == ["selected_tool"]

    await scope.cleanup()

    assert resource_manager.removed_servers == [config.server_id]


@pytest.mark.asyncio
async def test_optional_unavailable_mcp_emits_warning_without_connecting():
    binding = MCPBinding(
        server_id="optional-1",
        server_name="optional-server",
        url="",
        transport="sse",
        required=False,
        tool_names=["optional_tool"],
        available=False,
        unavailable_reason="server_disabled",
    )
    tool = ToolConfig(
        class_name="optional_tool",
        name="optional_tool",
        description="optional",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        usage="optional-server",
        metadata={"mcp_required": False},
    )
    resource_manager = FakeResourceManager()
    scope, queue = make_scope(make_spec(bindings=[binding], tools=[tool]), resource_manager)

    await scope._setup_mcp_tools(scope.runtime._bindings)

    warning = json.loads(await queue.get())
    assert warning["runtime_event"] == "warning"
    assert "optional_mcp_unavailable" in warning["content"]
    assert resource_manager.added_configs == []


@pytest.mark.asyncio
async def test_required_unavailable_mcp_blocks_run():
    binding = MCPBinding(
        server_id="required-1",
        server_name="required-server",
        url="",
        transport="sse",
        required=True,
        tool_names=["required_tool"],
        required_tool_names=["required_tool"],
        available=False,
        unavailable_reason="server_not_configured",
    )
    tool = ToolConfig(
        class_name="required_tool",
        name="required_tool",
        description="required",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        usage="required-server",
    )
    scope, _queue = make_scope(
        make_spec(bindings=[binding], tools=[tool]),
        FakeResourceManager(),
    )

    with pytest.raises(RuntimeError, match="Required MCP server is unavailable"):
        await scope._setup_mcp_tools(scope.runtime._bindings)


@pytest.mark.asyncio
async def test_missing_optional_tool_warns_but_missing_required_tool_fails():
    optional_binding = MCPBinding(
        server_id="server-1",
        server_name="server",
        url="https://mcp.example/mcp",
        transport="streamable-http",
        required=False,
        tool_names=["optional_tool"],
        required_tool_names=[],
    )
    optional_tool = ToolConfig(
        class_name="optional_tool",
        name="optional_tool",
        description="optional",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        usage="server",
        metadata={"mcp_required": False},
    )
    scope, queue = make_scope(
        make_spec(bindings=[optional_binding], tools=[optional_tool]),
        FakeResourceManager(discovered=[]),
    )

    await scope._setup_mcp_tools(scope.runtime._bindings)
    warning = json.loads(await queue.get())
    assert "optional_mcp_tools_unavailable" in warning["content"]

    required_binding = optional_binding.model_copy(
        update={"required": True, "required_tool_names": ["optional_tool"]}
    )
    required_scope, _queue = make_scope(
        make_spec(bindings=[required_binding], tools=[optional_tool]),
        FakeResourceManager(discovered=[]),
    )
    with pytest.raises(RuntimeError, match="Required MCP tools are unavailable"):
        await required_scope._setup_mcp_tools(required_scope.runtime._bindings)


@pytest.mark.asyncio
async def test_local_knowledge_memory_and_skill_tools_share_request_scope(monkeypatch):
    created_tools = []

    class FakeTool:
        def __init__(self, name):
            self.name = name

        def forward(self, **kwargs):
            return {"tool": self.name, "kwargs": kwargs}

    class FakeNexentAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_tool(self, config):
            tool = FakeTool(config.class_name)
            created_tools.append(tool)
            return tool

    monkeypatch.setattr(provider, "NexentAgent", FakeNexentAgent)
    tools = [
        ToolConfig(
            class_name=class_name,
            name=class_name,
            description=class_name,
            inputs='{"query": {"type": "string"}}',
            output_type="string",
            params={},
            source="local",
        )
        for class_name in ("KnowledgeBaseSearchTool", "SearchMemoryTool", "RunSkillTool")
    ]
    spec = make_spec(tools=tools)
    scope, _queue = make_scope(spec, FakeResourceManager())
    scope.runtime._bindings.LocalFunction = FakeLocalFunction
    scope.runtime._bindings.ToolCard = FakeToolCard
    scope._drain_tool_observer = AsyncMock()

    await scope._setup_local_tools(scope.runtime._bindings)

    assert [tool.name for tool in created_tools] == [
        "KnowledgeBaseSearchTool",
        "SearchMemoryTool",
        "RunSkillTool",
    ]
    for card, local_function in scope.agent.ability_manager.abilities:
        result = await local_function.func(query="hello")
        assert result == {"tool": card.name, "kwargs": {"query": "hello"}}
    assert scope._drain_tool_observer.await_count == 3


@pytest.mark.parametrize(
    "class_name",
    [
        "RunSkillScriptTool",
        "ReadSkillMdTool",
        "ReadSkillConfigTool",
        "WriteSkillFileTool",
    ],
)
def test_builtin_skill_tools_use_node_owned_agent_context(class_name):
    first_config = ToolConfig(
        class_name=class_name,
        name=class_name,
        description="run",
        inputs="{}",
        output_type="string",
        params={"local_skills_dir": "/tmp/skills"},
        source="builtin",
        usage="builtin",
        metadata={"agent_id": 1, "tenant_id": "tenant-a", "version_no": 2},
    )
    second_config = first_config.model_copy(
        update={
            "metadata": {
                "agent_id": 2,
                "tenant_id": "tenant-b",
                "version_no": 3,
            }
        }
    )
    factory = SimpleNamespace(create_tool=lambda config: pytest.fail("unexpected fallback"))

    first_instance, first_callable = provider._NodeScope._create_request_tool(
        factory,
        first_config,
    )
    second_instance, second_callable = provider._NodeScope._create_request_tool(
        factory,
        second_config,
    )

    assert first_instance is not second_instance
    assert (first_instance.agent_id, first_instance.tenant_id, first_instance.version_no) == (
        1,
        "tenant-a",
        2,
    )
    assert (second_instance.agent_id, second_instance.tenant_id, second_instance.version_no) == (
        2,
        "tenant-b",
        3,
    )
    assert callable(first_callable)
    assert callable(second_callable)


def test_openjiuwen_builtin_skill_schemas_match_nexent_call_contracts():
    from openjiuwen.core.common.exception.errors import ValidationError as OpenJiuwenValidationError
    from openjiuwen.core.common.utils.schema_utils import SchemaUtils

    run_config = ToolConfig(
        class_name="RunSkillScriptTool",
        name="run_skill_script",
        description="run",
        inputs='{"skill_name": "str", "script_path": "str", "params": "dict"}',
        output_type="string",
        params={},
        source="builtin",
    )
    read_config = ToolConfig(
        class_name="ReadSkillMdTool",
        name="read_skill_md",
        description="read",
        inputs='{"skill_name": "str", "additional_files": "list[str]"}',
        output_type="string",
        params={},
        source="builtin",
    )

    run_schema = provider.OpenJiuwenInProcessRuntime._resolve_local_tool_input_schema(run_config)
    read_schema = provider.OpenJiuwenInProcessRuntime._resolve_local_tool_input_schema(read_config)

    assert run_schema["required"] == ["skill_name", "script_path"]
    assert run_schema["properties"]["params"] == {"type": "string"}
    assert SchemaUtils.format_with_schema(
        {"skill_name": "csv-data-analyzer", "script_path": "scripts/analyze.py"},
        run_schema,
    ) == {
        "skill_name": "csv-data-analyzer",
        "script_path": "scripts/analyze.py",
        "params": None,
    }
    assert SchemaUtils.format_with_schema(
        {
            "skill_name": "csv-data-analyzer",
            "script_path": "scripts/analyze.py",
            "params": "--file input.csv",
        },
        run_schema,
    )["params"] == "--file input.csv"
    with pytest.raises(OpenJiuwenValidationError) as exc_info:
        SchemaUtils.format_with_schema(
            {
                "skill_name": "csv-data-analyzer",
                "script_path": "scripts/analyze.py",
                "params": {"file": "input.csv"},
            },
            run_schema,
        )
    assert "valid string" in str(exc_info.value)

    assert read_schema["required"] == ["skill_name"]
    assert SchemaUtils.format_with_schema(
        {"skill_name": "csv-data-analyzer"},
        read_schema,
    ) == {
        "skill_name": "csv-data-analyzer",
        "additional_files": None,
    }
    assert SchemaUtils.format_with_schema(
        {
            "skill_name": "csv-data-analyzer",
            "additional_files": ["examples.md", "reference/api.md"],
        },
        read_schema,
    )["additional_files"] == ["examples.md", "reference/api.md"]


@pytest.mark.asyncio
async def test_setup_local_tools_applies_openjiuwen_builtin_skill_schemas():
    tools = [
        ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="run",
            inputs='{"skill_name": "str", "script_path": "str", "params": "dict"}',
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
        ),
        ToolConfig(
            class_name="ReadSkillMdTool",
            name="read_skill_md",
            description="read",
            inputs='{"skill_name": "str", "additional_files": "list[str]"}',
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
        ),
    ]
    scope, _queue = make_scope(make_spec(tools=tools), FakeResourceManager())
    scope.runtime._bindings.LocalFunction = FakeLocalFunction
    scope.runtime._bindings.ToolCard = FakeToolCard

    await scope._setup_local_tools(scope.runtime._bindings)

    cards = {
        card.name: card
        for card, _local_function in scope.agent.ability_manager.abilities
    }
    assert cards["run_skill_script"].input_params["required"] == [
        "skill_name",
        "script_path",
    ]
    assert cards["run_skill_script"].input_params["properties"]["params"] == {
        "type": "string"
    }
    assert cards["read_skill_md"].input_params["required"] == ["skill_name"]
    assert cards["read_skill_md"].input_params["properties"]["additional_files"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_non_overridden_tools_keep_generic_openjiuwen_schema_conversion():
    config = ToolConfig(
        class_name="WriteSkillFileTool",
        name="write_skill_file",
        description="write",
        inputs='{"skill_name": "str", "file_path": "str", "content": "str"}',
        output_type="string",
        params={},
        source="builtin",
    )

    schema = provider.OpenJiuwenInProcessRuntime._resolve_local_tool_input_schema(config)

    assert schema == provider.OpenJiuwenInProcessRuntime._tool_input_schema(config.inputs)
    assert schema["required"] == ["skill_name", "file_path", "content"]


def test_tool_input_schema_preserves_shorthand_types():
    schema = provider.OpenJiuwenInProcessRuntime._tool_input_schema(
        '{"name": "str", "count": "int", "files": "list[str]", '
        '"options": "dict", "enabled": "Optional[bool]"}'
    )

    assert schema["properties"] == {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "files": {"type": "array", "items": {"type": "string"}},
        "options": {"type": "object"},
        "enabled": {"type": "boolean", "nullable": True},
    }
    assert schema["required"] == ["name", "count", "files", "options"]


@pytest.mark.asyncio
async def test_external_a2a_is_exposed_as_request_local_function(monkeypatch):
    class FakeExternalConfig:
        agent_id = "external-1"
        name = "external_agent"
        description = "External Agent"

        @staticmethod
        def to_a2a_agent_info():
            return {"agent_id": "external-1"}

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, task, **kwargs):
            return f"external:{task}"

    monkeypatch.setattr(provider, "ExternalA2AAgentWrapper", FakeWrapper)
    spec = make_spec()
    spec.agent_config.external_a2a_agents = [FakeExternalConfig()]
    scope, _queue = make_scope(spec, FakeResourceManager())
    scope.runtime._bindings.LocalFunction = FakeLocalFunction
    scope.runtime._bindings.ToolCard = FakeToolCard

    await scope._setup_a2a_tools(scope.runtime._bindings)

    card, local_function = scope.agent.ability_manager.abilities[0]
    assert card.name == "external_agent"
    assert await local_function.func(task="delegate this") == "external:delegate this"


@pytest.mark.asyncio
async def test_recursive_node_events_only_emit_outer_final_answer(monkeypatch):
    class FakeSession:
        @staticmethod
        def get_session_id():
            return "session-1"

    class FakeAgent:
        async def stream(self, inputs, session):
            yield SimpleNamespace(type="llm_output", payload={"content": "partial"})
            yield SimpleNamespace(type="answer", payload={"output": "complete"})

    class FakeScope:
        def __init__(self, **kwargs):
            self.session = FakeSession()
            self.agent = FakeAgent()

        async def setup(self):
            return None

        async def cleanup(self):
            return None

    monkeypatch.setattr(provider, "_NodeScope", FakeScope)
    root_spec = make_spec(depth=0)
    child_spec = OpenJiuwenRunSpec(
        agent_id=2,
        name="child",
        description="child",
        agent_config=root_spec.agent_config,
        parent_agent_id=1,
        depth=1,
        children=(),
    )
    runtime = provider.OpenJiuwenInProcessRuntime()
    queue = asyncio.Queue()
    emitter = provider._EventEmitter(queue)

    root_result = await runtime._execute_node(
        execution=make_execution(root_spec),
        spec=root_spec,
        query="root task",
        emitter=emitter,
        cancel_event=asyncio.Event(),
    )
    child_result = await runtime._execute_node(
        execution=make_execution(child_spec),
        spec=child_spec,
        query="child task",
        emitter=emitter,
        cancel_event=asyncio.Event(),
    )

    events = []
    while not queue.empty():
        events.append(json.loads(await queue.get()))
    final_events = [event for event in events if event["type"] == "final_answer"]
    child_finish = [event for event in events if event["type"] == "agent_finish"]
    assert root_result == child_result == "complete"
    assert len(final_events) == 1
    assert final_events[0]["agent_id"] == 1
    assert len(child_finish) == 1
    assert child_finish[0]["agent_id"] == 2
    assert child_finish[0]["parent_agent_id"] == 1
    assert child_finish[0]["depth"] == 1
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_concurrent_mcp_scopes_use_distinct_server_ids():
    binding = MCPBinding(
        server_id="configured-1",
        server_name="shared-server",
        url="https://mcp.example/mcp",
        transport="streamable-http",
        tool_names=["selected_tool"],
        required_tool_names=["selected_tool"],
    )
    tool = ToolConfig(
        class_name="selected_tool",
        name="selected_tool",
        description="selected",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        usage="shared-server",
    )
    resource_manager = FakeResourceManager(discovered=["selected_tool"])
    spec = make_spec(bindings=[binding], tools=[tool])
    first_scope, _queue = make_scope(spec, resource_manager, scope_id="scope-a")
    second_scope, _queue = make_scope(spec, resource_manager, scope_id="scope-b")

    await asyncio.gather(
        first_scope._setup_mcp_tools(first_scope.runtime._bindings),
        second_scope._setup_mcp_tools(second_scope.runtime._bindings),
    )

    server_ids = [config.server_id for config, _tag in resource_manager.added_configs]
    assert len(server_ids) == 2
    assert len(set(server_ids)) == 2
    assert all(server_id.startswith("nexent-mcp-scope-") for server_id in server_ids)

    await asyncio.gather(first_scope.cleanup(), second_scope.cleanup())
    assert set(resource_manager.removed_servers) == set(server_ids)


@pytest.mark.asyncio
async def test_initialization_failure_yields_explicit_event_and_never_falls_back(monkeypatch):
    spec = make_spec()
    execution = make_execution(spec)
    runtime = provider.OpenJiuwenInProcessRuntime()
    monkeypatch.setattr(
        provider,
        "_load_openjiuwen_bindings",
        lambda: (_ for _ in ()).throw(ImportError("missing OpenJiuwen core API")),
    )

    stream = runtime.run(execution)
    event = json.loads(await anext(stream))

    assert event["type"] == "error"
    assert event["runtime_event"] == "initialization_error"
    with pytest.raises(RuntimeError, match="initialization failed"):
        await anext(stream)


@pytest.mark.asyncio
async def test_execution_timeout_yields_explicit_failure_event(monkeypatch):
    spec = make_spec()
    execution = make_execution(spec)
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._started = True
    runtime._bindings = SimpleNamespace()
    monkeypatch.setattr(provider, "build_openjiuwen_run_spec", lambda config: spec)
    monkeypatch.setattr(
        runtime,
        "_execute_node",
        AsyncMock(side_effect=asyncio.TimeoutError()),
    )

    stream = runtime.run(execution)
    event = json.loads(await anext(stream))

    assert event["type"] == "error"
    assert event["runtime_event"] == "timeout"
    assert event["content"] == "OpenJiuwen execution timed out."
    with pytest.raises(RuntimeError, match="execution failed"):
        await anext(stream)


@pytest.mark.asyncio
async def test_openjiuwen_runtime_supports_concurrent_run_ids(monkeypatch):
    first_spec = make_spec()
    second_spec = make_spec()
    first_execution = make_execution(first_spec)
    second_execution = make_execution(second_spec)
    first_execution = AgentRuntimeExecution(
        **{**first_execution.__dict__, "run_id": "run-a"}
    )
    second_execution = AgentRuntimeExecution(
        **{**second_execution.__dict__, "run_id": "run-b"}
    )
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._started = True
    runtime._bindings = SimpleNamespace()

    async def produce(execution, _cancel_event, emitter, queue):
        await asyncio.sleep(0)
        await emitter.emit("final_answer", execution.run_id, first_spec)
        await queue.put(provider._END)

    monkeypatch.setattr(runtime, "_produce", produce)

    first_result, second_result = await asyncio.gather(
        _collect(runtime.run(first_execution)),
        _collect(runtime.run(second_execution)),
    )

    assert json.loads(first_result[0])["content"] == "run-a"
    assert json.loads(second_result[0])["content"] == "run-b"
    assert runtime._active == {}


@pytest.mark.asyncio
async def test_request_stop_cancels_exact_active_run(monkeypatch):
    spec = make_spec()
    execution = make_execution(spec)
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._started = True
    runtime._bindings = SimpleNamespace()

    async def produce(_execution, _cancel_event, _emitter, queue):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            _execution.agent_run_info.stop_event.set()
        finally:
            await queue.put(provider._END)

    monkeypatch.setattr(runtime, "_produce", produce)

    async def consume():
        return [item async for item in runtime.run(execution)]

    consumer = asyncio.create_task(consume())
    for _ in range(20):
        if execution.run_id in runtime._active:
            break
        await asyncio.sleep(0)

    assert runtime.request_stop(execution.run_id) is True
    assert await consumer == []
    assert execution.agent_run_info.stop_event.is_set()
    assert runtime.request_stop(execution.run_id) is False


@pytest.mark.asyncio
async def test_shutdown_drains_active_runs_and_stops_initialized_runner(monkeypatch):
    spec = make_spec()
    execution = make_execution(spec)
    stop_runner = AsyncMock()
    runtime = provider.OpenJiuwenInProcessRuntime()
    runtime._started = True
    runtime._bindings = SimpleNamespace(Runner=SimpleNamespace(stop=stop_runner))

    async def produce(_execution, _cancel_event, _emitter, queue):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            _execution.agent_run_info.stop_event.set()
        finally:
            await queue.put(provider._END)

    monkeypatch.setattr(runtime, "_produce", produce)
    consumer = asyncio.create_task(
        asyncio.wait_for(
            _collect(runtime.run(execution)),
            timeout=1,
        )
    )
    for _ in range(20):
        if execution.run_id in runtime._active:
            break
        await asyncio.sleep(0)

    await runtime.shutdown()

    assert await consumer == []
    assert execution.agent_run_info.stop_event.is_set()
    stop_runner.assert_awaited_once_with()
    assert runtime._started is False


@pytest.mark.asyncio
async def test_shutdown_before_first_run_never_imports_or_restarts_openjiuwen(monkeypatch):
    spec = make_spec()
    execution = make_execution(spec)
    runtime = provider.OpenJiuwenInProcessRuntime()
    load_bindings = AsyncMock()
    monkeypatch.setattr(provider, "_load_openjiuwen_bindings", load_bindings)

    await runtime.shutdown()

    stream = runtime.run(execution)
    with pytest.raises(RuntimeError, match="shutting down"):
        await anext(stream)
    load_bindings.assert_not_called()


async def _collect(stream):
    return [item async for item in stream]
