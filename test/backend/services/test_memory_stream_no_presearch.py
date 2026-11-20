# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stream only authorized prepared Memory events and persist their tool metadata."""

import json
from types import SimpleNamespace

import pytest

from contracts.agentos import AgentResource, PreparedMemorySearch, ToolBinding
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_memory, prepared_run
from .test_agent_run_final_answers import stream_capture


@pytest.fixture
def run_events(mocker):
    async def model(_info, **_kwargs):
        yield '{"type":"final_answer","content":"Done"}'

    mocker.patch.object(prepared_run, "agent_run", side_effect=model)

    async def collect(search=None):
        resource = AgentResource(
            agent_id=7, version_no=1, name="memory", description="", prompt_templates={},
            memory_search=search, tools=[ToolBinding(tool_id="store_memory", version="1")],
        )
        tools, events = prepared_memory.materialize_memory(resource, ServicePrincipal("user", "tenant"), 42)
        assert set(tools) == {"store_memory"}
        info = SimpleNamespace(agent_config=SimpleNamespace(pre_run_tool_events=events))
        return [json.loads(chunk) async for chunk in prepared_run._snapshot_chunks(info)]

    return collect


@pytest.mark.asyncio
async def test_enabled_memory_without_a_search_binding_emits_no_presearch_events(run_events, stream_capture):
    source = await run_events()

    published, batch = await stream_capture(source)

    assert published == [{"type": "final_answer", "content": "Done"}]
    assert [unit["type"] for unit in batch["message_units"]] == ["final_answer"]


@pytest.mark.asyncio
async def test_fixed_search_is_streamed_and_saved_as_a_structured_tool(run_events, stream_capture):
    search = PreparedMemorySearch(query="question", result="No relevant memories found.")
    source = await run_events(search)

    published, batch = await stream_capture(source)

    assert published[:-1] == search.observer_events()
    assert [unit["type"] for unit in batch["message_units"]] == ["tool", "execution_logs", "final_answer"]
    tool, logs, _ = batch["message_units"]
    assert tool["unit_index"] == 0
    assert json.loads(tool["unit_content"]) == {
        "content": "", "tool_name": "search_memory",
        "tool_arguments": {"query": "question", "top_k": 5},
    }
    assert logs["unit_content"] == "No relevant memories found."
