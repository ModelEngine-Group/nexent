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
    assert recorder.receipt()["calls"][0]["requested_arguments"] == {"limit":argument_digest(3)}
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

@pytest.mark.parametrize("raw,expected", [("2024/02/29","2024-02-29"),("20241205","2024-12-05"),
                                         ("2024-12-05","2024-12-05")])
def test_mapping_converts_one_date_and_preserves_approved_inputs(raw, expected):
    from nexent.core.agents.resources.argument_formats import bind_argument_formats, format_rule
    rule = format_rule({"type":"string","format":"date"})
    tool = SimpleNamespace(inputs={"day":{}, "region":{}}, _nexent_mcp_formats={"day":rule},
                           forward=lambda **kw: kw)
    mapped = bind_argument_formats(tool, {"day":rule})
    assert mapped.forward(raw, region="west") == {"day":expected, "region":"west"}
    assert mapped.forward(region="west") == {"region":"west"}
    with pytest.raises(TypeError):
        mapped.forward(raw, day=raw)


@pytest.mark.parametrize("raw", ["03/04/2026", "2023/02/29", "2026/04-30", "2026/01/01,2026/01/02", None, []])
def test_mapping_does_not_guess_ambiguous_missing_or_invalid_values(raw):
    from nexent.core.agents.resources.argument_formats import formatted_value
    with pytest.raises(ValueError):
        formatted_value({"kind":"iso_date"}, raw)


def test_enum_requires_an_unambiguous_live_contract():
    from nexent.core.agents.resources.argument_formats import bind_argument_formats, format_rule, formatted_value
    rule = format_rule({"type":"string","enum":["OPEN","CLOSED"]})
    assert formatted_value(rule," open ") == "OPEN"
    with pytest.raises(ValueError):
        formatted_value(rule,"pending")
    with pytest.raises(ValueError):
        format_rule({"type":"string","enum":["OPEN"," open"]})
    with pytest.raises(ValueError):
        bind_argument_formats(SimpleNamespace(inputs={"status":{}}, _nexent_mcp_formats={}), {"status":rule})
    with pytest.raises(ValueError):
        bind_argument_formats(SimpleNamespace(inputs={"user_id":{}}), {"user_id":rule})


@pytest.mark.asyncio
async def test_native_mcp_maps_before_validation_and_records_after_binding():
    from openjiuwen.core.foundation.tool.mcp.base import McpToolCard
    from nexent.core.agents.cores.jiuwen.mcp import _ManagedNativeClient, _ObservedMCPTool
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, argument_digest
    sent = []
    def submit(_lane, _spec, fn, args):
        future = Future()
        future.set_result(fn(args))
        return SimpleNamespace(future=future)
    owner = SimpleNamespace(manager=SimpleNamespace(submit=submit),user_context={"tenant_id":"test"},
                            cancellation_scope=SimpleNamespace(cancelled=False), request_close=lambda:None,
                            tool_timeout_seconds=1, _call_tool=lambda client, name, args:sent.append(args) or "ok")
    proxy = _ManagedNativeClient(owner, object(), "lookup", ["tenant_id"])
    recorder = ReplayToolRecorder(object(), {"lookup":["day"]})
    proxy.send = recorder.wrap_forward("lookup",proxy.send,[],mapping_input=True)
    props = {"day":{"type":"string","format":"date"}}
    card = McpToolCard(name="lookup",server_name="calendar",description="test",
                       input_params={"type":"object","properties":props,"required":["day"]})
    tool = _ObservedMCPTool(proxy,card,lambda *_:None,None,recorder,{"day":{"kind":"iso_date"}})
    await tool.invoke({"day":"2028/02/29"})
    record, = recorder.receipt()["calls"]
    assert sent == [{"day":"2028-02-29","tenant_id":"test"}]
    assert record["requested_arguments"] == {"day":argument_digest("2028/02/29")}
    assert record["arguments"] == {"day":argument_digest("2028-02-29")}
