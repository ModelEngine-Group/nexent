# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""RSR-001 regression coverage for runtime action records."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from smolagents.agents import EMPTY_PROMPT_TEMPLATES
from smolagents.models import ChatMessage, Model

from nexent.core.agents.context import ContextManager
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent, ModelOutputProtocolExhaustedError
from nexent.core.agents.cores.smolagents.output_protocol import (
    ModelOutputProtocolError,
    NonterminalThought,
    ProtocolErrorReason,
    classify_model_output,
    is_raw_final_answer_candidate,
)
from nexent.core.utils.observer import MessageObserver

RECORD = (
    "Executed action:\n[{'id': 'call_1', 'type': 'function', "
    "'function': {'name': 'python_interpreter', 'arguments': 'print(1)'}}]"
)
JSON_RECORD = (
    'Executed action:\r\n[\r\n  {"id": "call_1", "type": "function", '
    '"function": {"name": "python_interpreter"}}\r\n]'
)
FENCE = "```"


@pytest.mark.parametrize("text", [RECORD, " \n" + RECORD, "reasoning\n" + RECORD, JSON_RECORD])
def test_reserved_record_is_rejected_by_both_protocol_and_exhaustion(text):
    with pytest.raises(ModelOutputProtocolError) as failure:
        classify_model_output(text, protocol="code_action", finish_reason="stop")
    assert failure.value.reason == ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT
    assert not is_raw_final_answer_candidate(text)


@pytest.mark.parametrize("text", [
    "[1, 2, 3]",
    '{"answer": 42}',
    'Executed action:\n[{"id": "shipment-1", "status": "delivered"}]',
    "Executed action:\n[1, 2, 3]",
    "A complete ordinary answer.",
    "Executed action: is the label used by the framework.",
    f"{FENCE}text\n{RECORD}\n{FENCE}",
    "`Executed action:` is a quoted label.",
    "\n".join("> " + line for line in RECORD.splitlines()),
])
def test_normal_answers_and_examples_are_never_executable(text):
    assert isinstance(classify_model_output(text, protocol="code_action"), NonterminalThought)
    assert is_raw_final_answer_candidate(text)


def test_code_literal_and_explicit_final_explanation_are_not_reserved_records():
    code = '<code>text = "Executed action:\\n[1]"</code>'
    assert classify_model_output(code, protocol='code_action').code == 'text = "Executed action:\\n[1]"'
    answer = f"<final_answer>Here is an example:\n{FENCE}text\n{RECORD}\n{FENCE}</final_answer>"
    assert 'Here is an example:' in classify_model_output(answer, protocol='code_action').answer


def test_reserved_record_exhaustion_fails_without_a_fourth_generation_or_execution():
    requests = []

    class FixtureModel(Model):
        def generate(self, messages, **kwargs):
            requests.append(messages)
            assert len(requests) <= 3
            self.last_finish_reason = "stop"
            return ChatMessage(role="assistant", content=RECORD)

    agent = CoreAgent(
        observer=MessageObserver(lang="en"),
        model=FixtureModel(model_id="fixture"),
        tools=[],
        prompt_templates=deepcopy(EMPTY_PROMPT_TEMPLATES),
        context_runtime=ManagedContextRuntime(ContextManager()),
        enable_protocol_repair_retry=True,
        max_steps=5,
        verbosity_level=-1,
    )
    agent.python_executor = Mock()
    with pytest.raises(ModelOutputProtocolExhaustedError):
        agent.run("Produce a result after the required execution.")
    assert len(requests) == 3
    agent.python_executor.assert_not_called()
