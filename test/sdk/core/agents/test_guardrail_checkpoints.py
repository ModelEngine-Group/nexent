"""Deterministic scenarios for guardrail checkpoints ② (tool output) and ③ (tool input).

Checkpoint ① intercepts a keyword the user types this turn, so ②/③ only fire when the
keyword comes from a source ① does not screen: a tool's returned data (②), or a tool arg
the LLM composed / inherited from a prior tool's raw return (③). Exercises the real
``_guardrail_wrap_one`` wrap and ``check_output`` / ``check_tool_args`` engine.
"""

import types
from unittest.mock import MagicMock

import pytest

from nexent.core.agents.agent_model import AgentVerificationConfig, GuardrailConfig, GuardrailRule
from nexent.core.agents.core_agent import CoreAgent, ToolInputBlockedError
from nexent.core.agents.verification import VerificationController

KEYWORD = "机密信息"
PATTERN = KEYWORD


# ---------------------------------------------------------------------------
# Minimal test doubles -- avoid constructing a full CoreAgent (needs a model).
# _guardrail_wrap_one only touches self.verification_controller and self.logger,
# so a shim is enough to drive the real wrap method. MagicMock stands in for the
# logger/observer (auto-stubs any method the guardrail path calls).
# ---------------------------------------------------------------------------

class _ShimAgent:
    """Just enough of CoreAgent for _guardrail_wrap_one(self, tool, engine)."""

    def __init__(self, controller, logger):
        self.verification_controller = controller
        self.logger = logger


