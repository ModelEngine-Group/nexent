"""AIDP factory fixture with controlled HTTP transport and resource cleanup."""

from __future__ import annotations

import json
import threading
import uuid
from types import SimpleNamespace

import httpx
import pytest

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.utils.observer import MessageObserver
from shared.tool_fastpath import FinalEnvelopeModel, OrdinaryExecutor


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
    monkeypatch.setattr(runtime, "create_model", lambda _: FinalEnvelopeModel())
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
            enable_protocol_repair_retry=True,
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
