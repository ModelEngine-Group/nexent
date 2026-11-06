# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SDK factory keeps runtime callable identity consistent with model context."""

from threading import Event
from types import SimpleNamespace

from nexent.core.agent_names import resolve_external_agent_configs
from nexent.core.agents import nexent_agent
from nexent.core.agents.agent_model import AgentConfig, ExternalA2AAgentConfig
from nexent.core.agents.context.models import ContextItemInput, ContextItemType
from nexent.core.utils.observer import MessageObserver


def test_factory_aliases_match_context_and_observer_without_mutating_config(mocker):
    original = [
        ExternalA2AAgentConfig(agent_id=str(index), name=name, url="https://unused.invalid")
        for index, name in enumerate(["parallel_probe_a", "bad-name", "parallel_probe_a"], 1)
    ]
    config = AgentConfig(
        name="parent", description="Parent", tools=[], model_name="test_model",
        external_a2a_agents=original,
    )
    items = [ContextItemInput(
        id=f"external_agent:{item.agent_id}", type=ContextItemType.EXTERNAL_AGENT,
        content={"agent_id": item.agent_id, "name": item.name}, source=("test",),
    ) for item in original]
    expected = resolve_external_agent_configs(original)
    factory = nexent_agent.NexentAgent(MessageObserver(lang="en"), [], Event())
    mocker.patch.object(factory, "create_model", return_value=SimpleNamespace())
    core = mocker.patch.object(nexent_agent, "CoreAgent", return_value=SimpleNamespace(enable_planning=False))
    factory.create_single_agent(config, _managed_context=True, context_items_override=items)

    wrappers = core.call_args.kwargs["managed_agents"]
    context = core.call_args.kwargs["context_runtime"].items
    assert [wrapper.name for wrapper in wrappers] == [item.invocation_name for item in expected]
    assert [wrapper._agent_name for wrapper in wrappers] == [item.name for item in original]
    assert [item.content["name"] for item in context] == [item.invocation_name for item in expected]
    assert [item.content["display_name"] for item in context] == [item.name for item in original]
    assert all(item.invocation_name is None for item in config.external_a2a_agents)
    assert [item.content["name"] for item in items] == [item.name for item in original]
