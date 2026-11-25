# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime capture converts supported SDK values without arbitrary object repr."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

import pytest
from nexent.monitor.local_content import safe_local_content, set_local_span_content
from smolagents import Tool


class Lookup(Tool):
    name = 'lookup'
    description = 'Controlled tool'
    inputs: ClassVar[dict] = {'query': {'type': 'string', 'description': 'The query'}}
    output_type = 'string'

    def forward(self, query: str) -> str:
        raise AssertionError('Capture must never execute tools')


def test_local_tool_objects_are_safe_references_without_executing_or_serializing_services():
    tool = Lookup()
    tool.private_client = object()
    tool.api_key = 'private-key'
    text = safe_local_content({'tasks': [(tool, {'query': 'question', 'password': 'private'})]})
    value = json.loads(text)['tasks'][0]
    assert value[0] == {'type': 'tool_reference', 'name': 'lookup',
                        'implementation': f'{Lookup.__module__}.{Lookup.__qualname__}'}
    assert value[1] == {'query': 'question'}
    assert 'private' not in text and 'object at' not in text


def test_local_runtime_dto_preserves_enum_and_dataclass_fields_but_omits_raw_transport():
    class Role(str, Enum):
        USER = 'user'

    @dataclass
    class Message:
        role: Role
        content: str
        raw: object

    text = safe_local_content({'messages': [Message(Role.USER, '完整上下文', object())]})
    assert json.loads(text) == {'messages': [{'role': 'user', 'content': '完整上下文'}]}


def test_function_references_do_not_capture_defaults_or_closures():
    credential = 'sensitive-value'

    def execute(value=credential):
        raise AssertionError('Capture must never execute callables')

    value = json.loads(safe_local_content({'execute': execute}))['execute']
    assert value == {'type': 'callable_reference', 'name': 'execute',
                     'implementation': f'{execute.__module__}.{execute.__qualname__}'}
    assert credential not in json.dumps(value)


@pytest.mark.parametrize('value', [object(), {1: 'value'}])
def test_unsupported_runtime_objects_still_fail_closed(value):
    with pytest.raises(ValueError):
        safe_local_content(value)


@pytest.mark.parametrize('body', [
    '  多行文本\n第二行\n', '  { "value": [1, 2] }\n', '  "text"\n', '  123  ', '{"a":1,"a":2}',
])
def test_execution_body_preserves_safe_text_exactly(body):
    assert safe_local_content(body, redact_json_strings=True) == body


def test_execution_body_redacts_encoded_objects_inside_carriers():
    inner = json.dumps({'password': 'secret', 'link': 'https://example.test/?token=sensitive&lang=en'})
    data = {'result': json.dumps([{'text': inner}])}
    safe = json.loads(safe_local_content(data, redact_json_strings=True))
    text = json.loads(safe['result'])[0]['text']
    assert json.loads(text) == {'link': 'https://example.test/?token=REDACTED_CREDENTIAL&lang=en'}
    assert json.loads(json.loads(data['result'])[0]['text'])['password'] == 'secret'


def test_execution_body_omits_credentials_in_shadowed_json_fields():
    body = '{"a":{"password":"secret"},"a":"answer"}'
    assert json.loads(safe_local_content(body, redact_json_strings=True)) == {'a': 'answer'}
    assert 'secret' not in safe_local_content(body, redact_json_strings=True)


def test_failed_body_capture_only_marks_local_gap(mocker):
    span = mocker.Mock()
    set_local_span_content(span, 'output', object())
    span.set_attribute.assert_not_called()
    span.set_attributes.assert_called_once_with({
        'nexent.local.nexent.trajectory.gap': True,
        'nexent.local.nexent.availability.output': 'serialization_failed',
    })
