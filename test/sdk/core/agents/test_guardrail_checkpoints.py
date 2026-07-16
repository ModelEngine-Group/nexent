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
# ② tool_output
# ---------------------------------------------------------------------------

def test_checkpoint2_tool_output_keyword_masked_before_memory():
    """Keyword in a tool's RETURNED data is redacted by ② before entering memory."""
    rule = GuardrailRule(name="confidential", pattern=PATTERN, severity="mask")
    controller = _make_controller(rule)
    engine = controller.guardrail_engine

    kb = _wrap(controller, _Tool("kb_search", lambda q: f"doc: {KEYWORD} 营收7000亿 (query='{q}')"))
    observation = kb.forward("某公司")  # query has no keyword -> ③ passes, tool runs

    assert observation == f"doc: {KEYWORD} 营收7000亿 (query='某公司')"
    decision = engine.check_output(
        observation=observation, code_action="kb_search('某公司')", step_number=1, is_final_answer=False
    )
    assert decision.effective_action == "mask"
    assert KEYWORD not in decision.cleaned_content
    assert "***" in decision.cleaned_content


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
        observation=raw, code_action="...", step_number=1, is_final_answer=False
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
