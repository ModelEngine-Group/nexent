"""Configuration cloning preserves services but isolates invocation data."""

from dataclasses import dataclass
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import (
    AgentConfig,
    ToolConfig,
    copy_invocation_config,
)
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.utils.observer import MessageObserver


class InjectedClient:
    def __deepcopy__(self, memo):
        raise RecursionError("Injected clients must not be copied")


@dataclass
class Options:
    values: list
    client: object


@pytest.mark.parametrize("nested", [False, True])
def test_clone_isolates_configuration_and_preserves_service_identity(nested):
    client = InjectedClient()
    options = Options([1], client)
    worker = AgentConfig(name="worker", description="Worker", model_name="model", tools=[
        ToolConfig(name="tool", class_name="Tool", params={"options": options},
                   metadata={"client": client, "items": [{"value": 1}]}),
    ])
    source = AgentConfig(name="parent", description="Parent", model_name="model", tools=[],
                         worker_agents=[worker]) if nested else worker
    left, right = copy_invocation_config(source), copy_invocation_config(source)
    left_tool = (left.worker_agents[0] if nested else left).tools[0]
    right_tool = (right.worker_agents[0] if nested else right).tools[0]
    left_tool.params["options"].values.append(2)
    left_tool.metadata["items"][0]["value"] = 99
    assert left is not right and right is not source
    assert right_tool.params["options"].values == options.values == [1]
    assert right_tool.metadata["items"] == worker.tools[0].metadata["items"] == [{"value": 1}]
    assert left_tool.metadata["client"] is right_tool.metadata["client"] is client
    assert left_tool.params["options"].client is right_tool.params["options"].client is client


def test_clone_preserves_cycles_without_sharing_mutable_metadata():
    source = AgentConfig(name="worker", description="Worker", model_name="model", tools=[
        ToolConfig(name="tool", class_name="Tool", metadata={}),
    ])
    metadata = source.tools[0].metadata
    metadata["self"] = metadata
    cloned = copy_invocation_config(source)
    assert cloned.tools[0].metadata is not metadata
    assert cloned.tools[0].metadata["self"] is cloned.tools[0].metadata


def test_invocation_factory_passes_isolated_config_and_original_client_to_tools(monkeypatch):
    from nexent.core.agents import nexent_agent

    class FakeCore:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.state = {}

        def __call__(self, task):
            return task

    captured = []
    monkeypatch.setattr(nexent_agent, "CoreAgent", FakeCore)
    monkeypatch.setattr(NexentAgent, "create_model", lambda *_args: SimpleNamespace())

    def create_tool(_owner, config):
        captured.append(config)
        return Mock()

    monkeypatch.setattr(NexentAgent, "create_tool", create_tool)
    client = InjectedClient()
    config = AgentConfig(name="worker", description="Worker", model_name="model", tools=[
        ToolConfig(name="tool", class_name="Tool", params={"options": [1]}, metadata={"client": client}),
    ])
    factory = NexentAgent(MessageObserver(), [], Event())
    child = factory._create_subagent_definition(config, {})
    assert child(task="left") == "left"
    assert child(task="right") == "right"
    assert len(captured) == 2
    assert all(tool.metadata["client"] is client for tool in captured)
    captured[0].params["options"].append(2)
    assert captured[1].params["options"] == config.tools[0].params["options"] == [1]
    assert not factory._subagent_invocations
