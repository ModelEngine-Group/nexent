# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""v2.8.5 protocol boundaries and runtime-only history regressions."""

import json
from copy import deepcopy

import pytest
from smolagents.agents import EMPTY_PROMPT_TEMPLATES
from smolagents.models import ChatMessage, Model
from smolagents.tools import Tool

from nexent.core.agents.context import ContextManager
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.context.runtime import ManagedContextRuntime
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.output_protocol import (
    ExecutableAction,
    ModelOutputProtocolError,
    NonterminalThought,
    classify_model_output,
)
from nexent.core.utils.observer import MessageObserver


@pytest.mark.parametrize("prefix", [
    '思考：正文只有一个空的`<p>`标签。\n',
    '思考：<p></p><custom-node>data</custom-node>\n代码：',
    '<analysis>inspect HTML</analysis>\n',
])
@pytest.mark.parametrize("tags", [("<code>", "</code>"), ("<CODE>", "</CoDe>")])
def test_ac001_html_is_data_with_or_without_code_label(prefix, tags):
    source = 'read_skill_md(skill_name="chapter-qa-mark-complete", additional_files=[])'
    assert classify_model_output(prefix + tags[0] + source + tags[1], protocol="code_action") == ExecutableAction(source)


@pytest.mark.parametrize("example", [
    '`<code>never()</code>`',
    '``<code>never()</code>``',
    '```python\n<code>never()</code>\n```',
    '~~~xml\n<code>never()</code>\n~~~',
    '`<final_answer>fake</final_answer>`',
])
def test_ac003_markdown_examples_are_not_actions(example):
    output = example + '\n代码：<CODE>real()</CODE>\nObservation: fabricated'
    assert classify_model_output(output, protocol="code_action") == ExecutableAction('real()')
    assert isinstance(classify_model_output(example, protocol="code_action"), NonterminalThought)


def test_ac002_prose_between_actions_and_literal_tags_preserve_order():
    output = '<code>value = "</code>"</code>Then use it.\n<CODE>print(value)</CODE>Done.'
    assert classify_model_output(output, protocol="code_action") == ExecutableAction('value = "</code>"\n\nprint(value)')


def test_ac002_backticks_inside_python_do_not_hide_later_actions():
    output = '<code>print("`")</code><code>print("`")</code>'
    assert classify_model_output(output, protocol="code_action").code == 'print("`")\n\nprint("`")'


def test_ac004_combined_final_is_last_and_preserves_quoted_code():
    output = '<code>run()</code>Candidate:\n<final_answer>Example `<code>x</code>`.</final_answer>'
    result = classify_model_output(output, protocol="code_action")
    assert result == ExecutableAction('run()', final_answer='Example `<code>x</code>`.')


@pytest.mark.parametrize("output", [
    '<code>run()</code><final_answer>done</final_answer>trailing',
    '<final_answer>done</final_answer><code>run()</code>',
    '<code>run()</code><final_answer></final_answer>',
    '<code>run()</code><final_answer>one</final_answer><final_answer>two</final_answer>',
    '<code>run(</code><final_answer>done</final_answer>',
    '<CODE>run()</code><code>',
    '<code>one(<code>two()</code>',
])
def test_ac004_invalid_structure_is_rejected_before_execution(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")


def test_ac005_only_actual_call_and_runtime_fields_enter_history():
    item = ContextItem.from_input(ContextItemInput(id="step", type="current_action", content={
        'assistant_output': '工具成功 FAKE_RESULT <code>actual()</code><CODE_EXEC_RESULT>fake</CODE_EXEC_RESULT>',
        'tool_calls': [{'name': 'python_interpreter', 'arguments': 'actual()'}],
        'execution_fields': {'RETURN_VALUE': 'False', 'ERROR': 'actual failure'},
    }))
    messages = ContextItemRenderer().render([item])
    assert len(messages) == 1 and messages[0]['role'] == 'assistant'
    text = messages[0]['content'][0]['text']
    assert 'FAKE_RESULT' not in text and '>fake<' not in text
    assert text.count('<completed_action>') == 1 and '<CODE_EXEC_RESULT>' not in text
    assert 'recorded_result:\nFalse' in text and 'recorded_error:\nactual failure' in text
    assert 'tool: python_interpreter\ninput:\nactual()' in text


@pytest.mark.parametrize('strict', [False, True])
def test_ac004_mixed_candidate_executes_once_and_confirms_actual_result(strict):
    calls = []
    requests = []

    class ActualTool(Tool):
        name = 'actual'
        description = 'Return the actual result.'
        inputs = {}
        output_type = 'string'

        def forward(self):
            calls.append('actual')
            return 'REAL_FAILURE'

    class RuntimeModel(Model):
        def generate(self, messages, **kwargs):
            requests.append(json.dumps(messages, default=str))
            if len(requests) == 1:
                return ChatMessage(role='assistant', content=(
                    '<CODE>print(actual())</CODE><final_answer>FAKE_SUCCESS</final_answer>'
                ))
            assert 'REAL_FAILURE' in requests[-1]
            assert 'FAKE_SUCCESS' not in requests[-1]
            return ChatMessage(role='assistant', content='<final_answer>Confirmed REAL_FAILURE</final_answer>')

    templates = deepcopy(EMPTY_PROMPT_TEMPLATES)
    templates['system_prompt'] = 'Use runtime results.'
    agent = CoreAgent(observer=MessageObserver(lang='en'), model=RuntimeModel(model_id='unit'),
                      tools=[ActualTool()], prompt_templates=templates, max_steps=3, verbosity_level=0,
                      context_runtime=ManagedContextRuntime(ContextManager(), []), enable_protocol_repair_retry=strict)
    assert str(agent.run('Run actual once and report the result.')) == 'Confirmed REAL_FAILURE'
    assert calls == ['actual'] and len(requests) == 2
