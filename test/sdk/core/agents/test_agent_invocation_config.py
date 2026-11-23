# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
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
        tool = Mock()
        tool.name = config.name
        return tool

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


@pytest.mark.parametrize("enabled, allowed", [
    (True, None), (True, []), (True, ["ReadSkillConfigTool"]),
    (False, None), (False, ["ReadSkillConfigTool"]),
])
def test_child_invocations_inherit_fastpath_policy_and_release_distinct_executors(monkeypatch, enabled, allowed):
    from nexent.core.agents import nexent_agent, sandbox

    executors = []

    class FakeCore:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.state = {}
            self.python_executor = kwargs["executor"]
            executors.append(self.python_executor)

        def __call__(self, task):
            self.python_executor.send_tools({tool.name: tool for tool in self.tools})
            return self.python_executor(task)

    build = Mock(side_effect=lambda **kwargs: Mock(
        _nexent_backend="docker", _nexent_session_container_group=None,
    ))
    cleanup = Mock()
    monkeypatch.setattr(sandbox, "build_python_executor", build)
    monkeypatch.setattr(sandbox, "SandboxSkillScriptRunner", Mock())
    monkeypatch.setattr(sandbox, "cleanup_executor", cleanup)
    monkeypatch.setattr(nexent_agent, "CoreAgent", FakeCore)
    monkeypatch.setattr(NexentAgent, "create_model", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(NexentAgent, "create_tool", lambda *_args: ReadSkillConfigTool(
        config_overrides={"demo": {"answer": "rules"}}, authorized_skill_names=["demo"],
    ))
    config = AgentConfig(name="worker", description="Worker", model_name="model", tools=[
        ToolConfig(name="read_skill_config", class_name="ReadSkillConfigTool", source="local"),
    ])
    factory = NexentAgent(
        MessageObserver(), [], Event(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER),
        tool_fastpath_enabled=enabled, tool_fastpath_allowed_tools=allowed,
    )
    factory.agent = factory.create_single_agent(AgentConfig(
        name="parent", description="Parent", model_name="model", tools=[], worker_agents=[config],
    ))
    child = factory.agent.managed_agents[0]
    try:
        assert build.call_count == (0 if enabled else 1)
        for _ in range(2):
            result = child(task='result = read_skill_config("demo")\nprint(result)')
            if enabled and allowed != []:
                assert '"answer": "rules"' in result.logs
        left, right = executors[1:]
        assert left is not right
        assert isinstance(left, DeferredToolExecutor) is enabled
        assert isinstance(right, DeferredToolExecutor) is enabled
        expected_children = 0 if enabled and allowed != [] else 2
        assert build.call_count == expected_children + (0 if enabled else 1)
        assert cleanup.call_count == expected_children
        released = [call.args[0] for call in cleanup.call_args_list]
        expected = [executor.remote for executor in (left, right)] if enabled else [left, right]
        assert released == (expected if expected_children else [])
        assert not factory._subagent_invocations
        if enabled:
            with pytest.raises(RuntimeError, match="closed"):
                left('import math')
            with pytest.raises(RuntimeError, match="closed"):
                right('import math')
    finally:
        factory._close_subagent_invocations()
        factory._cleanup_sandbox()
    assert cleanup.call_count == expected_children + (0 if enabled else 1)
