"""Focused factory tests for ContextRuntime selection in NexentAgent."""
from __future__ import annotations

from threading import Event
from unittest.mock import MagicMock, patch

from sdk.nexent.core.agents.agent_model import AgentConfig, ModelConfig
from sdk.nexent.core.agents.context import ContextItemInput
from sdk.nexent.core.agents.nexent_agent import NexentAgent
from sdk.nexent.core.agents.context import ContextManagerConfig
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


def test_create_single_agent_injects_managed_runtime_and_run_items():
    factory = _factory()
    item = ContextItemInput(id="system:policy", type="system", content={"text": "stable policy"})
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
        context_manager_config=ContextManagerConfig(token_threshold=1000),
        context_items=[item],
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
    assert runtime.items == [item]
    assert runtime.context_manager.get_registered_items() == []


def test_create_single_agent_keeps_managed_runtime_when_compression_disabled():
    factory = _factory()
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
        context_manager_config=ContextManagerConfig(token_threshold=1000),
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
    assert runtime.context_manager.config.policy_layers is not None


def test_create_single_agent_defaults_to_managed_runtime_without_config():
    factory = _factory()
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
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
    assert runtime.context_manager.config.policy_layers is not None
