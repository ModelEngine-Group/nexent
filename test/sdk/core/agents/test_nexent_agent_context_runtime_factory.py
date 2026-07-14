"""Focused factory tests for ContextRuntime selection in NexentAgent."""
from __future__ import annotations

from threading import Event
from unittest.mock import MagicMock, patch

from sdk.nexent.core.agents.agent_model import AgentConfig, ModelConfig, SystemPromptComponent
from sdk.nexent.core.agents.nexent_agent import NexentAgent
from sdk.nexent.core.agents.summary_config import ContextManagerConfig
from sdk.nexent.core.utils.observer import MessageObserver


def _factory() -> NexentAgent:
    return NexentAgent(
        observer=MessageObserver(),
        model_config_list=[
            ModelConfig(
                cite_name="main",
                model_name="model",
                url="https://example.invalid",
                model_factory="unknown",
            )
        ],
        stop_event=Event(),
    )


def test_create_single_agent_injects_managed_runtime_and_registers_components():
    factory = _factory()
    component = SystemPromptComponent(content="stable policy")
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
        context_manager_config=ContextManagerConfig(enabled=True, token_threshold=1000),
        context_components=[component],
    )
    captured = {}

    def fake_core_agent(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent", side_effect=fake_core_agent):
        factory.create_single_agent(config)

    runtime = captured["context_runtime"]
    assert type(runtime).__name__ == "ManagedContextRuntime"
    assert runtime.components == [component]
    assert runtime.context_manager.get_registered_components() == []


def test_create_single_agent_normalizes_disabled_config_to_managed_runtime():
    factory = _factory()
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
        context_manager_config=ContextManagerConfig(enabled=False, token_threshold=1000),
    )
    captured = {}

    def fake_core_agent(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent", side_effect=fake_core_agent):
        factory.create_single_agent(config)

    runtime = captured["context_runtime"]
    assert type(runtime).__name__ == "ManagedContextRuntime"
    assert runtime.context_manager is not None
    assert runtime.context_manager.config.enabled is True
    assert runtime.context_manager.config.token_threshold == 1000
