# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Component proof: model-visible names reach the correct bridged host Agent."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agent_names import resolve_external_agent_configs
from nexent.core.agents import sandbox
from nexent.core.agents.a2a_agent_proxy import ExternalA2AAgentProxy, ExternalA2AAgentWrapper
from nexent.core.agents.agent_model import ExternalA2AAgentConfig
from nexent.core.agents.context.formatting import _format_external_agents_description
from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.core.concurrency import LanePolicy, ThreadManager


class ControlledKernel:
    """Execute the actual submitted Python while controlling the Jupyter boundary."""

    def __init__(self):
        self.namespace = {}

    def send_tools(self, tools):
        assert tools == {}

    def send_variables(self, variables):
        self.namespace.update(variables)

    def run_code_raise_errors(self, source):
        exec(compile(source, "<controlled-kernel>", "exec"), self.namespace)
        return SimpleNamespace(logs="", output=None, is_final_answer=False)

    __call__ = run_code_raise_errors

    def cleanup(self):
        pass


@pytest.mark.case_id("UT-SDK-AGENT-CALLABLE-001")
@pytest.mark.stage("D1")
@pytest.mark.parametrize("language", ["zh", "en"])
def test_callable_identity_reaches_host_without_breaking_other_tools(monkeypatch, language):
    original = [ExternalA2AAgentConfig(agent_id=str(index), name=name, url="https://unused.invalid/a2a")
                for index, name in enumerate([
                    "parallel_probe_a", "agent-one", "class", "duplicate", "duplicate", "create_directory",
                ], 1)]
    configs = resolve_external_agent_configs(original, {"create_directory"})
    assert configs[0].invocation_name == "parallel_probe_a"
    assert [item.name for item in configs] == [item.name for item in original]
    assert all(item.invocation_name is None for item in original)
    assert len({item.invocation_name for item in configs}) == len(configs)
    assert "create_directory" not in {item.invocation_name for item in configs}
    assert {item.agent_id: item.invocation_name for item in configs} == {
        item.agent_id: item.invocation_name
        for item in resolve_external_agent_configs(list(reversed(original)), {"create_directory"})
    }

    composer = AgentPromptComposer(AgentPromptBundle.from_resource(role="manager", language=language))
    items = composer.compose_context_inputs(
        prompt="Delegate to an external Agent.", language=language, is_manager=True,
        external_a2a_agents={config.agent_id: config for config in configs},
    )
    context = {item.content["agent_id"]: item.content for item in items if item.type.value == "external_agent"}
    visible = _format_external_agents_description(context, language)
    for config in configs:
        assert context[config.agent_id]["name"] == config.invocation_name
        assert context[config.agent_id]["display_name"] == config.name
        assert f" - {config.invocation_name}" in visible
        assert config.name in visible

    calls, directory_calls = [], []

    def remote_call(proxy, query, history, *, context):
        calls.append((proxy.agent_info.agent_id, proxy.agent_info.name, query))
        return f"{proxy.agent_info.agent_id}:{query}"

    monkeypatch.setattr(ExternalA2AAgentProxy, "sync_call", remote_call)
    observer = Mock()
    tools = {}
    for config in configs:
        inner = ExternalA2AAgentWrapper(config.to_a2a_agent_info())
        wrapper = SubAgentToolWrapper(
            inner, observer, agent_id=config.agent_id, agent_name=config.name,
            invocation_name=config.invocation_name,
        )
        assert wrapper.name == context[config.agent_id]["name"]
        tools[wrapper.name] = wrapper

    class DirectoryTool:
        _nexent_execute_on_host = True

        def __call__(self, directory_path):
            directory_calls.append(directory_path)
            return directory_path

    tools["create_directory"] = DirectoryTool()
    manager = ThreadManager(service_name="callable-component", lane_policies={
        "sandbox": LanePolicy(name="sandbox", max_workers=2, max_queue_size=0),
    })
    manager.start()
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: manager)
    kernel = ControlledKernel()
    sandbox._install_host_tool_bridge(kernel, logging.getLogger(__name__))
    bridge = kernel._nexent_tool_bridge
    executor = DeferredToolExecutor(lambda: kernel, lambda item: item.cleanup(), {})
    try:
        executor.send_tools(tools)
        executor.send_variables({})
        executor('create_directory(directory_path="test")')
        assert directory_calls == ["test"]
        for config in configs:
            executor(f'result = {context[config.agent_id]["name"]}(task="hello")')
            assert kernel.namespace["result"] == f"{config.agent_id}:hello"
        assert calls == [(config.agent_id, config.name, "hello") for config in configs]
        starts = observer.add_subagent_start.call_args_list
        assert [(call.kwargs["agent_id"], call.kwargs["agent_name"], call.kwargs["invocation_name"]) for call in starts] == [
            (config.agent_id, config.name, config.invocation_name) for config in configs
        ]
        assert observer.add_subagent_end.call_count == len(configs)
    finally:
        executor.cleanup()
        bridge._thread.join(timeout=2)
        asyncio.run(manager.shutdown(timeout=5))
    assert not bridge._thread.is_alive()
    assert not manager.snapshot().executions
