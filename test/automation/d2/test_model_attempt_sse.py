"""Formal D2 SSE contract for model-attempt streams."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.agent import run as agent_run_service


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["transport", "semantic"])
async def test_cmsr_d2_001_success_delta_is_published_before_completion(monkeypatch, failure_kind):
    release_provider = asyncio.Event()
    persisted_batches = []
    failed_content = "failed text" if failure_kind == "transport" else "<code></code>"

    async def controlled_agent_run(*_args, **_kwargs):
        events = [
            {"type": "step_count", "content": "**Step 1**"},
            {"type": "model_attempt_control", "content": "", "phase": "begin", "attempt_id": "failed"},
            {"type": "model_output_thinking", "content": failed_content, "attempt_id": "failed"},
            {"type": "model_attempt_control", "content": "", "phase": "rollback", "attempt_id": "failed"},
            {"type": "model_attempt_control", "content": "", "phase": "begin", "attempt_id": "success"},
            {"type": "model_output_thinking", "content": "<code>print", "attempt_id": "success"},
        ]
        for event in events:
            yield json.dumps(event)
        await release_provider.wait()
        yield json.dumps({"type": "model_output_thinking", "content": "(1)</code>", "attempt_id": "success"})
        yield json.dumps({"type": "model_attempt_control", "content": "", "phase": "commit", "attempt_id": "success"})
        yield json.dumps({"type": "parse", "content": "print(1)"})

    monkeypatch.setattr(agent_run_service, "agent_run", controlled_agent_run)
    monkeypatch.setattr(agent_run_service, "save_message", MagicMock(return_value=4242))
    monkeypatch.setattr(
        agent_run_service,
        "persist_assistant_run_batch",
        lambda **kwargs: persisted_batches.append(kwargs),
    )
    monkeypatch.setattr(agent_run_service, "_unregister_agent_run_after_execution", MagicMock())
    monkeypatch.setattr(agent_run_service.streaming_channel_manager, "complete_channel", AsyncMock())
    monkeypatch.setattr(agent_run_service, "_cleanup_channel_later", AsyncMock())

    async def run_managed(_lane, _spec, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def wait_for_cancel(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent_run_service.runtime_thread_manager, "run", run_managed)
    monkeypatch.setattr(agent_run_service, "_poll_runtime_cancel_signal", wait_for_cancel)
    request = SimpleNamespace(conversation_id=999, history=[], is_debug=False)
    info = SimpleNamespace(
        agent_config=SimpleNamespace(pre_run_tool_events=()),
        cancellation_scope=None,
        stop_event=asyncio.Event(),
        human_interaction=None,
        attempt_outcome="completed",
        thread_future=None,
    )
    channel = SimpleNamespace(publish=AsyncMock())
    stream = agent_run_service._stream_agent_chunks(
        request, "test-user", "test-tenant", info, MagicMock(), channel=channel
    )
    published = [await asyncio.wait_for(anext(stream), timeout=2) for _ in range(6)]
    assert '"type": "step_count"' in published[0]
    assert '"type": "model_attempt_control"' in published[1]
    assert len([chunk for chunk in published if '"type": "step_count"' in chunk]) == 1
    assert not release_provider.is_set()
    assert "<code>print" in published[-1]
    assert '"attempt_id": "success"' in published[-1]
    assert all("(1)</code>" not in chunk for chunk in published)

    release_provider.set()
    published.extend([chunk async for chunk in stream])
    assert len([chunk for chunk in published if '"type": "step_count"' in chunk]) == 1
    assert len([chunk for chunk in published if '"type": "parse"' in chunk]) == 1
    assert len(persisted_batches) == 1
    persisted = persisted_batches[0]["message_units"]
    contents = [unit["unit_content"] for unit in persisted]
    assert failed_content not in "".join(contents)
    assert any("<code>print(1)</code>" in content for content in contents)
