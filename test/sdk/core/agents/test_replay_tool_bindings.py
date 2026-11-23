# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

def test_smol_mcp_records_effective_fields_beneath_configured_and_identity_parameters():
    from nexent.core.agents.contracts.config import ToolConfig
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, argument_digest
    from nexent.core.agents.resources.tools import ToolResources
    calls = []
    def forward(**values):
        calls.append(values)
        return "ok"
    config = ToolConfig(class_name="fetch", name="fetch", source="mcp", params={"limit": 7})
    recorder = ReplayToolRecorder(SimpleNamespace(tools=[config]), {"fetch":["limit"]})
    resources = ToolResources()
    resources.observer = SimpleNamespace(replay_tool_recorder=recorder)
    resources.user_context = {"tenant_id":"isolated"}
    template = SimpleNamespace(name="fetch", inputs={"tenant_id":{}, "limit":{}}, forward=forward)
    resources.mcp_tool_collection = SimpleNamespace(tools=[template])
    instance = resources.create_tool(config)
    assert instance.forward(limit=3) == "ok" and calls == [{"limit":7, "tenant_id":"isolated"}]
    assert recorder.receipt()["calls"][0]["arguments"] == {"limit":argument_digest(7)}
    assert template.forward is forward


@pytest.mark.asyncio
async def test_native_mcp_records_arguments_sent_to_transport_worker():
    from nexent.core.agents.cores.jiuwen.mcp import _ManagedNativeClient
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, argument_digest
    sent = []
    def submit(lane, task, fn, *args):
        future = Future()
        future.set_result(fn(*args))
        return SimpleNamespace(future=future)
    owner = SimpleNamespace(manager=SimpleNamespace(submit=submit), user_context={"tenant_id":"isolated"},
                            cancellation_scope=SimpleNamespace(cancelled=False), request_close=lambda: None,
                            tool_timeout_seconds=1, _call_tool=lambda client, name, args: sent.append((name,args)) or "done")
    proxy = _ManagedNativeClient(owner, object(), "remote-fetch", ["tenant_id"], {"limit":7})
    recorder = ReplayToolRecorder(object(), {"fetch":["limit"]})
    proxy.send = recorder.wrap_forward("fetch", proxy.send, [], mapping_input=True)
    assert await proxy.call_tool("fetch", {"limit":3}) == "done"
    assert sent == [("remote-fetch", {"limit":7, "tenant_id":"isolated"})]
    call, = recorder.receipt()["calls"]
    assert call["outcome"] == "returned" and call["arguments"] == {"limit":argument_digest(7)}
