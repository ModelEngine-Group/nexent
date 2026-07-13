import logging
import os
import sys
import threading
from pathlib import Path

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.config import (
    get_deployment_agent_runtime_provider,
    resolve_agent_runtime_provider_for_request,
)
from services.agent_runtime.models import (
    ActiveRunHandle,
    AgentRunPlan,
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    OperatorSpec,
    PromptBundle,
    RuntimeCapabilities,
    RuntimeCapabilityRequirements,
    RunControl,
    ToolSource,
    ToolRuntimeContext,
    ToolSpec,
    ToolVisibility,
    derive_runtime_capability_requirements,
    negotiate_runtime_capabilities,
)
from services.agent_runtime.registry import (
    AgentRuntimeRegistry,
    DuplicateAgentRuntimeProviderError,
    RuntimeCapabilityNegotiationError,
    UnknownAgentRuntimeProviderError,
    build_default_agent_runtime_registry,
    get_configured_agent_runtime,
)
from services.agent_runtime.smolagents_runtime import SmolagentsRuntime
from services.agent_runtime.tool_schema import (
    AgentRunPlanContractError,
    ToolSchemaConfigurationError,
    assert_agent_run_plan_framework_neutral,
    normalize_tool_input_schema,
    tool_input_schema_to_json_schema,
    tool_spec_from_legacy_tool_config,
)


class _Runtime:
    def __init__(self, name: str):
        self.name = name
        self.capabilities = RuntimeCapabilities()

    async def run(self, plan, event_sink):
        return None

    async def stop(self, request_id: str) -> None:
        return None


def test_runtime_provider_defaults_to_smolagents():
    assert (
        const.normalize_agent_runtime_provider(None)
        == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    )


def test_runtime_provider_normalizes_case_and_whitespace():
    assert (
        const.normalize_agent_runtime_provider("  OpenJiuWen ")
        == const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN
    )


def test_runtime_provider_rejects_unknown_value():
    with pytest.raises(ValueError, match="Unsupported AGENT_RUNTIME_PROVIDER"):
        const.normalize_agent_runtime_provider("unknown")


def test_runtime_provider_env_read_is_centralized():
    repo_root = Path(__file__).resolve().parents[3]
    direct_env_reads = []
    patterns = (
        'os.getenv("AGENT_RUNTIME_PROVIDER"',
        "os.getenv('AGENT_RUNTIME_PROVIDER'",
        'os.environ.get("AGENT_RUNTIME_PROVIDER"',
        "os.environ.get('AGENT_RUNTIME_PROVIDER'",
    )
    for root in (repo_root / "backend", repo_root / "sdk" / "nexent"):
        for path in root.rglob("*.py"):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            if path == repo_root / "backend" / "consts" / "const.py":
                continue
            text = path.read_text(encoding="utf-8")
            if any(pattern in text for pattern in patterns):
                direct_env_reads.append(path.relative_to(repo_root).as_posix())

    assert direct_env_reads == []


def test_registry_register_get_and_list():
    registry = AgentRuntimeRegistry()
    runtime = _Runtime("Example")

    registry.register(runtime)

    assert registry.get("example") is runtime
    assert registry.get(" EXAMPLE ") is runtime
    assert registry.list_providers() == ["example"]


def test_registry_rejects_duplicate_provider():
    registry = AgentRuntimeRegistry([_Runtime("example")])

    with pytest.raises(DuplicateAgentRuntimeProviderError):
        registry.register(_Runtime("example"))


def test_registry_unknown_provider_fails_fast():
    registry = AgentRuntimeRegistry([_Runtime("smolagents")])

    with pytest.raises(
        UnknownAgentRuntimeProviderError,
        match="Unknown agent runtime provider 'openjiuwen'",
    ):
        registry.get("openjiuwen")


def test_default_registry_contains_runtime_spike_extension_points():
    registry = build_default_agent_runtime_registry()

    assert registry.list_providers() == [
        const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN,
        const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
    ]
    assert (
        registry.get(const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS).name
        == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    )
    assert (
        registry.get(const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN).name
        == const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN
    )


def test_configured_runtime_uses_deployment_provider(monkeypatch):
    monkeypatch.setattr(
        const, "AGENT_RUNTIME_PROVIDER", const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN
    )

    runtime = get_configured_agent_runtime()

    assert runtime.name == const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN


def test_request_runtime_provider_override_is_ignored(monkeypatch):
    monkeypatch.setattr(
        const, "AGENT_RUNTIME_PROVIDER", const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    )

    assert (
        get_deployment_agent_runtime_provider()
        == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    )
    assert (
        resolve_agent_runtime_provider_for_request("openjiuwen")
        == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    )


def test_smolagents_capabilities_are_complete_for_default_path():
    runtime = SmolagentsRuntime()

    assert runtime.capabilities.process_type_compatibility == "complete"
    assert runtime.capabilities.mcp is True
    assert runtime.capabilities.managed_agents is True
    assert runtime.capabilities.context_compression is True


