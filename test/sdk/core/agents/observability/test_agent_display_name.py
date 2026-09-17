"""UT-SDK-TRACE-019/020: display names never replace executable identifiers."""

from threading import Event
from types import SimpleNamespace

import pytest

from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata

from .conftest import by_name


@pytest.mark.parametrize("display_name", [None, "知识助手"])
def test_ut_sdk_trace_019_configuration_round_trip(display_name):
    config = AgentConfig(
        name="knowledge_agent", display_name=display_name, description="test", model_name="model", tools=[],
    )
    restored = AgentConfig.model_validate_json(config.model_dump_json())
    assert restored.name == "knowledge_agent"
    assert restored.display_name == display_name


@pytest.mark.parametrize("display_name", [None, "", " \t "])
def test_ut_sdk_trace_019_missing_display_name_falls_back(spans, display_name):
    with spans.manager.start_agent_run(AgentRunMetadata(agent_name="variable", agent_display_name=display_name)):
        pass
    run, = spans.exporter.get_finished_spans()
    assert run.attributes["langfuse.trace.name"] == "variable"


@pytest.mark.parametrize("display_name,expected", [(None, "knowledge_agent"), ("知识助手", "知识助手")])
def test_ut_sdk_trace_019_direct_sdk_execution(spans, mocker, display_name, expected):
    observer = MessageObserver()
    agent = CoreAgent(
        observer=observer, tools=[], model=mocker.Mock(), name="knowledge_agent", display_name=display_name,
    )
    factory = NexentAgent(observer=observer, model_config_list=[], stop_event=Event())
    factory.set_agent(agent)
    previous_runtime_name = agent.agent_name
    mocker.patch.object(agent, "run", return_value=iter([SimpleNamespace(output="done")]))
    factory.agent_run_with_observer("test")
    assert agent.name == "knowledge_agent"
    assert agent.agent_name == previous_runtime_name
    assert agent.display_name == display_name
    run = by_name(spans)["agent.run"]
    assert run.attributes["langfuse.trace.name"] == expected
    assert run.attributes["agent.name"] == "knowledge_agent"


def test_ut_sdk_trace_019_factory_passes_display_name(mocker):
    factory = NexentAgent(observer=MessageObserver(), model_config_list=[], stop_event=Event())
    mocker.patch.object(factory, "create_model", return_value=mocker.Mock())
    config = AgentConfig(
        name="knowledge_agent", display_name="知识助手", description="test", model_name="model", tools=[],
    )
    agent = factory.create_single_agent(config)
    assert agent.name == "knowledge_agent"
    assert agent.display_name == "知识助手"
