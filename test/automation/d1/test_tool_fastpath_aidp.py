"""TFP-D1-001/002/004/005: official AIDP admission and preserved permissions."""

from __future__ import annotations

import json
import threading
import uuid
from types import SimpleNamespace

import httpx
import pytest
from smolagents.default_tools import FinalAnswerTool

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.agents.tool_fastpath import (
    OFFICIAL_FASTPATH_TOOL_CLASSES,
    DeferredToolExecutor,
    official_fastpath_tools,
)
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool
from nexent.core.tools.ind_aidp_search_tool import IndependentAidpSearchTool
from nexent.core.utils.observer import MessageObserver, ProcessType
from test.automation.d1.test_tool_fastpath import OrdinaryExecutor


@pytest.fixture
def aidp_runtime(monkeypatch):
    """Use a real factory/tool with a controlled HTTP transport and no provider I/O."""
    import nexent.core.agents.sandbox as sandbox_module
    import nexent.core.ext_components.aidp.aidp_search_tool as aidp_module

    requests, events, acquisitions, releases = [], [], [], []
    status = SimpleNamespace(code=200)

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(status.code, json={"result": [{
            "id": "record-1", "title": "Fixture rule", "text": "fixture-answer",
            "chunk_type": "text", "score": 0.9,
        }]})

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(aidp_module.http_client_manager, "get_sync_client", lambda **kwargs: client)
    observer = MessageObserver()
    monkeypatch.setattr(observer, "add_message", lambda *args, **kwargs: events.append((args, kwargs)))
    ordinary = OrdinaryExecutor(execute=False)

    def acquire(**kwargs):
        acquisitions.append(kwargs)
        return ordinary

    monkeypatch.setattr(sandbox_module, "build_python_executor", acquire)
    monkeypatch.setattr(sandbox_module, "cleanup_executor", lambda ex, *args, **kwargs: releases.append(ex))
    runtime = NexentAgent(
        observer=observer, model_config_list=[], stop_event=threading.Event(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
        tool_fastpath_enabled=True,
    )
    monkeypatch.setattr(runtime, "create_model", lambda _: SimpleNamespace(model_id="fixture"))
    config = ToolConfig(
        class_name="AidpSearchTool", name="aidp_search", source="local",
        params={
            "server_url": "http://aidp.fixture.invalid", "api_key": "fixture-" + uuid.uuid4().hex,
            "tenant_id": "fixture-tenant", "kds_list": '["kb-allowed", "kb-denied"]',
        },
        metadata={
            "allowed_kds_set": ["kb-allowed"],
            "kds_name_to_id_map": {"Allowed": "kb-allowed", "Denied": "kb-denied"},
        },
    )

    def create():
        agent = runtime.create_single_agent(AgentConfig(
            name="fixture", description="AIDP fixture", model_name="fixture", tools=[config],
        ))
        runtime.agent = agent
        agent._wrap_visible_tool_events()
        agent.python_executor.send_tools(agent.tools)
        agent.python_executor.send_variables(agent.state)
        return agent

    try:
        yield SimpleNamespace(
            create=create, runtime=runtime, config=config, requests=requests, events=events,
            acquisitions=acquisitions, releases=releases, ordinary=ordinary, status=status,
        )
    finally:
        runtime._cleanup_sandbox()
        client.close()


@pytest.mark.parametrize("allowed", [["kb-allowed"], []])
def test_tfp_d1_001_aidp(aidp_runtime, allowed):
    """TFP-D1-001: real AIDP filtering, results and events avoid all Docker acquisition."""
    agent = aidp_runtime.create()
    tool = agent.tools["aidp_search"]
    tool.set_allowed_kds(allowed)
    executor = agent.python_executor
    assert isinstance(executor, DeferredToolExecutor)
    output = executor('result = aidp_search(query="rules", kds_list=["Allowed", "Denied"])\nprint(result)')
    if allowed:
        assert "fixture-answer" in output.logs
        assert [request["kds_list"] for request in aidp_runtime.requests] == [["kb-allowed"]]
    else:
        assert "search was not executed" in output.logs
        assert aidp_runtime.requests == []
    assert "no read permission" in output.logs
    answer = executor("final_answer(result)")
    assert answer.is_final_answer
    assert answer.output == executor.local.state["result"]
    tool_events = [
        event for event in aidp_runtime.events
        if event[0][1] == ProcessType.TOOL and event[1].get("tool_name") == "aidp_search"
    ]
    assert len(tool_events) == 1
    assert tool_events[0][1]["tool_arguments"]["query"] == "rules"
    aidp_runtime.runtime._cleanup_sandbox()
    assert aidp_runtime.acquisitions == []
    assert aidp_runtime.releases == []


def test_tfp_d1_002_aidp(aidp_runtime):
    """TFP-D1-002: an AIDP mixed step delegates intact before any provider request."""
    executor = aidp_runtime.create().python_executor
    source = 'result = aidp_search(query="rules")\nimport math'
    executor(source)
    assert len(aidp_runtime.acquisitions) == 1
    assert aidp_runtime.ordinary.calls == ["[0, None]", source]
    assert aidp_runtime.requests == []


@pytest.mark.parametrize("identity", ["mcp", "custom", "subclass", "independent", "omitted"])
def test_tfp_d1_004_aidp(aidp_runtime, identity):
    """TFP-D1-004: same-name AIDP variants and explicit omission cannot qualify."""
    config = aidp_runtime.config.model_copy()
    tool = aidp_runtime.runtime.create_tool(config)
    allowed_classes = OFFICIAL_FASTPATH_TOOL_CLASSES
    if identity == "mcp":
        config.source = "mcp"
    elif identity == "custom":
        tool = SimpleNamespace(name="aidp_search")
    elif identity == "subclass":
        class DerivedAidp(AidpSearchTool):
            pass

        tool = object.__new__(DerivedAidp)
    elif identity == "independent":
        tool = object.__new__(IndependentAidpSearchTool)
        tool.name = "aidp_search"
    else:
        allowed_classes = [name for name in allowed_classes if name != "AidpSearchTool"]
    allowed = official_fastpath_tools([config], [tool], allowed_classes)
    assert allowed == {}
    acquisitions = []

    def acquire():
        acquisitions.append(True)
        return aidp_runtime.ordinary

    wrapper = DeferredToolExecutor(acquire, aidp_runtime.releases.append, allowed)
    wrapper.send_tools({"aidp_search": tool, "final_answer": FinalAnswerTool()})
    source = 'aidp_search(query="rules")'
    wrapper(source)
    assert acquisitions == [True]
    assert aidp_runtime.ordinary.calls == [source]
    assert aidp_runtime.requests == []
    wrapper.cleanup()


def test_tfp_d1_005_aidp(aidp_runtime):
    """TFP-D1-005: AIDP transport errors do not initialize Docker or replay requests."""
    executor = aidp_runtime.create().python_executor
    aidp_runtime.status.code = 400
    with pytest.raises(Exception, match="AIDP HTTP error"):
        executor('aidp_search(query="rules")')
    assert len(aidp_runtime.requests) == 1
    assert aidp_runtime.acquisitions == []
    assert executor.remote is None
