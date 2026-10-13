"""FAF-D2-001 real stream-generator contract with SDK events."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from management.services.agent import run as agent_run_service
from test.automation.d1.test_final_answer_display import MessageObserver, ProcessType

@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "Thought. ", "<think>Deep.</think>"])
@pytest.mark.parametrize("invocation", [None, "child"])
async def test_faf_d2_001(monkeypatch, prefix, invocation):
    observer = MessageObserver()
    if invocation:
        observer.add_subagent_start(2, "Child", invocation_id=invocation)
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("a", 1)
    for fragment in [prefix + "<final_ans", "wer>Final ", "report</final_answer>"]:
        observer.add_model_new_token(fragment)
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("a", 1)
    observer.complete_final_answer("agent", "Final report")
    events = [json.loads(raw) for raw in observer.get_cached_message()]
    payloads, batches = await _capture_events(monkeypatch, events)
    assert len(batches) == 1
    units = batches[0]["message_units"]
    assert [unit["content"] for unit in units if unit["type"] == "final_answer"] == ["Final report"]
    assert len([unit for unit in units if unit["type"] == "step_count"]) == bool(prefix)
    assert "".join(item["content"] for item in payloads if item.get("type") == "final_answer") == "Final report"
    assert all(item.get("invocation_id") == invocation for item in payloads if item.get("type") == "final_answer")
    assert not any("Final report" in item["content"] for item in units if item["type"].startswith("model_output"))


@pytest.mark.asyncio
async def test_faf_d2_001_legacy_body_is_moved_without_retransmission(monkeypatch):
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.add_model_new_token("Legacy answer")
    observer.flush_remaining_tokens()
    observer.mark_direct_final_answer()
    observer.complete_final_answer("agent", "Legacy answer")
    payloads, batches = await _capture_events(monkeypatch, [json.loads(raw) for raw in observer.get_cached_message()])
    assert sum(event.get("content") == "Legacy answer" for event in payloads) == 1
    units = batches[0]["message_units"]
    assert [(item["type"], item["content"]) for item in units] == [("final_answer", "Legacy answer")]
    assert batches[0]["message_content"] == "Legacy answer"

async def _capture_events(monkeypatch, events):
    async def source(*_args, **_kwargs):
        for event in events:
            yield json.dumps(event)

    batches = []
    monkeypatch.setattr(agent_run_service, "agent_run", source)
    monkeypatch.setattr(agent_run_service, "save_message", MagicMock(return_value=42))
    monkeypatch.setattr(
        agent_run_service,
        "persist_assistant_run_batch",
        lambda **kwargs: batches.append(kwargs),
    )
    monkeypatch.setattr(
        agent_run_service, "_unregister_agent_run_after_execution", MagicMock()
    )
    monkeypatch.setattr(
        agent_run_service.streaming_channel_manager, "complete_channel", AsyncMock()
    )
    monkeypatch.setattr(agent_run_service, "_cleanup_channel_later", AsyncMock())

    async def managed(_lane, _spec, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def cancel(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent_run_service.runtime_thread_manager, "run", managed)
    monkeypatch.setattr(agent_run_service, "_poll_runtime_cancel_signal", cancel)
    info = SimpleNamespace(
        agent_config=SimpleNamespace(pre_run_tool_events=()),
        cancellation_scope=None,
        stop_event=asyncio.Event(),
        human_interaction=None,
        attempt_outcome="completed",
        thread_future=None,
    )
    channel = SimpleNamespace(publish=AsyncMock())
    published = [
        raw
        async for raw in agent_run_service._stream_agent_chunks(
            SimpleNamespace(conversation_id=999, history=[], is_debug=False),
            "test-user",
            "test-tenant",
            info,
            MagicMock(),
            channel=channel,
        )
    ]
    payloads = [
        json.loads(raw.removeprefix("data: ").strip())
        for raw in published
        if raw.startswith("data: {")
    ]
    return payloads, batches
