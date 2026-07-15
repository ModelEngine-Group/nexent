import asyncio
import json
import os
import sys
import threading
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.models import (
    AgentRunPlan,
    AgentSpec,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    OperatorSpec,
    PromptBundle,
    RunControl,
    ToolSource,
    ToolSpec,
)
from services.agent_runtime.events import RuntimeEvent, RuntimeEventSink, RuntimeEventType
from services.agent_runtime.operators import OperatorRegistry, OperatorResult
from services.agent_runtime.smolagents_runtime import SmolagentsRuntime


class _ValidatingDataclass:
    @classmethod
    def model_validate(cls, data):
        field_names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in dict(data).items() if key in field_names})


@dataclass
class FakeModelConfig(_ValidatingDataclass):
    cite_name: str
    api_key: str = ""
    model_name: str = ""
    url: str = ""
    ssl_verify: bool = True
    model_factory: str | None = None
    max_output_tokens: int | None = None
    context_window_tokens: int | None = None


@dataclass
class FakeToolConfig:
    class_name: str
    name: str | None
    description: str | None
    inputs: str | None
    output_type: str | None
    params: dict[str, Any]
    source: str
    usage: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class FakeAgentVerificationConfig(_ValidatingDataclass):
    enabled: bool = False
    max_final_rounds: int = 2


@dataclass
class FakeExternalA2AAgentConfig(_ValidatingDataclass):
    agent_id: str
    name: str
    description: str = ""
    url: str = ""
    api_key: str | None = None


@dataclass
class FakeContextManagerConfig:
    enabled: bool = False
    token_threshold: int = 10000
    soft_input_budget_tokens: int = 0
    hard_input_budget_tokens: int = 0
    keep_recent_steps: int = 4


@dataclass
class FakeAgentConfig:
    name: str
    description: str
    prompt_templates: dict[str, Any] | None
    tools: list[FakeToolConfig]
    max_steps: int
    requested_output_tokens: int | None
    model_name: str
    provide_run_summary: bool = False
    instructions: str | None = None
    managed_agents: list[Any] = field(default_factory=list)
    external_a2a_agents: list[Any] = field(default_factory=list)
    context_manager_config: FakeContextManagerConfig | None = None
    context_components: list[Any] | None = None
    capacity_snapshot: dict[str, Any] | None = None
    safe_input_budget_snapshot: dict[str, Any] | None = None
    verification_config: FakeAgentVerificationConfig = field(
        default_factory=FakeAgentVerificationConfig
    )


@dataclass
class FakeAgentHistory:
    role: str
    content: str


@dataclass
class FakeAgentRunInfo:
    query: str
    model_config_list: list[Any]
    observer: Any
    agent_config: FakeAgentConfig
    mcp_host: list[Any] | None
    history: list[FakeAgentHistory] | None
    stop_event: threading.Event
    context_manager: Any | None = None
    capacity_snapshot: dict[str, Any] | None = None
    safe_input_budget_snapshot: dict[str, Any] | None = None


class FakeMessageObserver:
    def __init__(self, lang: str = "zh"):
        self.lang = lang


@pytest.fixture(autouse=True)
def fake_legacy_agent_models(monkeypatch):
    import services.agent_runtime.smolagents_runtime as smolagents_runtime

    def fake_models():
        return {
            "AgentConfig": FakeAgentConfig,
            "AgentHistory": FakeAgentHistory,
            "AgentRunInfo": FakeAgentRunInfo,
            "AgentVerificationConfig": FakeAgentVerificationConfig,
            "ExternalA2AAgentConfig": FakeExternalA2AAgentConfig,
            "ModelConfig": FakeModelConfig,
            "ToolConfig": FakeToolConfig,
            "ContextManagerConfig": FakeContextManagerConfig,
            "MessageObserver": FakeMessageObserver,
        }

    for module in {
        smolagents_runtime,
        sys.modules.get("backend.services.agent_runtime.smolagents_runtime"),
        sys.modules.get("services.agent_runtime.smolagents_runtime"),
    }:
        if module is not None:
            monkeypatch.setattr(module, "_legacy_agent_models", fake_models)


