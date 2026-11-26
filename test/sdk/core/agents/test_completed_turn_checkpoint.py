# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""WT-001/002: completed turn checkpoints contain real uncovered tail facts."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from smolagents.memory import ActionStep, FinalAnswerStep
from smolagents.monitoring import Timing
from test_jiuwen_adapter_lifecycle import adapter as adapter
from test_jiuwen_model_service import saved_profile as saved_profile
from test_run_local_completion import setup_core

from nexent.core.agents.context.maintenance import finish_agent_context
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent


async def accept(core, runtime, model, state, *, result="REAL_RESULT"):
    if core == "jiuwen":
        messages = [{"role": "system", "content": "POLICY"}, {"role": "user", "content": state.query}]
        if result == "LATE_RESULT":
            messages.extend(message for item in runtime._current_items for message in item.content.get("messages", []))
        from test_jiuwen_model_service import TOOLS

        native = await model.invoke(messages, tools=TOOLS)
        assert native.tool_calls[0].id == "new-call"
        runtime.completed_tool("add", result, result, provider_call_id="new-call")
        await asyncio.wrap_future(runtime._maintenance_execution.future)
    else:
        prepared = runtime.prepare_step(model=model, memory=state, current_run_start_idx=0)
        response = model(prepared.messages)
        response.nexent_context_accepted = True
        state.steps.append(ActionStep(step_number=len(state.steps), model_output=response.content,
            observations=result, timing=Timing(start_time=0)))
        runtime.complete_step(model=model, memory=state, current_run_start_idx=0, response=response)


def finish(core, runtime, model, state):
    if core == "jiuwen":
        return runtime.finish_run("FINAL_VISIBLE_OUTPUT")
    return runtime.finish_run(model=model, memory=state, current_run_start_idx=0,
                              final_output="FINAL_VISIBLE_OUTPUT")


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
async def test_ever_triggered_round_finishes_after_usage_drops(saved_profile, core):
    sender, runtime, model, state = setup_core(core, saved_profile, (70, 30))
    sender.first_tool_call = core == "jiuwen"
    await accept(core, runtime, model, state)
    sender.counts = (1, 1)
    sender.first_tool_call = core == "jiuwen"
    await accept(core, runtime, model, state, result="LATE_RESULT")
    assert sender.summary_count == 1
    if core == "smolagents":
        state.steps[1].observations += " LATE_UPDATED_RESULT"
    event = finish(core, runtime, model, state)
    assert event["coverage_scope"] == "current_completed_turn"
    assert "covered_through_message_id" not in event
    assert event["history_tail_message_id"] == 4
    assert event["previous_summary_unit_id"] == 10
    assert sender.summary_count == 2
    encoded = json.dumps(sender.bodies[-1])
    for fact in ("LOCAL_COMPACT_VIEW", "REAL_RESULT", "LATE_RESULT", "FINAL_VISIBLE_OUTPUT"):
        assert fact in encoded
    if core == "smolagents":
        assert "LATE_UPDATED_RESULT" in encoded
    assert "PRIVATE_THOUGHT" not in encoded
    assert "OLD_HISTORY_TASK" not in encoded
    assert finish(core, runtime, model, state) is None
    assert sender.summary_count == 2
    assert runtime.context_manager.consume_history_summary_event() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
@pytest.mark.parametrize("failure", ["cancelled", "empty", "error", "new_epoch"])
async def test_invalid_finalization_preserves_prior_checkpoint(saved_profile, core, failure, mocker):
    sender, runtime, model, state = setup_core(core, saved_profile, (70, 30))
    sender.first_tool_call = core == "jiuwen"
    await accept(core, runtime, model, state)
    manager = runtime.context_manager
    original = list((runtime.run_context if core == "jiuwen" else runtime._run_context).items)
    if failure == "cancelled":
        if core == "jiuwen":
            runtime.scope.cancel()
        else:
            model.stop_event = SimpleNamespace(is_set=lambda: True)
    elif failure == "new_epoch":
        def reset(*args, **kwargs):
            manager.prepare_items_context("", items=original)
            return SimpleNamespace(summary_text="LATE_OLD_RUN")
        mocker.patch.object(manager._llm, "generate_summary", side_effect=reset)
    else:
        mocker.patch.object(manager._llm, "generate_summary", **(
            {"return_value": SimpleNamespace(summary_text="  ")} if failure == "empty" else
            {"side_effect": ValueError("provider failed")}))
    assert finish(core, runtime, model, state) is None
    assert list((runtime.run_context if core == "jiuwen" else runtime._run_context).items) == original
    assert manager.consume_history_summary_event() is None


