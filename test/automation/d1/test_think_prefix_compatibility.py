"""TPC-D1-001..006: reasoning prefixes preserve executable and final boundaries."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from smolagents.local_python_executor import LocalPythonExecutor

from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.output_protocol import (
    ExecutableAction,
    ExplicitFinalAnswer,
    ModelOutputProtocolError,
    classify_model_output,
)

PREFIXES = [
    "Read the guide first.\n",
    "<think>Read the guide.</think>\n",
    "<think>Read the guide.</think>First load the skill.\n",
    "Read the guide.</think>\n",
    "<think>Read the guide.\n",
    "<think>One.</think><think>Two.</think>\n",
    "<think>One.<think>Two.</think></think>\n",
]
CODE = 'skill_content = read_skill_md(skill_name="general_quality_checker")\nprint(skill_content)'
INVALID = [
    "</think><code>read_skill_md(",
    "<think>Read the guide.<code>read_skill_md(</code>",
    "</think><code></code>",
    "<code>print(1)</code>explanation<code>print(2)</code>",
    "<code>print(1)</code>suffix",
    "<analysis>reason</analysis><code>print(1)</code>",
    "<|channel|>analysis<code>print(1)</code>",
    "<final_answer>partial",
    "<final_answer>one</final_answer><final_answer>two</final_answer>",
    "<final_answer>done</final_answer>suffix",
    "<think>Only think.</think>",
    "Only think.</think>",
    "<think>Only think.",
]


def envelope(code, legacy=False):
    return f"```<run>\n{code}\n```" if legacy else f"<code>{code}</code>"


def make_agent(content, prior_errors=0, finish_reason="stop"):
    """Keep parsing and local Python execution real; isolate provider/context/monitoring."""
    agent = object.__new__(CoreAgent)
    agent.agent_name = agent.name = "prefix-test"
    agent.lang = "en"
    agent.step_number = 1
    agent.memory = SimpleNamespace(steps=[])
    agent.observer = MagicMock()
    agent.logger = MagicMock()
    agent.context_runtime = MagicMock()
    agent.context_runtime.chars_per_token = 4
    agent.context_runtime.prepare_step.return_value = SimpleNamespace(
        messages=[], memory_messages=None, evidence=None,
    )
    agent.context_runtime.token_counts.return_value = {}
    agent._history_step_count = 0
    agent._context_tools = lambda: []
    agent._emit_history_summary_event = lambda: None
    agent._log_model_call_parameters = lambda *_args, **_kwargs: None
    agent._record_output_protocol = MagicMock()
    agent._use_structured_outputs_internally = False
    agent._protocol_repair_messages = []
    agent._consecutive_protocol_errors = prior_errors
    agent.output_protocol = "code_action"
    agent.enable_protocol_repair_retry = True
    agent.enable_planning = False
    agent.verification_controller = None
    agent.clarification_tool_name = None
    agent.stop_event = threading.Event()
    message = SimpleNamespace(
        content=content, token_usage=None, model_attempt_id="prefix-attempt",
        model_attempt_number=1, model_attempt_commit_deferred=True,
    )
    agent.model = MagicMock(return_value=message)
    agent.model.supports_deferred_attempt_commit = True
    agent.model.last_finish_reason = finish_reason
    read_skill = MagicMock(return_value="Quality check guide")
    executor = LocalPythonExecutor(additional_authorized_imports=[])
    executor.send_tools({"read_skill_md": read_skill})
    agent.python_executor = MagicMock(wraps=executor)
    step = SimpleNamespace(
        step_number=1, model_output=None, model_output_message=None,
        model_input_messages=None, token_usage=None, tool_calls=None,
        observations=None, action_output=None,
    )
    return agent, step, read_skill


@pytest.fixture(autouse=True)
def isolate_monitoring(monkeypatch):
    monkeypatch.setattr("nexent.core.agents.core_agent.get_monitoring_manager", lambda: MagicMock())


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("legacy", [False, True])
def test_tpc_d1_001_compatible_prefix(prefix, legacy):
    result = classify_model_output(prefix + envelope(CODE, legacy), protocol="code_action")
    assert result == ExecutableAction(code=CODE, legacy_format=legacy)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("prior_errors", [0, 2])
def test_tpc_d1_002_skill_action_executes_once(prefix, prior_errors):
    agent, step, read_skill = make_agent(prefix + envelope(CODE), prior_errors)
    outputs = list(agent._step_stream(step))
    read_skill.assert_called_once_with(skill_name="general_quality_checker")
    agent.python_executor.assert_called_once_with(CODE)
    assert len(outputs) == 1 and outputs[0].is_final_answer is False
    assert "Quality check guide" in step.observations
    assert not hasattr(step, "_final_answer_source")
    assert agent._consecutive_protocol_errors == 0
    agent.observer.commit_model_attempt.assert_called_once_with("prefix-attempt", 1)
    agent.observer.rollback_model_attempt.assert_not_called()
    agent.model.assert_called_once()


@pytest.mark.parametrize("output", INVALID[:7])
def test_tpc_d1_003_invalid_action_remains_error(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")


@pytest.mark.parametrize("output", INVALID)
def test_tpc_d1_004_marked_output_never_raw_final(output):
    agent, step, read_skill = make_agent(output, 2)
    with pytest.raises(ModelOutputProtocolError):
        list(agent._step_stream(step))
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
    assert not hasattr(step, "_final_answer_source")
    agent.observer.rollback_model_attempt.assert_called_once_with("prefix-attempt", 1)
    agent.observer.commit_model_attempt.assert_not_called()


def test_tpc_d1_004_plain_exhaustion_remains_compatible():
    agent, step, read_skill = make_agent("A complete plain answer.", 2)
    outputs = list(agent._step_stream(step))
    assert outputs[0].is_final_answer is True
    assert outputs[0].output == "A complete plain answer."
    assert step._final_answer_source == "protocol_exhausted_raw_output"
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()


@pytest.mark.parametrize("prefix", PREFIXES)
def test_tpc_d1_005_ordinary_final_prefix(prefix):
    payload = "Checked **quality**."
    output = prefix + f"<final_answer>{payload}</final_answer>"
    assert classify_model_output(output, protocol="code_action") == ExplicitFinalAnswer(answer=payload)
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="final_envelope")


@pytest.mark.parametrize("output", INVALID[7:10])
def test_tpc_d1_005_final_boundaries_remain_strict(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")


def test_tpc_d1_006_python_protocol_data_is_preserved():
    code = 'value = "<think>data</think><code>example</code>"\n# </think> comment\nprint(value)'
    assert classify_model_output("</think>" + envelope(code), protocol="code_action") == ExecutableAction(code=code)