def _model_config() -> dict[str, Any]:
    return {
        "cite_name": "gpt-4o",
        "api_key": "key",
        "model_name": "openai/gpt-4o",
        "url": "https://api.example",
        "ssl_verify": True,
        "model_factory": "openai",
        "max_output_tokens": 4096,
        "context_window_tokens": 128000,
    }


def _plan(**overrides: Any) -> AgentRunPlan:
    stop_event = overrides.pop("stop_event", None)
    run_control = overrides.pop(
        "run_control",
        RunControl(
            request_id="req-1",
            user_id="user-1",
            conversation_id=None,
            legacy_stop_event=stop_event,
            metadata={"language": "en"},
        ),
    )
    root_agent = overrides.pop(
        "root_agent",
        AgentSpec(
            agent_id=1,
            name="root",
            description="Root agent",
            model_name="gpt-4o",
            max_steps=8,
            prompt=PromptBundle(
                rendered_legacy_system_prompt="You are the root agent.",
                templates={"planning": {"enabled": True}},
                context_components=[{"type": "agent_profile"}],
            ),
            tools=[
                ToolSpec(
                    name="search",
                    description="Search docs",
                    input_schema={"query": {"type": "string"}},
                    output_type="string",
                    source=ToolSource.KNOWLEDGE,
                    class_name="KnowledgeBaseSearchTool",
                    params={"top_k": 3},
                    metadata={"display_name_to_index_map": {"Docs": "idx"}},
                )
            ],
            managed_agents=[
                AgentSpec(
                    agent_id=2,
                    name="researcher",
                    description="Research",
                    model_name="sub_model",
                    max_steps=3,
                    prompt=PromptBundle(rendered_legacy_system_prompt="Research facts."),
                )
            ],
            external_a2a_agents=[
                {
                    "agent_id": "remote-1",
                    "name": "remote",
                    "description": "Remote helper",
                    "url": "https://remote.example/a2a",
                }
            ],
            context_policy=ContextPolicy(
                mode=ContextMode.MANAGED,
                token_threshold=32000,
                soft_input_budget_tokens=28000,
                hard_input_budget_tokens=30000,
                compression={"keep_recent_steps": 6},
            ),
            verification_config={"enabled": True, "max_final_rounds": 2},
        ),
    )
    payload = {
        "request_id": "req-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        "query": "hello",
        "history": [
            {
                "role": "user",
                "content": "previous",
                "minio_files": [{"name": "doc.txt", "object_name": "tenant/doc.txt"}],
            }
        ],
        "model_config_list": [_model_config()],
        "root_agent": root_agent,
        "mcp_connections": [
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/sse",
                transport="sse",
                headers={"Authorization": "Bearer token"},
            )
        ],
        "monitoring_metadata": {
            "language": "en",
            "model.capacity_snapshot": {"context_window_tokens": 128000},
            "model.safe_input_budget_snapshot": {
                "soft_input_budget_tokens": 28000,
                "hard_input_budget_tokens": 30000,
            },
        },
        "run_control": run_control,
    }
    payload.update(overrides)
    return AgentRunPlan(**payload)


def test_smolagents_runtime_maps_plan_to_legacy_agent_run_info():
    runtime = SmolagentsRuntime()
    plan = _plan()

    run_info = runtime.to_agent_run_info(plan)

    assert run_info.query == "hello"
    assert run_info.model_config_list[0].cite_name == "gpt-4o"
    assert run_info.agent_config.name == "root"
    assert run_info.agent_config.model_name == "gpt-4o"
    assert run_info.agent_config.prompt_templates["system_prompt"] == "You are the root agent."
    assert run_info.agent_config.prompt_templates["planning"] == {"enabled": True}
    assert run_info.agent_config.tools[0].class_name == "KnowledgeBaseSearchTool"
    assert run_info.agent_config.tools[0].inputs == '{"query": {"type": "string"}}'
    assert run_info.agent_config.tools[0].source == "local"
    assert run_info.agent_config.managed_agents[0].name == "researcher"
    assert run_info.agent_config.external_a2a_agents[0].url == "https://remote.example/a2a"
    assert run_info.agent_config.context_manager_config.enabled is True
    assert run_info.agent_config.context_manager_config.token_threshold == 32000
    assert run_info.agent_config.context_manager_config.keep_recent_steps == 6
    assert run_info.agent_config.context_components == [{"type": "agent_profile"}]
    assert run_info.agent_config.verification_config.enabled is True
    assert run_info.mcp_host == [
        {
            "url": "https://mcp.example/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer token"},
        }
    ]
    assert run_info.history[0].role == "user"
    assert "[Attached files]" in run_info.history[0].content
    assert run_info.capacity_snapshot == {"context_window_tokens": 128000}
    assert run_info.safe_input_budget_snapshot == {
        "soft_input_budget_tokens": 28000,
        "hard_input_budget_tokens": 30000,
    }
    assert plan.run_control.legacy_stop_event is run_info.stop_event


