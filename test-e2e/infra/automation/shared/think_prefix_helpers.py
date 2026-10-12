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