class _Tool:
    """Minimal stand-in for a smolagents Tool: a name and a forward()."""

    def __init__(self, name, fn):
        self.name = name
        self._fn = fn
        self.calls = []

    def forward(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._fn(*args, **kwargs)


def _make_controller(rule):
    guardrail_cfg = GuardrailConfig(enabled=True, rules=[rule], default_action="pass")
    verification_cfg = AgentVerificationConfig(enabled=True, guardrail_config=guardrail_cfg)
    controller = VerificationController(
        config=verification_cfg,
        observer=MagicMock(),
        agent_name="test",
        model=None,  # only used for LLM-based final verification, not exercised here
        logger=MagicMock(),
    )
    return controller


def _wrap(controller, tool):
    CoreAgent._guardrail_wrap_one(_ShimAgent(controller, MagicMock()), tool, controller.guardrail_engine)
    return tool


# ---------------------------------------------------------------------------
# ② tool_output: covered by test_guardrail_engine.py (check_output unit tests);
# the _step_stream integration is exercised by test_step_stream_checkpoint2_mask below.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ③(a) tool_input: keyword in an LLM-generated tool arg
# ---------------------------------------------------------------------------

def test_checkpoint3a_tool_input_block_prevents_execution():
    """A tool arg the LLM composed with the keyword is blocked before the tool runs."""
    rule = GuardrailRule(name="confidential", pattern=PATTERN, severity="block")
    controller = _make_controller(rule)
    send = _wrap(controller, _Tool("send_email", lambda body: f"sent: {body}"))

    with pytest.raises(ToolInputBlockedError) as exc_info:
        send.forward(f"把{KEYWORD}发给客户")
    assert send.calls == []  # underlying forward never ran
    refusal = exc_info.value.refusal
    assert KEYWORD in refusal  # echoes the matched content, like checkpoint ①
    assert "send_email" in refusal  # names the blocked tool
    assert "confidential" in refusal  # names the configured rule


def test_checkpoint3a_tool_input_mask_redacts_arg_then_executes():
    """mask redacts the keyword in the arg, then the tool executes on the masked value."""
    rule = GuardrailRule(name="confidential", pattern=PATTERN, severity="mask")
    controller = _make_controller(rule)
    send = _wrap(controller, _Tool("send_email", lambda body: f"sent: {body}"))

    result = send.forward(f"把{KEYWORD}发给客户")
    assert KEYWORD not in result
    assert send.calls == [(("把***发给客户",), {})]


# ---------------------------------------------------------------------------
# ③(b) tool_input variable flow: toolA returns keyword -> passed to toolB
# ---------------------------------------------------------------------------

def test_checkpoint3b_variable_flow_blocked_at_toolB():
    """Raw keyword returned by toolA and passed to toolB is caught by ③ on toolB."""
    rule = GuardrailRule(name="confidential", pattern=PATTERN, severity="block")
    controller = _make_controller(rule)
    engine = controller.guardrail_engine

    reader = _wrap(controller, _Tool("read_record", lambda rid: f"record {rid}: {KEYWORD} 营收7000亿"))
    writer = _wrap(controller, _Tool("write_log", lambda content: f"logged: {content}"))

    raw = reader.forward("rec-001")  # input has no keyword -> ③ passes, tool runs, RETURNS keyword
    assert KEYWORD in raw

    with pytest.raises(ToolInputBlockedError) as exc_info:
        writer.forward(raw)  # raw carries the keyword -> ③ blocks toolB
    assert writer.calls == []  # toolB never ran
    assert KEYWORD in exc_info.value.refusal  # refusal echoes the matched content
    assert "write_log" in exc_info.value.refusal

    # ② then masks toolA's observation for memory (separate layer, after the step)
    masked = engine.check_output(
        observation=raw, code_action="..."
    )
    assert KEYWORD not in masked.cleaned_content


# ---------------------------------------------------------------------------
# _guardrail_wrap_tools: iterate self.tools + self.managed_agents and wrap each
# ---------------------------------------------------------------------------

def _shim_with_tools(controller, tools, managed_agents=None):
    agent = _ShimAgent(controller, MagicMock())
    agent.tools = tools
    agent.managed_agents = managed_agents or {}
    # _guardrail_wrap_tools calls self._guardrail_wrap_one(...); bind the real CoreAgent
    # method onto the shim so the unbound-self call dispatches back into CoreAgent.
    agent._guardrail_wrap_one = types.MethodType(CoreAgent._guardrail_wrap_one, agent)
    return agent


def test_guardrail_wrap_tools_wraps_every_tool_in_both_containers():
    """_guardrail_wrap_tools walks self.tools and self.managed_agents and wraps each forward."""
    rule = GuardrailRule(name="confidential", pattern=PATTERN, severity="block")
    controller = _make_controller(rule)
    t1 = _Tool("send_email", lambda body: f"sent: {body}")
    t2 = _Tool("write_log", lambda content: f"logged: {content}")
    agent = _shim_with_tools(controller, {"send_email": t1}, {"write_log": t2})

    CoreAgent._guardrail_wrap_tools(agent)

    assert getattr(t1, "_guardrail_wrapped", False) is True
    assert getattr(t2, "_guardrail_wrapped", False) is True
    # a blocked arg now raises before the underlying forward runs
    with pytest.raises(ToolInputBlockedError):
        t1.forward(KEYWORD)
    assert t1.calls == []


def test_guardrail_wrap_tools_no_engine_is_noop():
    """When guardrail is disabled, _guardrail_wrap_tools wraps nothing."""
    disabled_cfg = AgentVerificationConfig(enabled=True, guardrail_config=None)
    controller = VerificationController(
        config=disabled_cfg, observer=MagicMock(), agent_name="test",
        model=None, logger=MagicMock(),
    )
    assert controller.guardrail_engine is None
    t = _Tool("send_email", lambda body: body)
    agent = _shim_with_tools(controller, {"send_email": t})
    CoreAgent._guardrail_wrap_tools(agent)
    assert getattr(t, "_guardrail_wrapped", False) is False  # not wrapped
    assert t.forward("x") == "x"  # original forward untouched


# ---------------------------------------------------------------------------
# _step_stream guardrail integration: checkpoints ①②③
# ---------------------------------------------------------------------------

import threading as _threading
from nexent.core.agents.core_agent import FinalAnswerError


def _make_step_agent(rule, messages, model_output="ok"):
    """Build a CoreAgent via object.__new__ with a guardrail controller + mock model.

    Args:
        rule: GuardrailRule for the controller.
        messages: Input messages list (dicts with role/content).
        model_output: What the mock model returns.

    Returns:
        A CoreAgent instance ready for _step_stream.
    """
    controller = _make_controller(rule)
    agent = object.__new__(CoreAgent)
    agent.name = "test"
    agent.agent_name = "test"
    agent.observer = MagicMock()
    agent.step_number = 1
    agent.memory = MagicMock()
    agent.memory.steps = []
    agent.memory.system_prompt = None
    agent.logger = MagicMock()
    agent.monitor = MagicMock()
    agent.stop_event = _threading.Event()
    agent.code_block_tags = ["", ""]
    agent._history_step_count = 0
    agent._last_uncompressed_est = 0
    agent._context_tools = MagicMock(return_value=[])
    agent._use_structured_outputs_internally = False
    agent._ephemeral_system_messages = None
    agent.verification_controller = controller
    agent.verification_config = controller.config
    agent.python_executor = MagicMock()
    agent.context_runtime = MagicMock()
    agent.context_runtime.chars_per_token = 1.0
    mock_context = MagicMock()
    mock_context.messages = messages
    agent.context_runtime.prepare_step = MagicMock(return_value=mock_context)
    agent.context_runtime.truncate_observation = MagicMock()
    agent.context_manager = None
    agent.model = MagicMock()
    response = MagicMock()
    response.content = model_output
    agent.model.return_value = response
    return agent


def _msg(role, content):
    return {"role": role, "content": content}


def test_step_stream_checkpoint1_terminate():
    """Checkpoint ①: block rule on new_input → terminate → FinalAnswerError with refusal."""
    rule = GuardrailRule(
        name="destructive_rm",
        pattern=r"(?<![A-Za-z])rm\s+(-[A-Za-z]*[rfRF]|--recursive|--force)",
        severity="block",
    )
    agent = _make_step_agent(rule, messages=[_msg("user", "rm -rf /tmp")])
    action_step = MagicMock()
    with pytest.raises(FinalAnswerError):
        next(agent._step_stream(action_step))
    assert agent.model.call_count == 0  # model never called (terminated before)
    assert action_step.model_output  # refusal text was set


def test_step_stream_checkpoint1_mask():
    """Checkpoint ①: mask rule → input masked → model called with redacted input."""
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="mask")
    agent = _make_step_agent(rule, messages=[_msg("user", "这是机密信息内容")])
    action_step = MagicMock()
    with pytest.raises(FinalAnswerError):  # parse("ok") fails → FinalAnswerError
        next(agent._step_stream(action_step))
    assert agent.model.call_count == 1  # model was called (with masked input)
    called_messages = agent.model.call_args[0][0]
    masked_text = "".join(
        str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", ""))
        for m in (called_messages or [])
    )
    assert "机密信息" not in masked_text
    assert "***" in masked_text