def test_smolagents_runtime_agent_run_info_matches_legacy_golden_fixture(monkeypatch):
    import services.agent_runtime.smolagents_runtime as smolagents_runtime

    monkeypatch.setattr(smolagents_runtime, "MINIO_DEFAULT_BUCKET", None)
    backend_module = sys.modules.get("backend.services.agent_runtime.smolagents_runtime")
    if backend_module is not None:
        monkeypatch.setattr(backend_module, "MINIO_DEFAULT_BUCKET", None)
    monkeypatch.setitem(SmolagentsRuntime._to_agent_history.__globals__, "MINIO_DEFAULT_BUCKET", None)
    runtime = SmolagentsRuntime()
    run_info = runtime.to_agent_run_info(_plan())
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "agent_runtime"
        / "smolagents_agent_run_info_golden.json"
    )

    assert _agent_run_info_summary(run_info) == json.loads(
        fixture_path.read_text(encoding="utf-8")
    )


def test_smolagents_runtime_regression_maps_ordinary_skill_memory_knowledge_mcp_and_managed_agents():
    root_agent = AgentSpec(
        agent_id=1,
        name="root",
        description="Root agent",
        model_name="main_model",
        max_steps=5,
        prompt=PromptBundle(rendered_legacy_system_prompt="Legacy system prompt."),
        tools=[
            ToolSpec(name="local_echo", class_name="EchoTool", source=ToolSource.LOCAL),
            ToolSpec(
                name="mcp_search",
                class_name="search",
                source=ToolSource.MCP,
                usage="docs",
            ),
            ToolSpec(
                name="read_skill_md",
                class_name="ReadSkillMdTool",
                source=ToolSource.SKILL,
                params={"local_skills_dir": "/skills"},
                metadata={
                    "agent_id": 1,
                    "tenant_id": "tenant-1",
                    "version_no": 3,
                },
            ),
            ToolSpec(
                name="search_memory",
                class_name="SearchMemoryTool",
                source=ToolSource.MEMORY,
                metadata={"tenant_id": "tenant-1", "user_id": "user-1"},
            ),
            ToolSpec(
                name="knowledge_base_search",
                class_name="KnowledgeBaseSearchTool",
                source=ToolSource.KNOWLEDGE,
                metadata={"document_paths": ["/docs/a.md"]},
            ),
        ],
        managed_agents=[
            AgentSpec(
                agent_id=2,
                name="researcher",
                description="Research",
                model_name="sub_model",
                max_steps=3,
                prompt=PromptBundle(rendered_legacy_system_prompt="Research."),
                tools=[
                    ToolSpec(
                        name="store_memory",
                        class_name="StoreMemoryTool",
                        source=ToolSource.MEMORY,
                        metadata={
                            "tenant_id": "tenant-1",
                            "user_id": "user-2",
                            "agent_id": "2",
                        },
                    )
                ],
            )
        ],
    )
    plan = _plan(
        root_agent=root_agent,
        mcp_connections=[
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/mcp",
                transport="streamable-http",
            )
        ],
        history=None,
    )

    run_info = SmolagentsRuntime().to_agent_run_info(plan)

    assert run_info.history is None
    assert run_info.mcp_host == [
        {"url": "https://mcp.example/mcp", "transport": "streamable-http"}
    ]
    assert [
        (tool.name, tool.class_name, tool.source, tool.usage)
        for tool in run_info.agent_config.tools
    ] == [
        ("local_echo", "EchoTool", "local", None),
        ("mcp_search", "search", "mcp", "docs"),
        ("read_skill_md", "ReadSkillMdTool", "builtin", None),
        ("search_memory", "SearchMemoryTool", "local", None),
        ("knowledge_base_search", "KnowledgeBaseSearchTool", "local", None),
    ]
    assert run_info.agent_config.tools[2].metadata == {
        "agent_id": 1,
        "tenant_id": "tenant-1",
        "version_no": 3,
    }
    assert run_info.agent_config.tools[2].params == {
        "local_skills_dir": "/skills"
    }
    assert run_info.agent_config.tools[3].metadata == {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    }
    assert run_info.agent_config.tools[4].metadata == {
        "document_paths": ["/docs/a.md"],
    }
    assert run_info.agent_config.managed_agents[0].name == "researcher"
    assert run_info.agent_config.managed_agents[0].tools[0].source == "local"
    assert run_info.agent_config.managed_agents[0].tools[0].metadata == {
        "tenant_id": "tenant-1",
        "user_id": "user-2",
        "agent_id": "2",
    }


