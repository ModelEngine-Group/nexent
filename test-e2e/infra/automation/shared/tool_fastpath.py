"""Controlled executors and official-tool fixtures shared by fast-path Cases."""

from __future__ import annotations

from smolagents.default_tools import FinalAnswerTool
from smolagents.local_python_executor import CodeOutput, LocalPythonExecutor
from smolagents.models import ChatMessage, MessageRole
from smolagents.monitoring import TokenUsage

from nexent.core.agents.tool_fastpath import (
    DeferredToolExecutor,
)
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool


class FinalEnvelopeModel:
    """Return a controlled final envelope through the real Agent model boundary."""

    model_id = "fixture"
    last_finish_reason = "stop"

    def __init__(self, answer="answer"):
        self.answer = answer

    def __call__(self, messages, **kwargs):
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=f"<final_answer>{self.answer}</final_answer>",
            token_usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class OrdinaryExecutor:
    """Controlled ordinary executor with a real interpreter for safe test code."""

    def __init__(self, *, group=None, execute=True):
        self.interpreter = LocalPythonExecutor(["json"])
        self._nexent_backend = "docker"
        self._nexent_session_container_group = group
        self.container = None
        self.calls = []
        self.variables = {}
        self.tools = {}
        self.execute = execute

    @property
    def state(self):
        return self.interpreter.state

    def send_variables(self, variables):
        self.variables.update(variables)
        self.interpreter.send_variables(variables)

    def send_tools(self, tools):
        self.tools = tools
        self.interpreter.send_tools(tools)

    def __call__(self, code):
        self.calls.append(code)
        if self.execute:
            return self.interpreter(code)
        return CodeOutput(output=None, logs="", is_final_answer=False)

def make_wrapper(monkeypatch, *, execute=True, stop_event=None):
    tool = ReadSkillConfigTool(
        config_overrides={"demo": {"value": "answer"}}, authorized_skill_names=["demo"],
    )
    calls = []
    forward = tool.forward

    def observed(skill_name):
        calls.append(skill_name)
        return forward(skill_name)

    monkeypatch.setattr(tool, "forward", observed)
    acquisitions = []
    releases = []
    ordinary = OrdinaryExecutor(execute=execute)

    def acquire():
        acquisitions.append(True)
        return ordinary

    wrapper = DeferredToolExecutor(acquire, releases.append, {tool.name: tool}, stop_event)
    wrapper.send_tools({tool.name: tool, "final_answer": FinalAnswerTool()})
    wrapper.send_variables({"metadata": {"request": "example"}})
    return wrapper, ordinary, calls, acquisitions, releases