def test_step_stream_checkpoint1_pass():
    """Checkpoint ①: no match → pass → model called with original input."""
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(rule, messages=[_msg("user", "hello world")])
    action_step = MagicMock()
    with pytest.raises(FinalAnswerError):
        next(agent._step_stream(action_step))
    assert agent.model.call_count == 1  # model called


def test_step_stream_checkpoint2_mask():
    """Checkpoint ②: tool output with keyword → mask → observation redacted."""
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="mask")
    agent = _make_step_agent(
        rule,
        messages=[_msg("user", "hello")],
        model_output="<code>print(1)</code>",
    )
    code_output = MagicMock()
    code_output.output = "result: 机密信息 here"
    code_output.logs = ""
    code_output.is_final_answer = True
    agent.python_executor.return_value = code_output
    agent.verification_controller.config.step_verification_enabled = False
    agent.verification_controller.config.final_verification_enabled = False
    action_step = MagicMock()
    try:
        next(agent._step_stream(action_step))
    except (FinalAnswerError, StopIteration):
        pass
    obs = str(action_step.observations)
    assert "机密信息" not in obs
    assert "***" in obs


def test_step_stream_checkpoint3_except_block():
    """Checkpoint ③: pending_refusal + python_executor raises → FinalAnswerError."""
    rule = GuardrailRule(
        name="destructive_rm",
        pattern=r"(?<![A-Za-z])rm\s+(-[A-Za-z]*[rfRF]|--recursive|--force)",
        severity="block",
    )
    agent = _make_step_agent(
        rule,
        messages=[_msg("user", "hello")],
        model_output="<code>print(1)</code>",
    )
    agent.python_executor.side_effect = Exception("tool blocked")
    agent.verification_controller.pending_tool_block_refusal = "blocked refusal text"
    agent.verification_controller.config.step_verification_enabled = False
    action_step = MagicMock()
    with pytest.raises(FinalAnswerError):
        next(agent._step_stream(action_step))
    assert "blocked refusal text" in str(action_step.model_output)


def test_step_stream_checkpoint3_tool_input_blocked_error_isinstance_branch():
    """Checkpoint ③: python_executor raises ToolInputBlockedError directly (no stashed
    pending_refusal) → the isinstance(e, ToolInputBlockedError) branch picks up e.refusal
    → FinalAnswerError ends the run (no retry loop)."""
    rule = GuardrailRule(
        name="destructive_rm",
        pattern=r"(?<![A-Za-z])rm\s+(-[A-Za-z]*[rfRF]|--recursive|--force)",
        severity="block",
    )
    agent = _make_step_agent(
        rule,
        messages=[_msg("user", "hello")],
        model_output="<code>print(1)</code>",
    )
    refusal_text = "I cannot run rm -rf (blocked by rule 'destructive_rm')."
    # No stashed pending_tool_block_refusal — rely on isinstance(e, ToolInputBlockedError).
    assert getattr(agent.verification_controller, "pending_tool_block_refusal", None) is None
    agent.python_executor.side_effect = ToolInputBlockedError(refusal_text, agent.logger)
    agent.verification_controller.config.step_verification_enabled = False
    action_step = MagicMock()
    with pytest.raises(FinalAnswerError):
        next(agent._step_stream(action_step))
    assert action_step.model_output == refusal_text