@pytest.mark.parametrize(
    ("source", "class_name", "expected_source"),
    [
        (ToolSource.LOCAL, "EchoTool", "local"),
        (ToolSource.MCP, "search", "mcp"),
        (ToolSource.LANGCHAIN, "LangChainTool", "langchain"),
        (ToolSource.BUILTIN, "ReadSkillMdTool", "builtin"),
        (ToolSource.KNOWLEDGE, "KnowledgeBaseSearchTool", "local"),
        (ToolSource.MEMORY, "SearchMemoryTool", "local"),
        (ToolSource.SKILL, "ReadSkillConfigTool", "builtin"),
        (ToolSource.SKILL, "ReadSkillMdTool", "builtin"),
        (ToolSource.SKILL, "RunSkillScriptTool", "builtin"),
        (ToolSource.SKILL, "WriteSkillFileTool", "builtin"),
    ],
)
def test_smolagents_runtime_maps_neutral_tool_sources_to_legacy_sources(
    source,
    class_name,
    expected_source,
):
    tool = ToolSpec(
        name="tool_name",
        class_name=class_name,
        description="Tool description",
        raw_inputs='{"value": {"type": "string"}}',
        input_schema={"value": {"type": "string"}},
        output_type="string",
        source=source,
        params={"setting": "value"},
        metadata={"tenant_id": "tenant-1"},
        usage="server-name",
    )

    tool_config = SmolagentsRuntime._to_tool_config(tool)

    assert tool_config.source == expected_source
    assert tool_config.name == tool.name
    assert tool_config.class_name == class_name
    assert tool_config.description == tool.description
    assert tool_config.inputs == tool.raw_inputs
    assert tool_config.output_type == tool.output_type
    assert tool_config.params == tool.params
    assert tool_config.metadata == tool.metadata
    assert tool_config.usage == tool.usage
    assert tool.source == source


@pytest.mark.parametrize(
    ("source", "class_name"),
    [
        (ToolSource.PLUGIN, "PluginTool"),
        (ToolSource.SKILL, "UnknownSkillTool"),
    ],
)
def test_smolagents_runtime_rejects_unmappable_tool_sources(source, class_name):
    tool = ToolSpec(
        name="unsupported_tool",
        class_name=class_name,
        source=source,
    )

    with pytest.raises(ValueError) as exc_info:
        SmolagentsRuntime._to_tool_config(tool)

    message = str(exc_info.value)
    assert "unsupported_tool" in message
    assert class_name in message
    assert source.value in message


