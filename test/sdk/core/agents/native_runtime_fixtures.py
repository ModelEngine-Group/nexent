# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Acceptance-derived native protocol unit tests; live proof is separate."""

from copy import deepcopy

from nexent.core.agents.native_runtime import (
    NativeToolCallingAgent,
)
from smolagents.models import ChatMessage, Model
from smolagents.tools import Tool


class EchoTool(Tool):
    name = "echo"
    description = "Return text."
    inputs = {"text": {"type": "string", "description": "Text to return."}}  # noqa: RUF012 - smolagents tool schema.
    output_type = "string"

    def forward(self, text: str) -> str:
        return text


class ScriptedModel(Model):
    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        wire = next(self.responses)
        message = ChatMessage.from_dict(deepcopy(wire))
        message.raw = wire
        message.finish_reason = "tool_calls" if wire.get("tool_calls") else "stop"
        return message


def call(identifier, name="echo", arguments='{"text":"hello"}'):
    return {
        "id": identifier,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def agent_for(responses):
    model = ScriptedModel(responses)
    return NativeToolCallingAgent(
        tools=[EchoTool()], model=model, verbosity_level=0
    ), model




def guarded_agent(responses, tool=None, executor=None):
    from nexent.core.agents.agent_model import (
        AgentVerificationConfig,
        GuardrailConfig,
        GuardrailRule,
    )

    model = ScriptedModel(responses)
    agent = NativeToolCallingAgent(
        tools=[tool or EchoTool()],
        model=model,
        executor=executor,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            guardrail_config=GuardrailConfig(
                enabled=True,
                rules=[
                    GuardrailRule(name="blocked", pattern="forbidden", severity="block")
                ],
            )
        ),
    )
    return agent, model
