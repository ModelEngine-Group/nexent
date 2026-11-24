# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore closed actions without replaying executor-expanded call metadata."""

import json
from copy import deepcopy

import pytest
from test_jiuwen_model_service import saved_profile as saved_profile

from nexent.core.agents.context.action_history import render_persisted_actions
from nexent.core.agents.context.execution_history import ExecutionHistory


def records():
    call = {"id": "call-1", "name": "python_interpreter", "arguments": "write_file(body=computed)"}
    payload = {
        "content": "<STDOUT>actual stdout</STDOUT>",
        "model_action": {"schema_version": 1, "agent_core": "smolagents",
                         "dispatch_state": "dispatched", "step_number": 1, "tool_calls": [call]},
        "covered_unit_indices": [3, 4],
    }
    return [
        {"record_type": "tool", "unit_index": 3, "content": json.dumps({
            "tool_name": "write_file", "tool_arguments": {"body": "EXPANDED" * 12000}})},
        {"record_type": "execution_logs", "unit_index": 4, "content": "actual stdout"},
        {"record_type": "execution_result", "unit_index": 5, "content": json.dumps(payload)},
    ]


def history_turn(message=42, *, execution_records=None, question="prior question", answer="actual answer"):
    """One authorized completed turn, shared by history and owner-boundary regressions."""
    from nexent.core.agents.context import ContextItemInput

    return ContextItemInput(id=f"turn:{message}", type="conversation_turn", content={
        "user_message_id": message - 1, "assistant_message_id": message,
        "user_message": question, "assistant_final_answer": answer,
        "execution_records": records() if execution_records is None else execution_records,
    })


def test_fix01_canonical_action_preserves_source_results_and_original_records():
    source = records()
    before = deepcopy(source)
    text = render_persisted_actions(source, assistant_message_id=42)
    assert "write_file(body=computed)" in text
    assert "actual stdout" in text
    assert "EXPANDED" not in text
    assert "message:42/unit-index:5" in text
    assert 'read_only="true"' in text
    assert source == before


@pytest.mark.parametrize("indices", [[3, 3], [99], [5], [-1], [True]])
def test_fix01_invalid_coverage_preserves_raw_history(indices):
    source = records()
    payload = json.loads(source[-1]["content"])
    payload["covered_unit_indices"] = indices
    source[-1]["content"] = json.dumps(payload)
    text = render_persisted_actions(source, assistant_message_id=42)
    assert "EXPANDED" in text
    assert "<completed_action>" not in text
    assert "<tool_call>" not in text


def test_fix01_uncovered_records_remain_and_output_can_be_read_by_owning_run():
    source = records()
    source.insert(
        0, {"record_type": "error", "unit_index": 1, "content": "uncovered fact"}
    )
    store = ExecutionHistory()
    text = render_persisted_actions(
        source, assistant_message_id=42, history=store, owner="new-run"
    )
    assert "uncovered fact" in text
    assert json.loads(store.read('new-run', 'message:42/unit-index:5'))['text'] == '<STDOUT>actual stdout</STDOUT>'
    with pytest.raises(PermissionError):
        store.read("other-run", "message:42/unit-index:5")


@pytest.mark.parametrize("kind", ["summary", "preview"])
def test_fix01_committed_view_is_restored_with_full_original_readable(kind):
    source = records()
    payload = json.loads(source[-1]["content"])
    payload["model_view"] = {kind: "accepted compact representation"}
    source[-1]["content"] = json.dumps(payload)
    store = ExecutionHistory()
    text = render_persisted_actions(
        source, assistant_message_id=42, history=store, owner="new-run"
    )
    assert "accepted compact representation" in text
    assert "actual stdout" not in text
    assert 'actual stdout' in json.loads(store.read('new-run', 'message:42/unit-index:5'))['text']
    assert render_persisted_actions(source, assistant_message_id=42, history=store, owner='new-run') == text


@pytest.mark.parametrize(
    "mutation",
    ["missing_unit", "child", "invalid_xml", "unknown_schema", "bad_call", "overlap"],
)
def test_fix01_unproven_projection_never_hides_raw_evidence(mutation):
    source = records()
    payload = json.loads(source[-1]["content"])
    if mutation == "missing_unit":
        source.pop(1)
    elif mutation == "child":
        source[0]["invocation_id"] = "child-owner"
    elif mutation == "invalid_xml":
        payload["content"] = "<STDOUT>not closed"
    elif mutation == "unknown_schema":
        payload["model_action"]["schema_version"] = 2
    elif mutation == "bad_call":
        payload["model_action"]["tool_calls"][0]["id"] = ""
    elif mutation == "overlap":
        source.append(deepcopy(source[-1]) | {"unit_index": 6})
    source[2 if len(source) > 2 else 1]["content"] = json.dumps(payload)
    text = render_persisted_actions(source, assistant_message_id=42)
    assert "EXPANDED" in text
    assert "<completed_action>" not in text
    assert "<tool_call>" not in text