def test_smolagents_runtime_converted_sources_dispatch_in_real_nexent_agent(
    monkeypatch,
):
    import services.agent_runtime.smolagents_runtime as smolagents_runtime_module
    from nexent.core.agents.agent_model import ToolConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import MessageObserver

    monkeypatch.setattr(
        smolagents_runtime_module,
        "_legacy_agent_models",
        lambda: {"ToolConfig": ToolConfig},
    )
    agent = NexentAgent(
        observer=MessageObserver(),
        model_config_list=[],
        stop_event=threading.Event(),
    )
    local_factory = Mock(side_effect=lambda config: config.class_name)
    builtin_factory = Mock(side_effect=lambda config: config.class_name)
    monkeypatch.setattr(agent, "create_local_tool", local_factory)
    monkeypatch.setattr(agent, "create_builtin_tool", builtin_factory)

    tool_configs = [
        SmolagentsRuntime._to_tool_config(
            ToolSpec(
                name="knowledge",
                class_name="KnowledgeBaseSearchTool",
                source=ToolSource.KNOWLEDGE,
            )
        ),
        SmolagentsRuntime._to_tool_config(
            ToolSpec(
                name="memory",
                class_name="SearchMemoryTool",
                source=ToolSource.MEMORY,
            )
        ),
        SmolagentsRuntime._to_tool_config(
            ToolSpec(
                name="skill",
                class_name="RunSkillScriptTool",
                source=ToolSource.SKILL,
            )
        ),
    ]

    assert [agent.create_tool(config) for config in tool_configs] == [
        "KnowledgeBaseSearchTool",
        "SearchMemoryTool",
        "RunSkillScriptTool",
    ]
    assert local_factory.call_count == 2
    assert builtin_factory.call_count == 1


def test_smolagents_runtime_reuses_context_manager_only_for_conversation_runs():
    calls = []
    context_manager = object()

    def fake_get_or_create_context_manager(conversation_id, config, max_steps):
        calls.append(
            {
                "conversation_id": conversation_id,
                "token_threshold": config.token_threshold,
                "max_steps": max_steps,
            }
        )
        return context_manager

    runtime = SmolagentsRuntime(
        context_manager_resolver=fake_get_or_create_context_manager,
    )
    conversation_plan = _plan(
        run_control=RunControl(
            request_id="req-conversation",
            user_id="user-1",
            conversation_id=99,
            metadata={"language": "en"},
        ),
        request_id="req-conversation",
    )
    debug_plan = _plan(
        run_control=RunControl(
            request_id="req-debug",
            user_id="user-1",
            conversation_id=None,
            metadata={"language": "en"},
        ),
        request_id="req-debug",
    )

    assert runtime.to_agent_run_info(conversation_plan).context_manager is context_manager
    assert runtime.to_agent_run_info(debug_plan).context_manager is None
    assert calls == [
        {
            "conversation_id": 99,
            "token_threshold": 32000,
            "max_steps": 8,
        }
    ]


def test_smolagents_runtime_preserves_capacity_safe_budget_verification_and_monitoring_snapshots():
    root_agent = _plan().root_agent.model_copy(
        update={
            "runtime_hints": {
                "capacity_snapshot": {"context_window_tokens": 64000},
                "safe_input_budget_snapshot": {
                    "soft_input_budget_tokens": 60000,
                    "hard_input_budget_tokens": 63000,
                },
                "requested_output_tokens": 2048,
                "provide_run_summary": True,
                "instructions": "Use concise summaries.",
            },
            "verification_config": {
                "enabled": True,
                "max_final_rounds": 3,
            },
        },
        deep=True,
    )
    plan = _plan(root_agent=root_agent)

    run_info = SmolagentsRuntime().to_agent_run_info(plan)

    assert run_info.capacity_snapshot == {"context_window_tokens": 64000}
    assert run_info.safe_input_budget_snapshot == {
        "soft_input_budget_tokens": 60000,
        "hard_input_budget_tokens": 63000,
    }
    assert run_info.agent_config.capacity_snapshot == {"context_window_tokens": 64000}
    assert run_info.agent_config.safe_input_budget_snapshot == {
        "soft_input_budget_tokens": 60000,
        "hard_input_budget_tokens": 63000,
    }
    assert run_info.agent_config.requested_output_tokens == 2048
    assert run_info.agent_config.provide_run_summary is True
    assert run_info.agent_config.instructions == "Use concise summaries."
    assert run_info.agent_config.verification_config.enabled is True
    assert run_info.agent_config.verification_config.max_final_rounds == 3


