# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native function registration uses the existing bounded execution reader."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.concurrency import LanePolicy, ThreadManager
from test_jiuwen_adapter_wiring import adapter as _adapter

adapter = _adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("tracing", [True, False])
@pytest.mark.parametrize("source_kind", ["execution_result", "tool_result", "user_message"])
async def test_b010_native_reader_uses_real_localfunction_owner_and_middle_page(
    adapter, mocker, tracing, source_kind
):
    from openjiuwen.harness import factory

    native = adapter.native_agent
    captured = mocker.patch.object(factory, "create_deep_agent", return_value=native)
    resources = Mock()
    resources._prepare_file_workspace.return_value = "Latest task"
    mocker.patch(
        "nexent.core.agents.cores.jiuwen.adapter.AgentResources", return_value=resources
    )
    mocker.patch.object(adapter, "_bind_skill_sandbox")
    mocker.patch.object(adapter, "_skill_rails", return_value=[])
    mocker.patch.object(adapter, "_bind_parallel_tool")
    mocker.patch.object(adapter, "_bind_text_executor")
    mocker.patch.object(adapter, "_create_model", return_value=SimpleNamespace())
    bridge = mocker.patch("nexent.core.agents.cores.jiuwen.context.JiuwenContextBridge")
    text = "<STDOUT>" + "prefix" * 1000 + "真实中段" + "tail" * 1000 + "</STDOUT>"
    source = {"message_id": 42, "unit_index": 5, "record_type": source_kind,
              "content": json.dumps({"content": text})}
    reference = "message:42/unit-index:5"
    if source_kind == "user_message":
        source.update(unit_index=None, content=text)
        reference = "message:42/user-message"
    elif source_kind == "tool_result":
        source.update(tool_call_id="local-source", content=json.dumps({
            "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen", "type": "tool_result",
            "local_call_id": "local-source", "tool_call_id": "local-source", "provider_call_id": "provider-source",
            "turn_id": "source-turn", "invocation_id": None, "parent_call_id": None, "result": text, "is_error": False}))
    adapter.context_items = [ContextItem.from_input(ContextItemInput(id="checkpoint", type="history_summary",
        content={"summary": "accepted facts", "covered_through_message_id": 42, "execution_sources": [source]}))]
    mocker.patch.object(adapter, "_compile_context", return_value="instructions")
    monitoring = mocker.patch(
        "nexent.core.agents.cores.jiuwen.adapter.get_monitoring_manager", create=True
    )
    monitoring.return_value.is_enabled = tracing
    threads = ThreadManager(
        "checkpoint-reader-test",
        {
            "model-tool-io": LanePolicy(
                name="model-tool-io", max_workers=1, max_queue_size=0
            )
        },
    )
    threads.start()
    adapter.run_info.thread_manager = threads
    try:
        adapter.prepare()
        tools = captured.call_args.kwargs["tools"]
        reader = next(
            tool for tool in tools if tool.card.name == "read_execution_output"
        )
        from openjiuwen.core.foundation.tool import LocalFunction

        assert isinstance(reader, LocalFunction)
        assert (
            resources.agent.tools["read_execution_output"]
            is adapter.business_tools["read_execution_output"]
        )
        result = await reader.invoke(
            {
                "output_ref": reference,
                "offset": text.index("真实中段"),
                "max_chars": 4,
            }
        )
        assert json.loads(result)["text"] == "真实中段"
        with pytest.raises(PermissionError):
            await reader.invoke({"output_ref": "message:999/unit-index:0"})
        with pytest.raises(ValueError):
            await reader.invoke({"output_ref": "invalid"})
        with pytest.raises(PermissionError):
            adapter.execution_history.read("foreign-owner", reference)
        assert adapter._active_resource.get() is None
        assert bridge.return_value.completed_tool.called
    finally:
        assert not (await threads.shutdown(timeout=3)).stuck_execution_ids