def test_fix01_real_renderer_and_request_capture_use_restored_representation():
    from nexent.core.agents.context.manager import ContextManager
    from nexent.core.agents.context.models import ConversationTurnContextItem
    from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime

    manager = ContextManager(message_format="codeagent")
    turn = ConversationTurnContextItem(id="turn", type="conversation_turn", content=history_turn().content)
    messages = manager.build_context_messages([turn])
    assert [message["role"] for message in messages] == ["user", "user", "assistant"]
    assert "actual stdout" in str(messages[1]["content"])
    assert "actual stdout" not in str(messages[-1]["content"])
    from smolagents.models import get_clean_message_list, tool_role_conversions
    wire = get_clean_message_list(messages, role_conversions=tool_role_conversions)
    assert "actual stdout" in str(wire[0]["content"])
    assert "actual stdout" not in str(wire[-1]["content"])
    assert "actual answer" in str(wire[-1]["content"])
    assert str(wire).count("actual stdout") == 1
    assert manager._message_tokens(messages) < 2000
    runtime = ManagedContextRuntime(manager)
    manager.config.effective_input_limit_tokens = 2000
    runtime.capture_request(messages, [], object())
    assert runtime.usage_baseline.pending_estimate < 2000
    runtime.capture_request([*messages, {"role": "user", "content": "x" * 4000}], [], object())
    assert runtime.usage_baseline.pending_estimate > 2000


@pytest.mark.parametrize("dispatched", [False, True])
def test_fix01_parsed_candidate_is_not_promoted_to_executed_source(mocker, dispatched):
    from smolagents.agents import CodeAgent
    from smolagents.memory import ActionStep, ToolCall

    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent

    mocker.patch.object(CodeAgent, "_finalize_step")
    agent = CoreAgent.__new__(CoreAgent)
    agent._execution_history = ExecutionHistory()
    agent._execution_owner = "owner"
    agent._execution_loaded = False
    agent.agent_name = "root"
    agent.observer = mocker.Mock()
    step = ActionStep(step_number=1, timing=mocker.Mock())
    step.tool_calls = [
        ToolCall(
            name="python_interpreter", arguments="candidate_code()", id="candidate"
        )
    ]
    step.error = RuntimeError("actual failure")
    step.execution_dispatched = dispatched
    agent._finalize_step(step)
    action = agent._execution_history.get(step.execution_key).payload()["model_action"]
    assert action['dispatch_state'] == ('dispatched' if dispatched else 'not_dispatched')
    assert bool(action["tool_calls"]) is dispatched
    assert agent._execution_history.get(step.execution_key).fields['ERROR'] == 'actual failure'


def test_fix01_shared_store_keeps_historical_references_owner_scoped():
    source = records()
    store = ExecutionHistory()
    for owner in ["root", "authorized-child"]:
        render_persisted_actions(
            source, assistant_message_id=42, history=store, owner=owner
        )
        assert "actual stdout" in store.read(owner, "message:42/unit-index:5")
    with pytest.raises(PermissionError):
        store.read("unregistered-child", "message:42/unit-index:5")


