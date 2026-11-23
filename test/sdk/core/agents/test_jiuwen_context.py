# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared CM consumption and native tool association regression contracts."""

from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManagerConfig
from nexent.core.agents.context.history_compression import HistorySummaryInput
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.cores.jiuwen.context import JiuwenContextBridge, SummaryModel
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import MessageObserver


def make_bridge(mode="passthrough", items=(), sink=None):
    config = ContextManagerConfig(context_window_tokens=10000, effective_input_limit_tokens=10000,
        compaction_trigger_threshold_tokens=2000, compaction_target_tokens=1500,
        policy_layers={"agent": {"processing_mode": mode}}, history_summary_sink=sink)
    info = AgentRunInfo(query="CURRENT_TASK", model_config_list=[], observer=MessageObserver(), stop_event=Event(),
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[],
                                context_manager_config=config))
    scope = RunCancellationScope()
    model = Mock(scope=scope)
    model.profile.connection.timeout_seconds = 5
    bridge = JiuwenContextBridge(info, scope, Mock(), model, items)
    # This fixture isolates maintenance from the model encoder. Wire accounting
    # is covered with a real JiuwenServiceModel in test_context_message_format.
    bridge.context_manager._request_token_estimator = None
    return bridge, info


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
    original_model = bridge.summary_model.model
    bridge.summary_model = Mock(spec=["__call__", "model"], model=original_model, return_value=SimpleNamespace(content=markdown))
    bridge._assemble([{"role": "user", "content": info.query}], [])
    bridge.summary_model.assert_not_called()
    execute_pending_maintenance(bridge)
    assert bridge.summary_model.called and sink.call_count == 1
    assert sink.call_args.args[0].covered_through_message_id == 2
    assert bridge.last_evidence.processing_mode == "adaptive_compact"
    assert bridge.last_evidence.summary_persist_status == "succeeded"
    assert info.agent_config.context_manager_config.history_summary_sink is sink


def test_invalid_summary_does_not_persist_checkpoint():
    sink = Mock()
    bridge, info = make_bridge("adaptive_compact", [turn()], sink)
    original_model = bridge.summary_model.model
    bridge.summary_model = Mock(spec=["__call__", "model"], model=original_model,
        return_value=SimpleNamespace(content="Invalid summary"))
    bridge._assemble([{"role": "user", "content": info.query}], [])
    execute_pending_maintenance(bridge)
    sink.assert_not_called()
    assert bridge.last_evidence.new_summary_coverage is None


def test_historical_records_and_attachments_enter_summary_as_facts():
    rendered = ContextItemRenderer().render([turn()])
    source = HistorySummaryInput.from_items(None, [turn()]).render()
    assert rendered[1]["role"] == "user"
    from nexent.core.agents.context import ContextManager
    native = ContextManager(message_format="openai_chat_completions").build_context_messages([turn()])
    assert native[1]["role"] == "assistant"
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
@pytest.mark.parametrize("ending", ["deadline", "cancel"])
async def test_context_wait_reclaims_only_its_execution_on_deadline_or_cancellation(ending):
    import asyncio
    import time
    from concurrent.futures import Future

    bridge, info = make_bridge()
    pending = Future()
    execution = SimpleNamespace(execution_id="owned-context", future=pending)
    bridge.manager.submit.return_value = execution
    info.model_deadline = time.monotonic() - 1 if ending == "deadline" else None
    if ending == "deadline":
        with pytest.raises(TimeoutError):
            await bridge.prepare_messages([], [])
        assert bridge.scope.cancelled
    else:
        task = asyncio.create_task(bridge.prepare_messages([], []))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not bridge.scope.cancelled
    bridge.manager.cancel.assert_called_once()
    assert bridge.manager.cancel.call_args.args[0] == "owned-context"
    assert bridge.manager.cancel.call_args.kwargs["mark_stuck_on_timeout"] is False
    assert bridge.executions == [execution]


def test_context_close_cancels_pending_owners_and_retains_completed_results():
    from concurrent.futures import Future

    bridge, info = make_bridge()
    pending, completed = Future(), Future()
    completed.set_result("preserved")
    bridge.executions = [SimpleNamespace(execution_id="pending", future=pending),
                         SimpleNamespace(execution_id="done", future=completed)]
    bridge.close()
    bridge.manager.cancel.assert_called_once_with("pending", reason="Jiuwen context cleanup",
        wait_timeout=info.mcp_close_timeout_seconds, mark_stuck_on_timeout=True)
    assert completed.result() == "preserved"


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


def execute_pending_maintenance(bridge, *, calls=()):
    def execute(_lane, _spec, work):
        future = Future()
        try:
            future.set_result(work())
        except BaseException as error:
            future.set_exception(error)
        return SimpleNamespace(future=future)
    bridge.manager.submit.side_effect = execute
    bridge.accepted_response(SimpleNamespace(
        usage=SimpleNamespace(origin="provider", input_tokens=3000), content_parts=[{"type":"text","text":"answer"}],
        tool_calls=[]), SimpleNamespace(tool_calls=list(calls)))
    if not calls:
        bridge._maintenance_execution.future.result()