def test_capability_negotiation_blocks_missing_required_capability():
    result = negotiate_runtime_capabilities(
        RuntimeCapabilities(mcp=False),
        RuntimeCapabilityRequirements(required={"mcp"}, optional={"tool_artifacts"}),
    )

    assert result.status == "blocking_failure"
    assert result.is_blocking is True
    assert result.missing_required == ["mcp"]


def test_registry_blocks_runtime_lookup_when_required_capability_is_missing():
    registry = AgentRuntimeRegistry([_Runtime("basic")])

    with pytest.raises(
        RuntimeCapabilityNegotiationError, match="required capabilities: mcp"
    ):
        registry.get("basic", RuntimeCapabilityRequirements(required={"mcp"}))


def test_registry_logs_openjiuwen_selection_with_capability_status(caplog):
    caplog.set_level(
        logging.INFO,
        logger="services.agent_runtime.registry",
    )
    runtime = _Runtime(const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN)
    runtime.capabilities = RuntimeCapabilities(streaming=True, mcp=False)
    registry = AgentRuntimeRegistry([runtime])

    selected = registry.get(
        const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN,
        RuntimeCapabilityRequirements(required={"streaming"}, optional={"mcp"}),
    )

    assert selected is runtime
    assert any(
        "Agent runtime provider selected" in record.getMessage()
        and "provider=openjiuwen" in record.getMessage()
        and "capability_status=degraded" in record.getMessage()
        for record in caplog.records
    )


def test_capability_negotiation_reports_optional_downgrade():
    result = negotiate_runtime_capabilities(
        RuntimeCapabilities(mcp=True, tool_artifacts=False),
        RuntimeCapabilityRequirements(required={"mcp"}, optional={"tool_artifacts"}),
    )

    assert result.status == "degraded"
    assert result.is_blocking is False
    assert result.downgraded_optional == ["tool_artifacts"]


def test_capability_requirements_are_derived_from_actual_agent_configuration():
    root = AgentSpec(
        agent_id=1,
        name="root",
        model_name="main_model",
        max_steps=3,
        prompt=PromptBundle(fragments={"duty": "answer"}),
        managed_agents=[
            AgentSpec(
                agent_id=2,
                name="child",
                model_name="main_model",
                max_steps=2,
            )
        ],
        verification_config={"enabled": True},
    )

    requirements = derive_runtime_capability_requirements(
        root,
        [
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/sse",
                transport="sse",
                required=True,
            )
        ],
    )

    assert {
        "streaming",
        "interruptible",
        "mcp",
        "managed_agents",
        "verification",
    }.issubset(requirements.required)


def test_agent_run_request_context_preserves_deployment_runtime_provider():
    context = AgentRunRequestContext(
        request_id="req-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        agent_id=123,
        query="hello",
        user_id="user-1",
        tenant_id="tenant-1",
        language="zh",
        version_no=3,
        override_model_id=9,
        requested_output_tokens=1024,
        tool_params={"tool": {"k": "v"}},
    )

    assert context.runtime_provider == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    assert context.conversation_id is None
    assert context.tool_params == {"tool": {"k": "v"}}


def test_run_control_cancel_sets_legacy_stop_event():
    stop_event = threading.Event()
    run_control = RunControl(
        request_id="req-1",
        user_id="user-1",
        conversation_id=10,
        legacy_stop_event=stop_event,
    )

    assert run_control.is_cancelled() is False

    run_control.cancel()

    assert run_control.is_cancelled() is True
    assert stop_event.is_set() is True


def test_active_run_handle_wraps_run_control_and_legacy_info():
    run_control = RunControl(request_id="req-1", user_id="user-1")
    legacy_info = object()

    handle = ActiveRunHandle(
        request_id="req-1",
        user_id="user-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        run_control=run_control,
        legacy_agent_run_info=legacy_info,
    )

    assert handle.status == "starting"
    assert handle.legacy_agent_run_info is legacy_info
    assert handle.run_control is run_control


def test_agent_run_plan_accepts_neutral_agent_tool_and_context_types():
    tool = ToolSpec(
        name="search",
        description="Search docs",
        input_schema={"type": "object"},
        source=ToolSource.KNOWLEDGE,
        visibility=ToolVisibility.MODEL,
        metadata={"document_paths": ["/doc"]},
    )
    agent = AgentSpec(
        agent_id=1,
        name="root",
        model_name="main_model",
        max_steps=5,
        prompt=PromptBundle(fragments={"skills": []}),
        tools=[tool],
        context_policy=ContextPolicy(mode=ContextMode.LEGACY),
    )
    run_control = RunControl(request_id="req-1", user_id="user-1")

    plan = AgentRunPlan(
        request_id="req-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        query="hello",
        root_agent=agent,
        mcp_connections=[
            MCPConnectionConfig(
                name="docs",
                url="http://localhost/mcp",
                transport="streamable-http",
            )
        ],
        operators=[OperatorSpec(name="monitor", stages={"before_run"})],
        run_control=run_control,
    )

    assert plan.root_agent.tools[0].source == ToolSource.KNOWLEDGE
    assert plan.mcp_connections[0].transport == "streamable-http"
    assert plan.operators[0].name == "monitor"


