# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real factory/worker/transport collaboration shared by the two runtime Cases."""

import asyncio
import json
import threading
from contextlib import nullcontext
from unittest.mock import Mock

from jiuwen_bridge_fixture import profile_for, provider
import nexent.core.tools as nexent_agent
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


async def run_worker(monkeypatch, protocol, scenario="normal"):
    def forbidden(*args, **kwargs):
        raise AssertionError("Native HTTP client or CodeAgent was constructed")

    monkeypatch.setattr("openjiuwen.core.foundation.llm.model.create_model_client", forbidden)
    monkeypatch.setattr(CoreAgent, "__init__", forbidden)
    from nexent.core.agents.cores.smolagents.agent import NexentAgent
    monkeypatch.setattr(NexentAgent, "__init__", forbidden)
    # Keep real model transport and observer events, but isolate the external monitoring sink.
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *args, **kwargs: nullcontext(None)
    monkeypatch.setattr("nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring)
    owned_cards = []
    prepare = JiuwenAdapter.prepare

    def track_prepare(adapter):
        prepare(adapter)
        owned_cards.extend(card.id for card in adapter.native_agent.ability_manager.list())

    monkeypatch.setattr(JiuwenAdapter, "prepare", track_prepare)
    async with provider(scenario, protocol) as (url, state):
        class BridgeAddTool:
            name, description = "add", "Add integers"
            inputs = {"a": {"type": "integer"}, "b": {"type": "integer"}}

            def forward(self, a, b):
                state["tool_calls"].append((a, b))
                return a + b

        monkeypatch.setattr(nexent_agent, "BridgeAddTool", BridgeAddTool, raising=False)
        profile = profile_for(url, protocol)
        manager = ThreadManager("jiuwen-bridge-tests", {
            name: LanePolicy(name=name, max_workers=2, max_queue_size=8)
            for name in ("agent-run", "model-tool-io", "mcp-session", "background-service", "sandbox", "control-io")
        })
        manager.start()
        info = AgentRunInfo(
            query="Compute 2 plus 3", observer=MessageObserver(lang="en"), stop_event=threading.Event(),
            thread_manager=manager, tenant_id="spike-tenant",
            model_config_list=[ModelConfig(cite_name="fixture", model_name=profile.identity.request_model_id,
                                           url=profile.connection.base_url, api_key="fixture-only",
                                           resolved_profile=profile)],
            agent_config=AgentConfig(agent_core="jiuwen", name="bridge-runtime", description="Fixture",
                                    model_name="fixture", max_steps=3, instructions="Answer the current request.",
                                    tools=[ToolConfig(name="add", class_name="BridgeAddTool",
                                                      source="local", params={})]),
        )
        async def cancel_after_first_response():
            while not state["requests"]:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)
            info.stop_event.set()

        canceller = asyncio.create_task(cancel_after_first_response()) if scenario == "cancel" else None
        try:
            output = [json.loads(event) async for event in agent_run(info, thread_manager=manager)]
        finally:
            if canceller is not None:
                await canceller
            drained = await manager.shutdown(timeout=5)
            assert not drained.stuck_execution_ids
        from openjiuwen.core.runner import Runner

        assert all(Runner.resource_mgr.get_tool(card_id) is None for card_id in owned_cards)
        assert manager.snapshot().active_count == 0
        if scenario == "cancel":
            for _ in range(50):
                if state.get("cancel_response_closed"):
                    break
                await asyncio.sleep(0.01)
        assert not state["server_errors"]
        return info, state, output


def stop_infrastructure():
    import nexent.monitor.monitoring as monitoring_module
    from nexent.core.concurrency.helpers import shutdown_fallback_thread_manager

    if monitoring_module._monitoring_buffer is not None:
        monitoring_module._monitoring_buffer.stop()
    asyncio.run(shutdown_fallback_thread_manager(timeout=5))
