import os
import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.assembly import assemble_agent_run_plan
from services.agent_runtime.models import (
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    CapabilityContribution,
    OperatorSpec,
    PromptBundle,
)
from services.agent_runtime.plugin import (
    DuplicatePluginRegistrationError,
    PluginConfigValidationError,
    PluginRegistry,
    UntrustedPluginRegistrationError,
)
from services.agent_runtime.tool_factory import LocalToolFactory


@dataclass
class Provider:
    name: str
    priority: int = 100
    depends_on: tuple[str, ...] = ()
    contribution: CapabilityContribution | None = None
    calls: list[str] = field(default_factory=list)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        _ = (request, state)
        self.calls.append(self.name)
        return self.contribution or CapabilityContribution()


class EchoTool:
    def __init__(self, text: str):
        self.text = text


def _request(**overrides: Any) -> AgentRunRequestContext:
    payload = {
        "request_id": "req-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        "agent_id": 10,
        "conversation_id": 20,
        "query": "hello",
        "history": [],
        "minio_files": [],
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "language": "zh",
        "is_debug": False,
        "version_no": 3,
    }
    payload.update(overrides)
    return AgentRunRequestContext(**payload)


def _root_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=10,
        name="root",
        description="Root agent",
        model_name="main_model",
        max_steps=5,
        prompt=PromptBundle(fragments={"base": "answer clearly"}),
    )


def test_plugin_registry_registers_trusted_contributions():
    registry = PluginRegistry()
    provider = Provider(name="plugin-provider")
    tool_factory = LocalToolFactory({"EchoTool": EchoTool})
    operator_factory = lambda spec: object()
    runtime = type("PluginRuntime", (), {"name": "plugin-runtime"})()

    def registrar(plugin_registry: PluginRegistry, config: dict[str, Any]) -> None:
        assert config == {"enabled": True}
        plugin_registry.register_provider(provider)
        plugin_registry.register_tool_factory(
            "plugin",
            tool_factory,
            class_name="EchoTool",
        )
        plugin_registry.register_operator("plugin_operator", operator_factory)
        plugin_registry.register_runtime(runtime)

    registry.register_plugin(
        "example",
        registrar,
        config={"enabled": True},
        config_schema={
            "type": "object",
            "required": ["enabled"],
            "properties": {"enabled": {"type": "boolean"}},
        },
    )

    assert registry.list_providers() == [provider]
    assert registry.list_tool_factories()[0].factory is tool_factory
    assert registry.list_tool_factories()[0].source == "plugin"
    assert registry.list_tool_factories()[0].class_name == "EchoTool"
    assert registry.list_operators()[0].name == "plugin_operator"
    assert registry.list_operators()[0].factory is operator_factory
    assert registry.list_runtimes() == [runtime]


def test_plugin_registry_rejects_untrusted_duplicate_and_invalid_config():
    registry = PluginRegistry()

    with pytest.raises(UntrustedPluginRegistrationError, match="not trusted"):
        registry.register_plugin("remote", lambda registry, config: None, trusted=False)

    with pytest.raises(PluginConfigValidationError, match="missing required key"):
        registry.register_plugin(
            "invalid",
            lambda registry, config: None,
            config={},
            config_schema={"type": "object", "required": ["api_key"]},
        )

    registry.register_plugin("example", lambda registry, config: None)
    with pytest.raises(DuplicatePluginRegistrationError, match="Duplicate plugin"):
        registry.register_plugin("example", lambda registry, config: None)


@pytest.mark.asyncio
async def test_assembly_adds_plugin_providers_before_sorting():
    calls: list[str] = []
    context_provider = Provider(
        name="context",
        priority=100,
        contribution=CapabilityContribution(root_agent=_root_agent()),
        calls=calls,
    )
    plugin_provider = Provider(
        name="plugin-provider",
        priority=1,
        depends_on=("context",),
        contribution=CapabilityContribution(
            prompt_fragments={"plugin_fragment": "from plugin"},
            operators=[
                OperatorSpec(
                    name="plugin_operator",
                    stages={"before_run"},
                    required=False,
                )
            ],
        ),
        calls=calls,
    )
    registry = PluginRegistry()
    registry.register_provider(plugin_provider)

    plan = await assemble_agent_run_plan(
        _request(),
        providers=[context_provider],
        plugin_registry=registry,
    )

    assert calls == ["context", "plugin-provider"]
    assert plan.root_agent.prompt.fragments["plugin_fragment"] == "from plugin"
    assert plan.operators[0].name == "plugin_operator"