def test_tool_runtime_context_carries_hidden_system_resources():
    run_control = RunControl(request_id="req-1", user_id="user-1")
    context = ToolRuntimeContext(
        request_id="req-1",
        agent_name="root",
        user_id="user-1",
        tenant_id="tenant-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        run_control=run_control,
        resources={"storage.client": object()},
    )

    assert context.runtime_provider == const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    assert context.run_control is run_control
    assert "storage.client" in context.resources


def test_assembly_state_collects_provider_contributions():
    tool = ToolSpec(name="search", source=ToolSource.LOCAL)
    state = AssemblyState(
        agent_record={"agent_id": 1},
        version_no=2,
        tools_by_agent={"root": [tool]},
        prompt_fragments={"duty": "answer"},
        runtime_resources={"memory.config": {"enabled": True}},
    )

    assert state.agent_record["agent_id"] == 1
    assert state.tools_by_agent["root"][0].name == "search"
    assert state.runtime_resources["memory.config"]["enabled"] is True


def test_tool_config_inputs_json_string_normalizes_to_tool_spec_schema():
    legacy_tool = type("LegacyToolConfig", (), {})()
    legacy_tool.class_name = "SearchTool"
    legacy_tool.name = "search"
    legacy_tool.description = "Search documents"
    legacy_tool.inputs = '{"query": {"type": "string"}, "top_k": {"type": "integer"}}'
    legacy_tool.output_type = "string"
    legacy_tool.params = {"top_k": 3}
    legacy_tool.source = "local"
    legacy_tool.usage = None
    legacy_tool.metadata = {"document_paths": ["/allowed/doc"]}

    tool_spec = tool_spec_from_legacy_tool_config(legacy_tool)

    assert tool_spec.name == "search"
    assert tool_spec.input_schema == {
        "query": {"type": "string"},
        "top_k": {"type": "integer"},
    }
    assert tool_spec.raw_inputs == legacy_tool.inputs
    assert tool_spec.metadata["document_paths"] == ["/allowed/doc"]


def test_legacy_tool_type_shorthand_converts_to_provider_safe_json_schema():
    inputs = {
        "skill_name": "str",
        "script_path": "str",
        "params": "dict",
        "additional_files": "list[str]",
    }

    normalized = normalize_tool_input_schema(inputs, tool_name="run_skill_script")
    json_schema = tool_input_schema_to_json_schema(
        normalized,
        tool_name="run_skill_script",
    )

    assert normalized == {
        "skill_name": {"type": "string"},
        "script_path": {"type": "string"},
        "params": {"type": "object"},
        "additional_files": {
            "type": "array",
            "items": {"type": "string"},
        },
    }
    assert json_schema == {
        "type": "object",
        "properties": normalized,
        "required": [
            "skill_name",
            "script_path",
            "params",
            "additional_files",
        ],
    }


def test_tool_config_inputs_invalid_json_is_diagnostic():
    with pytest.raises(ToolSchemaConfigurationError, match="bad_tool.*invalid JSON"):
        normalize_tool_input_schema("{not-json}", tool_name="bad_tool")


def test_tool_config_inputs_must_decode_to_json_object():
    with pytest.raises(
        ToolSchemaConfigurationError, match="must decode to a JSON object"
    ):
        normalize_tool_input_schema('["query"]', tool_name="bad_tool")


def test_model_visible_tool_schema_rejects_system_injected_params():
    with pytest.raises(ToolSchemaConfigurationError, match="document_paths"):
        normalize_tool_input_schema(
            '{"query": {"type": "string"}, "document_paths": {"type": "array"}}',
            tool_name="knowledge_search",
        )


def test_json_schema_properties_reject_system_injected_params():
    with pytest.raises(ToolSchemaConfigurationError, match="storage_client"):
        normalize_tool_input_schema(
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "storage_client": {"type": "object"},
                },
            },
            tool_name="file_reader",
        )


def test_agent_run_plan_contract_allows_neutral_runtime_resources():
    agent = AgentSpec(
        agent_id=1,
        name="root",
        model_name="main_model",
        max_steps=5,
    )
    plan = AgentRunPlan(
        request_id="req-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        query="hello",
        root_agent=agent,
        runtime_resources={"knowledge.document_paths": ["/doc"]},
        run_control=RunControl(request_id="req-1", user_id="user-1"),
    )

    assert_agent_run_plan_framework_neutral(plan)


def test_agent_run_plan_contract_rejects_framework_native_types():
    NativeOpenJiuwenAgentCard = type(
        "AgentCard",
        (),
        {"__module__": "openjiuwen.agent"},
    )
    agent = AgentSpec(
        agent_id=1,
        name="root",
        model_name="main_model",
        max_steps=5,
        runtime_hints={"native_agent_card": NativeOpenJiuwenAgentCard()},
    )
    plan = AgentRunPlan(
        request_id="req-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN,
        query="hello",
        root_agent=agent,
        run_control=RunControl(request_id="req-1", user_id="user-1"),
    )

    with pytest.raises(AgentRunPlanContractError, match="openjiuwen.agent.AgentCard"):
        assert_agent_run_plan_framework_neutral(plan)
