"""FAF-D1-001: role classification, completion and step persistence."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.case_id("FAF-D1-001"), pytest.mark.stage("D1")]


ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observer_module = load_module("faf_observer", "sdk/nexent/core/utils/observer.py")
projection = load_module("faf_projection", "backend/utils/final_answer_projection.py")
MessageObserver = observer_module.MessageObserver
ProcessType = observer_module.ProcessType


def events(observer):
    return [json.loads(item) for item in observer.get_cached_message()]


@pytest.mark.parametrize("prefix,kind", [("", None), ("Thought. ", "model_output_thinking"),
                                         ("<think>Reason.</think>", "model_output_deep_thinking")])
def test_faf_d1_001_tagged_stream(prefix, kind):
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("attempt", 1)
    for token in prefix + "<final_answer>Unique answer.</final_answer>":
        observer.add_model_new_token(token)
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("attempt", 1)
    observer.complete_final_answer("agent", "Unique answer.")
    assert observer.get_final_answer() == "Unique answer."
    result = events(observer)
    answer = [item for item in result if item["type"] == "final_answer"]
    assert "".join(item["content"] for item in answer) == "Unique answer."
    assert answer[-1]["answer_phase"] == "complete" and answer[-1]["content"] == ""
    assert all(item.get("attempt_id") == "attempt" for item in answer[:-1])
    thought = [item for item in result if item["type"].startswith("model_output")]
    assert {item["type"] for item in thought} == ({kind} if kind else set())
    assert len({item["step_id"] for item in result}) == 1


def test_faf_d1_001_subagent_and_retry():
    observer = MessageObserver()
    observer.add_subagent_start(2, "Child", invocation_id="child")
    observer.add_message("Child", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("failed", 1)
    observer.add_model_new_token("<FINAL_ANSWER>Rejected</FINAL_ANSWER>")
    observer.rollback_model_attempt("failed", 1)
    observer.begin_model_attempt("accepted", 2)
    observer.add_model_new_token("<final_answer>Accepted</final_answer>")
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("accepted", 2)
    observer.complete_final_answer("Child", "Accepted")
    result = events(observer)
    assert all(item.get("invocation_id") == "child" for item in result)
    assert result[-1]["content"] == ""
    assert result[-1]["answer_phase"] == "complete"


def unit(kind, text, step, invocation=None):
    return {"type": kind, "content": text, "_step_id": step, "invocation_id": invocation}


def test_faf_d1_001_legacy_and_pure_step_cleanup():
    units = [unit("step_count", "Step 1", "first"), unit("model_output_thinking", "Real thought", "first"),
             unit("step_count", "Step 2", "second"), unit("model_output_thinking", "Answer", "second"),
             unit("model_output_thinking", "Sibling", "second", "child")]
    completion = {"type": "final_answer", "content": "Answer", "step_id": "second",
                  "answer_phase": "complete", "reclassify_step": True}
    assert projection.resolve_answer_completion(units, completion)
    units.append(unit("final_answer", "Answer", "second"))
    projection.remove_answer_only_steps(units)
    assert [(item["type"], item["content"]) for item in units] == [
        ("step_count", "Step 1"), ("model_output_thinking", "Real thought"),
        ("model_output_thinking", "Sibling"), ("final_answer", "Answer")]


def test_faf_d1_001_deep_reasoning_is_retained():
    units = [unit("step_count", "Step 1", "one"), unit("model_output_deep_thinking", "Deep", "one"),
             unit("model_output_thinking", "Answer", "one")]
    completion = {"step_id": "one", "reclassify_step": True, "content": "Answer"}
    projection.resolve_answer_completion(units, completion)
    units.append(unit("final_answer", "Answer", "one"))
    projection.remove_answer_only_steps(units)
    assert [item["type"] for item in units] == ["step_count", "model_output_deep_thinking", "final_answer"]


def test_faf_d1_001_reasoning_protocol_quote_is_not_answer():
    observer = MessageObserver()
    observer.add_message("Child", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("child", 1)
    reasoning = "I must output <final_answer>Child</final_answer>."
    for fragment in (reasoning[:25], reasoning[25:]):
        observer.add_model_reasoning_content(fragment)
    observer.add_model_new_token("<final_answer>Child</final_answer>")
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("child", 1)
    observer.complete_final_answer("Child", "Child")
    result = events(observer)
    assert "".join(item["content"] for item in result if item["type"] == "final_answer") == "Child"
    assert "".join(item["content"] for item in result if item["type"] == "model_output_deep_thinking") == reasoning


def test_faf_d1_001_managed_agent_completes_one_answer(mocker):
    from nexent.core.agents.core_agent import CoreAgent

    observer = MessageObserver()
    observer.add_subagent_start("child", "Child", invocation_id="child")
    observer.add_message("Child", ProcessType.STEP_COUNT, 1)
    observer.add_model_new_token("<final_answer>Child result</final_answer>")
    agent = object.__new__(CoreAgent)
    agent.workspace_path = None
    agent.state = {}
    agent.name = "child"
    agent.observer = observer
    agent.provide_run_summary = False
    agent.prompt_templates = {"managed_agent": {"task": "{{task}}", "report": "{{final_answer}}"}}
    mocker.patch.object(agent, "run", return_value="Child result")
    assert agent("Test") == "Child result"
    result = events(observer)
    assert "".join(item["content"] for item in result if item["type"] == "final_answer") == "Child result"
    assert result[-2]["answer_phase"] == "complete"
    assert result[-1]["type"] == "agent_finish" and result[-1]["content"] == ""


def test_faf_d1_001_legacy_envelope_retains_trailing_answer(mocker):
    from nexent.core.agents.core_agent import CoreAgent

    agent = object.__new__(CoreAgent)
    agent.observer = MessageObserver()
    agent.logger = MagicMock()
    agent._protocol_repair_messages = []
    mocker.patch.object(agent, "_resolve_deferred_model_attempt")
    memory = SimpleNamespace(model_output_message=None)
    result = agent._legacy_parse_fallback(memory, "Thought <final_answer>Result</final_answer> tail", "stop")
    assert result.output == "Result tail"


def test_faf_d1_001_legacy_completion_moves_body_without_retransmission():
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.add_model_new_token("Legacy answer")
    observer.flush_remaining_tokens()
    observer.mark_direct_final_answer()
    observer.complete_final_answer("agent", "Legacy answer")
    assert observer.get_final_answer() == "Legacy answer"
    result = events(observer)
    assert result[-1]["content"] == "" and result[-1]["reclassify_step"]
    assert sum(item["content"] == "Legacy answer" for item in result) == 1
    step = result[-1]["step_id"]
    units = [unit("step_count", "Step 1", step), unit("model_output_thinking", "Legacy answer", step)]
    assert not projection.resolve_answer_completion(units, result[-1])
    projection.remove_answer_only_steps(units)
    assert len(units) == 1 and units[0]["type"] == "final_answer"
    assert units[0]["_content_fragments"] == ["Legacy answer"]


@pytest.mark.parametrize("prefix", ["", "Thought. "])
def test_faf_d1_001_merged_code_action_accepts_final_envelope(prefix):
    from nexent.core.agents.output_protocol import ExplicitFinalAnswer, classify_model_output

    result = classify_model_output(prefix + "<FINAL_ANSWER>Final</FINAL_ANSWER>", protocol="code_action")
    assert isinstance(result, ExplicitFinalAnswer)
    assert result.answer == "Final"