def test_maintenance_waits_for_matching_tool_results_and_ignores_nested_calls():
    bridge, info = make_bridge("adaptive_compact", [turn()])
    bridge._assemble([{"role":"user", "content":info.query}], [])
    call = SimpleNamespace(name="native_tool", id="provider-call", arguments="{}")
    execute_pending_maintenance(bridge, calls=[call])
    assert bridge._maintenance_execution is None
    bridge.completed_tool("nested_business_tool", "nested", "nested-local")
    assert bridge._maintenance_execution is None
    bridge.scope.cancel()
    bridge.completed_tool("native_tool", "finished", "local")
    assert bridge._maintenance_execution is None


def test_closed_tool_step_starts_maintenance_once_and_keeps_original_source():
    bridge, info = make_bridge("passthrough", [turn()])
    bridge._assemble([{"role":"user", "content":info.query}], [])
    execute_pending_maintenance(bridge, calls=[SimpleNamespace(name="native_tool", id="provider-call", arguments="{}")])
    bridge.completed_tool("native_tool", "actual result", "local")
    bridge._maintenance_execution.future.result()
    assert bridge.usage_baseline.actual_input_tokens == 3000
    assert bridge.manager.submit.call_count == 1
    bridge.completed_tool("native_tool", "duplicate", "local")
    assert bridge.manager.submit.call_count == 1
    assert "actual result" in str(bridge._current_items)
    assert len(bridge.run_context.items) == 1


def test_text_execution_maintenance_preserves_converted_native_call_pair():
    """FIX-JW-01: post-response accounting uses the call actually dispatched."""
    bridge, info = make_bridge()
    bridge._assemble([{"role": "user", "content": info.query}], [])
    call = SimpleNamespace(id="text-execution", name="nexent_execute_block", arguments='{"code":"print(7)"}')
    bridge.accepted_response(SimpleNamespace(
        usage=SimpleNamespace(origin="provider", input_tokens=100),
        content_parts=[{"type": "text", "text": "<code>print(7)</code>"}], tool_calls=[]),
        SimpleNamespace(tool_calls=[call]))
    payload = bridge._current_items[-1].content["messages"][0]
    assert payload["tool_calls"] == [{"id": call.id, "type": "function", "function": {
        "name": call.name, "arguments": call.arguments}}]
    assert bridge._maintenance_execution is None


def test_same_name_reverse_completion_matches_provider_call_id():
    """FIX-JW-02: a later same-name call may finish before the first."""
    bridge, info = make_bridge()
    bridge._assemble([{"role": "user", "content": info.query}], [])
    calls = [SimpleNamespace(id="call-a", name="lookup", arguments='{"key":"A"}'),
             SimpleNamespace(id="call-b", name="lookup", arguments='{"key":"B"}')]
    execute_pending_maintenance(bridge, calls=calls)
    bridge.completed_tool("lookup", "result-B", "local-b", provider_call_id="call-b")
    payload = bridge._current_items[-1].content["messages"][0]
    assert payload["tool_call_id"] == "call-b"
    assert payload["content"] == "result-B"
    assert [call.id for call in bridge._pending_calls] == ["call-a"]
    assert bridge._maintenance_execution is None
    bridge.completed_tool("lookup", "result-A", "local-a", provider_call_id="call-a")
    bridge._maintenance_execution.future.result()
    assert bridge.manager.submit.call_count == 1


@pytest.mark.parametrize("provider_id", [None, "foreign-call"])
def test_ambiguous_or_foreign_completion_cannot_consume_pending_call(provider_id):
    """FIX-JW-02: absent correlation never guesses which result completed."""
    bridge, info = make_bridge()
    bridge._assemble([{"role": "user", "content": info.query}], [])
    calls = [SimpleNamespace(id="call-a", name="lookup", arguments="{}"),
             SimpleNamespace(id="call-b", name="lookup", arguments="{}")]
    execute_pending_maintenance(bridge, calls=calls)
    bridge.completed_tool("lookup", "unattributed result", "unknown-local", provider_call_id=provider_id)
    assert bridge._pending_calls == calls
    assert bridge._completed_tool_ids == set()
    assert bridge._maintenance_execution is None


def test_capacity_rejection_reports_safe_local_estimate_and_no_provider_usage(caplog):
    bridge, info = make_bridge()
    bridge.context_manager.config.effective_input_limit_tokens = 1000
    info.query = "PRIVATE_PROMPT " + "x" * 3000
    with pytest.raises(ValueError, match="combined context window"):
        bridge._assemble([{"role": "user", "content": info.query}], [])
    records = [record.getMessage() for record in caplog.records
               if "event=context_input_rejected" in record.getMessage()]
    assert len(records) == 1
    assert "combined_window=1000" in records[0]
    assert "usage_source=estimated" in records[0]
    assert "provider_input=None" in records[0]
    assert "PRIVATE_PROMPT" not in caplog.text