def test_smolagents_runtime_mcp_mapping_keeps_legacy_toolcollection_and_error_text_path():
    run_info = SmolagentsRuntime().to_agent_run_info(_plan())
    run_agent_path = Path(__file__).resolve().parents[3] / "sdk" / "nexent" / "core" / "agents" / "run_agent.py"
    run_agent_source = run_agent_path.read_text(encoding="utf-8")

    assert run_info.mcp_host == [
        {
            "url": "https://mcp.example/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer token"},
        }
    ]
    assert "ToolCollection.from_mcp" in run_agent_source
    assert "MCP服务器连接超时。" in run_agent_source
    assert "Couldn't connect to the MCP server." in run_agent_source


def test_smolagents_runtime_preserves_existing_legacy_stop_event():
    stop_event = threading.Event()
    stop_event.set()
    runtime = SmolagentsRuntime()
    plan = _plan(stop_event=stop_event)

    run_info = runtime.to_agent_run_info(plan)

    assert run_info.stop_event is stop_event
    assert plan.run_control.is_cancelled() is True


@pytest.mark.asyncio
async def test_smolagents_runtime_run_delegates_to_legacy_agent_run_and_stop_sets_event():
    started = asyncio.Event()
    release = asyncio.Event()
    captured: dict[str, Any] = {}

    async def fake_agent_run(agent_run_info):
        captured["run_info"] = agent_run_info
        started.set()
        await release.wait()
        yield {"type": "final_answer", "content": "done"}

    runtime = SmolagentsRuntime(agent_run_func=fake_agent_run)
    plan = _plan()

    async def consume():
        return [chunk async for chunk in runtime.run(plan)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)

    await runtime.stop(plan.request_id)

    assert plan.run_control.cancelled is True
    assert captured["run_info"].stop_event.is_set() is True

    release.set()
    assert await asyncio.wait_for(task, timeout=1) == [
        {"type": "final_answer", "content": "done"}
    ]


@pytest.mark.asyncio
async def test_smolagents_runtime_run_bridges_legacy_chunks_to_runtime_events():
    async def fake_agent_run(agent_run_info):
        yield '{"type": "step_count", "content": "\\n**Step 1** \\n"}'
        yield {"type": "final_answer", "content": "done"}

    sink = RuntimeEventSink()
    runtime = SmolagentsRuntime(agent_run_func=fake_agent_run)
    plan = _plan()

    chunks = [chunk async for chunk in runtime.run(plan, event_sink=sink)]

    assert chunks == [
        '{"type": "step_count", "content": "\\n**Step 1** \\n"}',
        {"type": "final_answer", "content": "done"},
    ]
    assert [event.type for event in sink.events] == [
        RuntimeEventType.LEGACY_PROCESS,
        RuntimeEventType.LEGACY_PROCESS,
    ]
    assert [event.compat_process_type for event in sink.events] == [
        "step_count",
        "final_answer",
    ]
    assert [event.request_id for event in sink.events] == ["req-1", "req-1"]