def test_step_stream_generic_exec_error_raises_agent_execution_error():
    """Checkpoint ③: a non-block exec error (no pending_refusal, not ToolInputBlockedError)
    falls through the refusal guard and raises AgentExecutionError (not FinalAnswerError)."""
    from nexent.core.agents.core_agent import AgentExecutionError
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(
        rule, messages=[_msg("user", "hello")], model_output="<code>print(1)</code>",
    )
    # Plain exec error, no stashed refusal, not a ToolInputBlockedError.
    agent.python_executor.side_effect = RuntimeError("exec boom")
    agent.verification_controller.config.step_verification_enabled = False
    action_step = MagicMock()
    with pytest.raises(AgentExecutionError):
        next(agent._step_stream(action_step))
    assert action_step.model_output != "exec boom"  # refusal path not taken


def test_step_stream_precheck_action_scope_blocking_raises_before_exec():
    """Checkpoint precheck: code_action with a dangerous term (os.system) fails the
    action_scope check (blocking) → AgentExecutionError raised before the tool runs."""
    from nexent.core.agents.core_agent import AgentExecutionError
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(
        rule,
        messages=[_msg("user", "hello")],
        model_output="<code>import os; os.system('ls')</code>",
    )
    # step_verification_enabled defaults to True → precheck runs.
    exec_output = MagicMock()
    exec_output.output = "ran"
    exec_output.logs = ""
    exec_output.is_final_answer = False
    agent.python_executor.return_value = exec_output
    action_step = MagicMock()
    with pytest.raises(AgentExecutionError):
        next(agent._step_stream(action_step))
    assert agent.python_executor.call_count == 0  # blocked at precheck, never executed


def test_run_return_full_result_aggregates_token_usage_success_state():
    """run(return_full_result=True): sums ActionStep.token_usage across memory.steps and
    reports state=success when the last step has no error."""
    from smolagents.agents import RunResult
    from smolagents.memory import ActionStep, FinalAnswerStep
    from smolagents.monitoring import Timing, TokenUsage

    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(rule, messages=[_msg("user", "hello")])
    agent.max_steps = 5
    agent.initialize_system_prompt = MagicMock(return_value="system prompt")
    agent.state = {}
    agent.return_full_result = True
    agent.tools = {}
    agent.managed_agents = {}
    agent.memory.steps = [
        ActionStep(step_number=1, timing=Timing(0, 1), token_usage=TokenUsage(10, 5)),
    ]
    agent.memory.get_full_steps = MagicMock(return_value=[{"step": 1}])
    agent._run_stream = MagicMock(return_value=iter([FinalAnswerStep(output="answer")]))

    result = agent.run("do task", return_full_result=True)
    assert isinstance(result, RunResult)
    assert result.output == "answer"
    assert result.state == "success"
    assert result.token_usage.input_tokens == 10
    assert result.token_usage.output_tokens == 5


def test_managed_agent_call_wraps_run_result_into_report():
    """__call__ (managed agent): renders the managed_agent report template around the
    sub-agent's run output."""
    from smolagents.agents import RunResult
    from smolagents.monitoring import Timing

    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(rule, messages=[_msg("user", "hello")])
    agent.name = "subagent"
    agent.state = {}
    agent.prompt_templates = {
        "managed_agent": {
            "task": "{{task}}",
            "report": "Report from {{name}}: {{final_answer}}",
        }
    }
    agent.provide_run_summary = False
    agent.run = MagicMock(return_value=RunResult(
        output="done", token_usage=None, steps=[], timing=Timing(0, 1), state="success"))

    answer = agent.__call__("subtask")
    assert "Report from subagent: done" in answer


def test_guardrail_wrap_tools_handles_non_dict_container():
    """_guardrail_wrap_tools falls back to iterating the container directly when
    it has no .values() (e.g. a list/tuple of managed agents)."""
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    controller = _make_controller(rule)
    tool = _Tool("send_email", lambda body: f"sent: {body}")
    # managed_agents as a list (no .values()) -> exercises except AttributeError.
    agent = _shim_with_tools(controller, {}, managed_agents=[tool])
    CoreAgent._guardrail_wrap_tools(agent)
    assert getattr(tool, "_guardrail_wrapped", False) is True


def test_append_verification_feedback_sets_observations_when_empty():
    """_append_verification_feedback: when action_step.observations is empty,
    it is set (not appended) to the feedback string (the else branch)."""
    from nexent.core.agents.verification import VerificationResult
    rule = GuardrailRule(name="pii", pattern="机密信息", severity="block")
    agent = _make_step_agent(rule, messages=[_msg("user", "hello")])
    result = MagicMock(spec=VerificationResult)
    result.failed_criteria = []
    result.repair_instruction = "fix it"
    result.event = "guardrail_input"
    result.severity = "warning"
    action_step = MagicMock()
    action_step.observations = ""  # falsy -> else branch
    agent._append_verification_feedback(action_step, result)
    assert action_step.observations  # set to a non-empty feedback string
    assert "fix it" in action_step.observations
