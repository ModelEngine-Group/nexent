import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.consts.model import AgentRequest
from management.services.agent import run as agent_service


@pytest.mark.asyncio
async def test_memory_enabled_stream_does_not_emit_presearch_events(monkeypatch):
    request = AgentRequest(
        agent_id=7,
        conversation_id=777,
        query="question",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    channel = AsyncMock()
    monkeypatch.setattr(
        agent_service.streaming_channel_manager,
        "get_or_create_channel",
        AsyncMock(return_value=channel),
    )
    monkeypatch.setattr(
        agent_service,
        "build_memory_context",
        MagicMock(
            return_value=MagicMock(
                user_config=MagicMock(memory_switch=True)
            )
        ),
    )
    prepare = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(agent_service, "prepare_agent_run", prepare)

    async def chunks(**_kwargs):
        yield "data: body\n\n"

    monkeypatch.setattr(agent_service, "_stream_agent_chunks", chunks)

    output = [
        chunk
        async for chunk in agent_service.generate_stream(
            request,
            user_id="user-1",
            tenant_id="tenant-1",
            enable_memory=True,
        )
    ]

    assert output == ["data: body\n\n"]
    assert not any("memory_search" in chunk for chunk in output)
    assert not any(
        "memory_search" in str(call.args)
        for call in channel.publish.await_args_list
    )
    prepare.assert_awaited_once_with(
        agent_request=request,
        user_id="user-1",
        tenant_id="tenant-1",
        language=agent_service.LANGUAGE["ZH"],
        allow_memory_search=True,
    )


@pytest.mark.asyncio
async def test_fixed_search_is_streamed_and_persisted_as_structured_tool(monkeypatch):
    request = AgentRequest(
        agent_id=7,
        conversation_id=777,
        query="question",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    pre_run_events = [
        {
            "type": "tool",
            "content": "",
            "tool_name": "search_memory",
            "tool_arguments": {"query": "question", "top_k": 5},
        },
        {
            "type": "execution_logs",
            "content": "No relevant memories found.",
        },
    ]
    run_info = MagicMock()
    run_info.agent_config.pre_run_tool_events = pre_run_events
    run_info.stop_event.is_set.return_value = False

    async def fake_agent_run(_run_info):
        yield json.dumps({"type": "final_answer", "content": "Done"})

    monkeypatch.setattr(agent_service, "agent_run", fake_agent_run)
    monkeypatch.setattr(agent_service, "save_message", lambda *args, **kwargs: 42)
    monkeypatch.setattr(
        agent_service.agent_run_manager,
        "unregister_agent_run",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        agent_service,
        "generate_conversation_title_service",
        AsyncMock(),
    )
    persisted_batches = []
    monkeypatch.setattr(
        agent_service,
        "persist_assistant_run_batch",
        lambda **kwargs: persisted_batches.append(kwargs),
    )
    monkeypatch.setattr(
        agent_service.streaming_channel_manager,
        "complete_channel",
        AsyncMock(),
    )
    monkeypatch.setattr(agent_service, "_cleanup_channel_later", AsyncMock())
    channel = AsyncMock()

    chunks = [
        chunk
        async for chunk in agent_service._stream_agent_chunks(
            request,
            "user-1",
            "tenant-1",
            run_info,
            MagicMock(),
            channel=channel,
        )
    ]

    streamed_tool = json.loads(chunks[0].removeprefix("data: ").strip())
    assert streamed_tool == {
        **pre_run_events[0],
        "unit_index": 0,
    }

    assert len(persisted_batches) == 1
    saved_units = persisted_batches[0]["message_units"]
    tool_unit = next(unit for unit in saved_units if unit["unit_type"] == "tool")
    persisted_tool = json.loads(tool_unit["unit_content"])
    assert persisted_tool == {
        "content": "",
        "tool_name": "search_memory",
        "tool_arguments": {"query": "question", "top_k": 5},
    }
