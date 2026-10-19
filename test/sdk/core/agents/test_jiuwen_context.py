"""Shared CM consumption and native tool association regression contracts."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo
from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManagerConfig
from nexent.core.agents.context.history_compression import HistorySummaryInput
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.core_adapters.jiuwen_context import JiuwenContextBridge, SummaryModel
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import MessageObserver


def make_bridge(mode="passthrough", items=(), sink=None):
    config = ContextManagerConfig(effective_input_limit_tokens=1000,
        compaction_trigger_threshold_tokens=100, compaction_target_tokens=80,
        policy_layers={"agent": {"processing_mode": mode}}, history_summary_sink=sink)
    info = AgentRunInfo(query="CURRENT_TASK", model_config_list=[], observer=MessageObserver(), stop_event=Event(),
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[],
                                context_manager_config=config))
    scope = RunCancellationScope()
    model = Mock(scope=scope)
    model.profile.connection.timeout_seconds = 5
    return JiuwenContextBridge(info, scope, Mock(), model, items), info


def turn():
    return ContextItem.from_input(ContextItemInput(id="turn:1:2", type="conversation_turn", content={
        "user_message": "Historical task " * 100, "assistant_final_answer": "Completed answer " * 100,
        "user_message_id": 1, "assistant_message_id": 2,
        "attachments": [{"name": "file.txt", "url": "s3://files/old.txt", "ignored_secret": "HIDDEN"}],
        "execution_records": [{"record_type": "error", "content": "Saved error", "tool_call_id": "old-call"}],
    }))


def test_passthrough_uses_real_cm_and_keeps_current_call_ids_without_compaction(mocker):
    bridge, info = make_bridge(items=[turn()])
    bridge.summary_model = Mock(side_effect=AssertionError("CM off must not summarize"))
    forbidden = mocker.patch("smolagents.memory.AgentMemory", side_effect=AssertionError("Synthetic memory"))
    messages = [{"role": "system", "content": "Policy"}, {"role": "user", "content": info.query},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "active-call", "type": "function",
                    "function": {"name": "allowed", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "active-call", "content": "Real observation"}]
    result = bridge._assemble(messages, [])
    assert str(result).count("CURRENT_TASK") == 1
    assert result[-1]["tool_call_id"] == "active-call"
    assert result[-2]["tool_calls"][0]["id"] == "active-call"
    assert "old-call" in str(result) and "Saved error" in str(result) and "HIDDEN" not in str(result)
    assert "s3://files/old.txt" in str(result)
    assert bridge.last_evidence.processing_mode == "passthrough"
    assert not bridge.last_evidence.compression_attempted
    forbidden.assert_not_called()


def test_saved_adaptive_mode_calls_shared_summary_and_persists_accepted_candidate():
    sink = Mock()
    bridge, info = make_bridge("adaptive_compact", [turn()], sink)
    headings = bridge.context_manager.config.summary_json_schema
    markdown = "# Compact Result of History\n" + "\n".join(
        "## " + key.replace("_", " ").title() + "\nPreserved fact" for key in headings)
    bridge.summary_model = Mock(spec=["__call__"], return_value=SimpleNamespace(content=markdown))
    bridge._assemble([{"role": "user", "content": info.query}], [])
    assert bridge.summary_model.called and sink.call_count == 1
    assert sink.call_args.args[0].covered_through_message_id == 2
    assert bridge.last_evidence.processing_mode == "adaptive_compact"
    assert bridge.last_evidence.summary_persist_status == "succeeded"
    assert info.agent_config.context_manager_config.history_summary_sink is sink


def test_invalid_summary_does_not_persist_checkpoint():
    sink = Mock()
    bridge, info = make_bridge("adaptive_compact", [turn()], sink)
    bridge.summary_model = Mock(spec=["__call__"], return_value=SimpleNamespace(content="Invalid summary"))
    bridge._assemble([{"role": "user", "content": info.query}], [])
    sink.assert_not_called()
    assert bridge.last_evidence.new_summary_coverage is None


def test_historical_records_and_attachments_enter_summary_as_facts():
    rendered = ContextItemRenderer().render([turn()])
    source = HistorySummaryInput.from_items(None, [turn()]).render()
    assert rendered[1]["role"] == "assistant"
    for text in (str(rendered), source):
        assert "s3://files/old.txt" in text and "old-call" in text and "Saved error" in text
        assert "read_only" in text and "HIDDEN" not in text


def test_cancelled_context_does_not_assemble_or_call_model():
    bridge, info = make_bridge()
    bridge.scope.cancel()
    with pytest.raises(RunTerminated):
        bridge._assemble([{"role": "user", "content": info.query}], [])
    with pytest.raises(RunTerminated):
        SummaryModel(Mock(scope=bridge.scope))([])


@pytest.mark.asyncio
async def test_context_queue_deadline_cancels_before_work_can_start():
    from concurrent.futures import Future

    bridge, info = make_bridge()
    bridge.context_timeout = 0.01
    future = Future()
    bridge.manager.submit.return_value = SimpleNamespace(future=future, execution_id="queued-context")
    with pytest.raises(TimeoutError):
        await bridge.prepare_messages([{"role": "user", "content": info.query}], [])
    assert future.cancelled()
    assert bridge.scope.cancelled
    assert bridge.last_evidence is None
    bridge.manager.cancel.assert_called_once_with(
        "queued-context", reason="Jiuwen context deadline exceeded", wait_timeout=0, mark_stuck_on_timeout=False)


@pytest.mark.asyncio
async def test_cancelled_context_is_rejected_before_worker_admission():
    bridge, info = make_bridge()
    bridge.scope.cancel()
    with pytest.raises(RunTerminated):
        await bridge.prepare_messages([{"role": "user", "content": info.query}], [])
    bridge.manager.submit.assert_not_called()