@pytest.mark.asyncio
async def test_smolagents_runtime_runs_observable_operator_hooks():
    calls: list[str] = []

    class LifecycleOperator:
        def __init__(self, spec):
            self.spec = spec

        def supports(self, context):
            _ = context
            return True

        def execute(self, context):
            calls.append(context.stage)
            return OperatorResult.ok(
                runtime_events=[
                    RuntimeEvent(
                        type=RuntimeEventType.LEGACY_PROCESS,
                        compat_process_type="other",
                        content=f"operator:{context.stage}",
                    )
                ]
            )

    async def fake_agent_run(agent_run_info):
        _ = agent_run_info
        yield '{"type": "step_count", "content": "step"}'
        yield '{"type": "model_output_thinking", "content": "thought"}'
        yield '{"type": "parse", "content": "args"}'
        yield '{"type": "execution_logs", "content": "tool result"}'
        yield '{"type": "final_answer", "content": "done"}'

    registry = OperatorRegistry({"lifecycle": lambda spec: LifecycleOperator(spec)})
    runtime = SmolagentsRuntime(
        agent_run_func=fake_agent_run,
        operator_registry=registry,
    )
    plan = _plan(
        operators=[
            OperatorSpec(
                name="lifecycle",
                stages={
                    "before_model_call",
                    "after_model_call",
                    "before_tool_call",
                    "after_tool_call",
                    "before_final_answer",
                },
            )
        ]
    )
    sink = RuntimeEventSink()

    chunks = [chunk async for chunk in runtime.run(plan, event_sink=sink)]

    assert len(chunks) == 5
    assert calls == [
        "before_model_call",
        "after_model_call",
        "before_tool_call",
        "after_tool_call",
        "before_final_answer",
    ]
    assert [event.content for event in sink.events if event.compat_process_type == "other"] == [
        "operator:before_model_call",
        "operator:after_model_call",
        "operator:before_tool_call",
        "operator:after_tool_call",
        "operator:before_final_answer",
    ]


@pytest.mark.asyncio
async def test_smolagents_runtime_reconciles_legacy_stop_event_after_run_finishes():
    async def fake_agent_run(agent_run_info):
        agent_run_info.stop_event.set()
        yield {"type": "stopped"}

    runtime = SmolagentsRuntime(agent_run_func=fake_agent_run)
    plan = _plan()

    chunks = [chunk async for chunk in runtime.run(plan)]

    assert chunks == [{"type": "stopped"}]
    assert plan.run_control.cancelled is True


def _agent_run_info_summary(run_info: FakeAgentRunInfo) -> dict[str, Any]:
    return {
        "query": run_info.query,
        "models": [
            {
                "cite_name": model.cite_name,
                "model_name": model.model_name,
                "url": model.url,
                "model_factory": model.model_factory,
                "max_output_tokens": model.max_output_tokens,
                "context_window_tokens": model.context_window_tokens,
            }
            for model in run_info.model_config_list
        ],
        "agent": _agent_config_summary(run_info.agent_config),
        "mcp_host": run_info.mcp_host,
        "history": [
            {
                "role": item.role,
                "content": item.content,
            }
            for item in (run_info.history or [])
        ],
        "capacity_snapshot": run_info.capacity_snapshot,
        "safe_input_budget_snapshot": run_info.safe_input_budget_snapshot,
    }


def _agent_config_summary(agent_config: FakeAgentConfig) -> dict[str, Any]:
    return {
        "name": agent_config.name,
        "description": agent_config.description,
        "model_name": agent_config.model_name,
        "max_steps": agent_config.max_steps,
        "prompt_templates": agent_config.prompt_templates,
        "tools": [
            {
                "name": tool.name,
                "class_name": tool.class_name,
                "source": tool.source,
                "usage": tool.usage,
                "inputs": tool.inputs,
                "params": tool.params,
                "metadata": tool.metadata,
            }
            for tool in agent_config.tools
        ],
        "managed_agents": [
            _agent_config_summary(managed_agent)
            for managed_agent in agent_config.managed_agents
        ],
        "external_a2a_agents": [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "description": agent.description,
                "url": agent.url,
            }
            for agent in agent_config.external_a2a_agents
        ],
        "context_manager_config": {
            "enabled": agent_config.context_manager_config.enabled,
            "token_threshold": agent_config.context_manager_config.token_threshold,
            "soft_input_budget_tokens": agent_config.context_manager_config.soft_input_budget_tokens,
            "hard_input_budget_tokens": agent_config.context_manager_config.hard_input_budget_tokens,
            "keep_recent_steps": agent_config.context_manager_config.keep_recent_steps,
        },
        "context_components": agent_config.context_components,
        "capacity_snapshot": agent_config.capacity_snapshot,
        "safe_input_budget_snapshot": agent_config.safe_input_budget_snapshot,
        "verification_config": {
            "enabled": agent_config.verification_config.enabled,
            "max_final_rounds": agent_config.verification_config.max_final_rounds,
        },
    }