@pytest.mark.parametrize("cancel", [False, True])
def test_fix01_post_response_acceptance_saves_only_sent_execution_view(saved_profile, monkeypatch, cancel):
    from smolagents.memory import ActionStep, ToolCall
    from smolagents.monitoring import Timing
    from test_run_local_completion import setup_core

    sender, runtime, model, memory = setup_core("smolagents", saved_profile, (70, 30), history=False)
    history = runtime.context_manager.config.execution_history = ExecutionHistory()
    fields = {"STDOUT": "head\n" + "middle\n" * 2000 + "tail\n"}
    key = history.register("owner", fields)
    history.bind(key, 42, 5)
    history.get(key).model_action = {"dispatch_state": "dispatched"}
    history.get(key).summary = "accepted factual summary"
    step = ActionStep(step_number=1, timing=Timing(start_time=0))
    step.tool_calls = [ToolCall(id="python", name="python_interpreter", arguments="print(computed)")]
    step.execution_fields, step.execution_key = fields, key
    memory.steps.append(step)
    prepared = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    response = model(prepared.messages)
    response.nexent_context_accepted = True
    later_key = history.register("owner", {"STDOUT": "later " * 10000})
    history.bind(later_key, 43, 6)
    later = ActionStep(step_number=2, timing=Timing(start_time=0))
    later.execution_key = later_key
    later.execution_fields = history.get(later_key).fields
    memory.steps.append(later)
    if cancel:
        compact = runtime.context_manager._compact_execution
        def cancelled_compact(*args, **kwargs):
            result = compact(*args, **kwargs)
            kwargs["record_override"].summary = "UNCOMMITTED_SUMMARY"
            model.stop_event.set()
            return result
        monkeypatch.setattr(runtime.context_manager, "_compact_execution", cancelled_compact)
    runtime.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
    assert history.get(key).model_view == (None if cancel else {"summary": "accepted factual summary"})
    assert history.get(key).fields == fields and history.get(key).reference == "message:42/unit-index:5"
    assert history.get(later_key).model_view is None
    assert history.get(key).summary == "accepted factual summary"
    assert "UNCOMMITTED_SUMMARY" not in json.dumps(history.get(key).payload())
    assert sender.summary_count == 0  # No old history exists to replace.
    if not cancel:
        prepared = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
        model(prepared.messages)
        assert "accepted factual summary" in str(sender.bodies[-1])
        assert "later " * 10000 in str(sender.bodies[-1])


def test_fix01_summary_retains_error_and_empty_stdout_in_original():
    source = records()
    payload = json.loads(source[-1]["content"])
    payload["content"] = (
        "<STDOUT></STDOUT>\n<RETURN_VALUE>False</RETURN_VALUE>\n<ERROR>actual failure</ERROR>"
    )
    payload["model_view"] = {"summary": "accepted summary"}
    source[-1]["content"] = json.dumps(payload)
    history = ExecutionHistory()
    text = render_persisted_actions(
        source, assistant_message_id=42, history=history, owner="owner"
    )
    assert "actual failure" in text and "accepted summary" in text
    original = json.loads(history.read("owner", "message:42/unit-index:5"))["text"]
    assert original == payload["content"]


def test_fix01_real_core_records_only_the_dispatched_interpreter_action():
    from smolagents.agents import EMPTY_PROMPT_TEMPLATES
    from smolagents.models import ChatMessage, Model

    from nexent.core.agents.context import ContextManager
    from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
    from nexent.core.utils.observer import MessageObserver

    class ControlledModel(Model):
        count = 0

        def generate(self, messages, **kwargs):
            self.count += 1
            return ChatMessage(
                role="assistant",
                content=(
                    '<code>print("ACTUAL_RESULT")</code>'
                    if self.count == 1
                    else "<final_answer>done</final_answer>"
                ),
            )

    observer = MessageObserver(lang="en")
    observer.execution_history = ExecutionHistory()
    templates = deepcopy(EMPTY_PROMPT_TEMPLATES)
    templates["system_prompt"] = "Execute the requested action once, then finish."
    model = ControlledModel(model_id="offline-controlled")
    agent = CoreAgent(
        observer=observer,
        model=model,
        tools=[],
        prompt_templates=templates,
        context_runtime=ManagedContextRuntime(ContextManager()),
        enable_protocol_repair_retry=True,
        max_steps=2,
        verbosity_level=0,
    )
    assert agent.run("Print ACTUAL_RESULT once") == "done"
    completed = [
        step for step in agent.memory.steps if getattr(step, "execution_key", None)
    ]
    assert len(completed) == 1 and model.count == 2
    payload = observer.execution_history.get(completed[0].execution_key).payload()
    assert payload["model_action"]["dispatch_state"] == "dispatched"
    assert payload['model_action']['tool_calls'][0]['arguments'] == 'print("ACTUAL_RESULT")'
    assert "ACTUAL_RESULT" in payload["content"]


@pytest.mark.parametrize('missing', ['model_action', 'covered_unit_indices', 'unit_index'])
def test_legacy_result_without_action_provenance_remains_readonly_evidence(missing):
    source = records()[-1]
    if missing == 'unit_index':
        source.pop(missing)
    else:
        payload = json.loads(source['content'])
        payload.pop(missing)
        source['content'] = json.dumps(payload)
    original = deepcopy(source)
    store = ExecutionHistory()
    rendered = render_persisted_actions([source], assistant_message_id=42, history=store, owner='new')
    assert 'actual stdout' in rendered and source == original
    assert '<completed_action>' not in rendered and '<tool_call>' not in rendered
    assert 'read_only="true"' in rendered
    with pytest.raises(PermissionError):
        store.read('new', 'message:42/unit-index:5')
