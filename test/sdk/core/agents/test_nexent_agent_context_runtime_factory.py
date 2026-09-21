"""Focused factory tests for ContextRuntime selection in NexentAgent."""
from __future__ import annotations

import types

import pytest
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
        factory.create_single_agent(config)  # NOSONAR - trusted local test double.
        factory.create_single_agent(config)
        assert config.context_items == [item]

    runtime = captured["context_runtime"]
    assert type(runtime).__name__ == "ManagedContextRuntime"
    assert runtime.items[0] == item
    assert runtime.items[1].id == "system:clarification_protocol"
    assert "ends the current execution" in runtime.items[1].content["text"]
    assert captured["enable_clarification"] is True
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


def test_create_single_agent_preserves_explicit_empty_authorized_snapshot():
    factory = _factory()
    stale_item = ContextItemInput(
        id="system:stale",
        type="system",
        content={"text": "must not be restored"},
    )
    config = AgentConfig(
        name="agent",
        description="desc",
        model_name="main",
        tools=[],
        context_items=[stale_item],
    )
    captured = {}

    def fake_core_agent(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent", side_effect=fake_core_agent):
        factory.create_single_agent(  # NOSONAR - trusted local test double.
            config, context_items_override=()
        )

    assert captured["context_runtime"].items == []


def test_each_managed_agent_runtime_owns_one_distinct_context_manager():
    factory = _factory()
    child_a = AgentConfig(name="child-a", description="a", model_name="main", tools=[])
    child_b = AgentConfig(name="child-b", description="b", model_name="main", tools=[])
    root = AgentConfig(
        name="root",
        description="root",
        model_name="main",
        tools=[],
        managed_agents=[child_a, child_b],
    )
    created_agents = []

    def fake_core_agent(**kwargs):
        agent = types.SimpleNamespace(
            context_runtime=kwargs["context_runtime"],
            stop_event=None,
            enable_planning=False,
        )
        created_agents.append(agent)
        return agent

    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent", side_effect=fake_core_agent):
        main_agent = factory.create_single_agent(  # NOSONAR - trusted local test double.
            root
        )

    managers = [agent.context_runtime.context_manager for agent in created_agents]
    assert len(managers) == 3
    assert len({id(manager) for manager in managers}) == 3
    assert main_agent is created_agents[-1]
    assert all(not hasattr(agent, "context_manager") for agent in created_agents)


@pytest.mark.parametrize("kind", ["child", "nl2agent", "nl2skill"])
def test_clarification_policy_is_not_injected_into_other_protocols(kind):
    factory = _factory()
    factory.observer.enable_nl2a_wrapper = kind == "nl2agent"
    item = ContextItemInput(id="system:policy", type="system", content={"text": "original policy"})
    config = AgentConfig(name="agent", description="test", model_name="main", tools=[], context_items=[item],
                         output_protocol="final_answer_envelope" if kind == "nl2skill" else "code_action")
    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent") as core:
        factory.create_single_agent(config, _managed_context=kind == "child")
    assert core.call_args.kwargs["enable_clarification"] is False
    assert core.call_args.kwargs["context_runtime"].items == [item]
    assert config.context_items == [item]