@pytest.mark.parametrize("status", ["completed", "cancelled", "error", "human", "subagent"])
def test_core_loop_proposes_only_after_successful_root_completion(status, mocker):
    from nexent.core.agents.contracts.identity import run_identity_scope

    events = []
    agent = SimpleNamespace(stop_event=SimpleNamespace(is_set=lambda: status == "cancelled"),
        context_runtime=SimpleNamespace(finish_run=mocker.Mock(return_value={"summary": "ok"}),
            finalize_evidence=mocker.Mock()), model=object(), memory=object(), _history_step_count=0,
        observer=SimpleNamespace(turn_complete=status == "human", add_message=lambda *args: events.append(args)),
        agent_name="root")

    def stream(**kwargs):
        yield FinalAnswerStep("FINAL")
        assert not agent.context_runtime.finish_run.called
        if status == "error":
            raise ValueError("run failed after final presentation")

    agent._run_stream = stream
    with run_identity_scope("subagent" if status == "subagent" else "root"):
        gen = CoreAgent._run_stream_with_context_evidence(agent, task="task", max_steps=1)
        if status == "error":
            with pytest.raises(ValueError):
                list(gen)
        else:
            list(gen)
    assert agent.context_runtime.finish_run.call_count == (status == "completed")
    assert len(events) == (status == "completed")


def test_no_valid_base_never_fabricates_coverage(mocker):
    from test_run_local_completion import old_items

    from nexent.core.agents.context import ContextManager

    manager = ContextManager()
    context = manager.prepare_items_context("", items=old_items())
    manager._agent_triggered = True
    generate = mocker.patch.object(manager._llm, "generate_summary")
    assert finish_agent_context(manager=manager, run_context=context, current_items=[],
        final_output="final", model=object(), cancelled=lambda: False) is None
    generate.assert_not_called()


@pytest.mark.parametrize("status", ["completed", "failed", "stopped", "human", "subagent", "late_cancel"])
def test_native_close_proposes_after_cleanup_only_for_success(adapter, mocker, status):
    from nexent.core.agents.contracts.identity import run_identity_scope

    events = []
    adapter.events.final_answer = "FINAL"
    adapter.events.waiting_for_input = status == "human"
    adapter._run_completed = status not in {"failed", "stopped"}
    if status == "stopped":
        adapter.run_info.stop_event.set()

    def close():
        adapter._closed = True
        events.append("cleanup")

    def finish(_output):
        events.append("checkpoint")
        if status == "late_cancel":
            adapter.run_info.stop_event.set()
        return {"coverage_scope": "current_completed_turn", "summary": {"markdown": "whole"}}

    mocker.patch.object(adapter, "_close_resources", side_effect=close)
    adapter.context_bridge = SimpleNamespace(finish_run=mocker.Mock(side_effect=finish))
    output = mocker.patch.object(adapter.events, "output")
    terminal = mocker.patch.object(adapter.events, "finish", return_value="done")
    with run_identity_scope("subagent" if status == "subagent" else "root"):
        adapter.close()
        adapter.close()
    assert events == (["cleanup", "checkpoint"] if status in {"completed", "late_cancel"} else ["cleanup"])
    assert output.call_count == (status == "completed")
    terminal.assert_called_once_with("stopped" if status in {"stopped", "late_cancel"} else
                                     "failed" if status == "failed" else "completed")


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
@pytest.mark.parametrize("history,counts,expected", [(False, (70, 30), True), (True, (1, 1), False)])
async def test_first_round_and_untriggered_estimates(saved_profile, core, history, counts, expected):
    sender, runtime, model, state = setup_core(core, saved_profile, counts, history=history)
    sender.first_tool_call = core == "jiuwen"
    await accept(core, runtime, model, state)
    assert sender.summary_count == 0
    event = finish(core, runtime, model, state)
    assert (event is not None) is expected
    if expected:
        assert event["history_tail_message_id"] is None
        assert event["previous_summary_unit_id"] is None
        assert "CURRENT_TASK" in json.dumps(sender.bodies[-1])
        assert "REAL_RESULT" in json.dumps(sender.bodies[-1])
        assert sender.summary_count == 1


def test_closed_generator_does_not_finalize_presented_but_incomplete_round(mocker):
    agent = SimpleNamespace(stop_event=SimpleNamespace(is_set=lambda: False),
        context_runtime=SimpleNamespace(finish_run=mocker.Mock(), finalize_evidence=mocker.Mock()),
        _run_stream=lambda **kwargs: iter([FinalAnswerStep("FINAL")]))
    stream = CoreAgent._run_stream_with_context_evidence(agent, task="task", max_steps=1)
    assert next(stream).output == "FINAL"
    stream.close()
    agent.context_runtime.finish_run.assert_not_called()
    agent.context_runtime.finalize_evidence.assert_called_once_with(status="cancelled")
