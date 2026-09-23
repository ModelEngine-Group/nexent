"""Focused factory tests for ContextRuntime selection in NexentAgent."""
from __future__ import annotations

import json
import types

import pytest
from threading import Event
from unittest.mock import MagicMock, patch

from sdk.nexent.core.agents.agent_model import AgentConfig, ModelConfig, ToolConfig
from sdk.nexent.core.agents.context import ContextItemInput
from sdk.nexent.core.agents.nexent_agent import NexentAgent
from sdk.nexent.core.agents.context import ContextManagerConfig
from sdk.nexent.core.utils.observer import MessageObserver


def test_ut_sdk_dpr_004_factory_filters_prompt_and_execution_tools_by_run_policy():
    """UT-SDK-DPR-004: a versioned SDK snapshot gates executable and visible tools."""
    factory = _factory()
    configs = [
        ToolConfig(class_name="StubTool", name=name, description=name, metadata={"schema_version": version})
        for name, version in (("allowed", "v1"), ("blocked", "v1"), ("stale", "v0"), ("hidden", "v1"))
    ]
    items = [
        ContextItemInput(id=f"tool:{name}", type="tool", content={"name": name, "description": name})
        for name in ("allowed", "blocked", "stale", "hidden")
    ]
    config = AgentConfig(
        name="agent", description="desc", model_name="main", tools=configs,
        context_items=items,
        prompt_tool_policy_snapshot={
            "enabled": ["allowed", "blocked", "stale"],
            "allowed": ["allowed", "stale"],
            "system_default_hidden": ["hidden"],
            "policy_version": "p1", "tool_schema_version": "v1",
        },
    )
    second_config = config.model_copy(deep=True)
    second_config.prompt_tool_policy_snapshot = {
        "enabled": ["blocked"], "allowed": ["blocked"],
        "system_default_hidden": [],
        "policy_version": "p2", "tool_schema_version": "v1",
    }
    captured_runs = []

    def fake_core_agent(**kwargs):
        captured_runs.append(kwargs)
        return MagicMock(enable_planning=False)

    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch.object(factory, "create_tool", side_effect=lambda tool: MagicMock(name=tool.name)), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent", side_effect=fake_core_agent):
        factory.create_single_agent(config)
        factory.create_single_agent(second_config)

    assert {item.id for item in captured_runs[0]["context_runtime"].items} == {"tool:allowed"}
    assert {item.id for item in captured_runs[1]["context_runtime"].items} == {"tool:blocked"}
    assert len(captured_runs[0]["tools"]) == 2
    assert len(captured_runs[1]["tools"]) == 1
    events = [message for message in factory.observer.message_query if "prompt_tool_registry" in str(message)]
    assert len(events) == 2
    first_audit, second_audit = [json.loads(json.loads(event)["content"]) for event in events]
    assert first_audit["policy_version"] == "p1"
    assert second_audit["policy_version"] == "p2"
    assert first_audit["tool_schema_version"] == second_audit["tool_schema_version"] == "v1"
    assert first_audit["visible_tools"] == ["allowed"]
    assert second_audit["visible_tools"] == ["blocked"]
    assert first_audit["registry_hash"] != second_audit["registry_hash"]


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
    assert "ask_user" in runtime.items[1].content["text"]
    assert "人在回路" in runtime.items[1].content["text"]
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
                         output_protocol="final_envelope" if kind == "nl2skill" else "code_action")
    with patch.object(factory, "create_model", return_value=MagicMock()), \
            patch("sdk.nexent.core.agents.nexent_agent.CoreAgent") as core:
        factory.create_single_agent(config, _managed_context=kind == "child")
    assert core.call_args.kwargs["enable_clarification"] is False
    assert core.call_args.kwargs["context_runtime"].items == [item]
    assert config.context_items == [item]
