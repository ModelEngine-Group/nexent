"""A2A transport success or echoed input must not be counted as completion."""
import ast
from pathlib import Path
import types
import unittest

PATH = Path(__file__).resolve().parents[2] / 'automation/d4/a2a_client.py'
tree = ast.parse(PATH.read_text(encoding='utf-8'))
definitions = ast.Module(body=[node for node in tree.body if
    isinstance(node, (ast.FunctionDef, ast.ClassDef)) and
    node.name in ('ProbeFailure', 'verify_invocation')], type_ignores=[])
namespace = {}
exec(compile(definitions, str(PATH), 'exec'), namespace)
verify = namespace['verify_invocation']


class AcceptanceTests(unittest.TestCase):
    def response(self, payload):
        return types.SimpleNamespace(status_code=200, json=lambda: payload)

    def test_completed_real_answer_passes(self):
        verify(self.response({'task': {'status': {'state': 'TASK_STATE_COMPLETED'},
            'artifacts': [{'parts': [{'text': 'result-MARKER'}]}]}}), 'MARKER')

    def test_failed_task_with_echoed_marker_is_not_success(self):
        with self.assertRaisesRegex(AssertionError, 'TASK_STATE_FAILED'):
            verify(self.response({'task': {'status': {'state': 'TASK_STATE_FAILED'},
                'history': [{'parts': [{'text': 'MARKER'}]}]}}), 'MARKER')

    def test_completed_task_input_history_does_not_satisfy_answer(self):
        with self.assertRaisesRegex(AssertionError, 'omitted'):
            verify(self.response({'task': {'status': {'state': 'TASK_STATE_COMPLETED'},
                'history': [{'parts': [{'text': 'MARKER'}]}]}}), 'MARKER')

    def test_direct_agent_message_passes(self):
        verify(self.response({'message': {'parts': [{'text': 'MARKER'}]}}), 'MARKER')

    def test_http_200_error_text_with_marker_is_not_an_answer(self):
        with self.assertRaisesRegex(AssertionError, 'error text'):
            verify(self.response({'message': {'parts': [{'text': 'Error: request MARKER failed'}]}}), 'MARKER')

    def test_product_data_parts_and_split_final_answer_pass(self):
        verify(self.response({'message': {'role': 'ROLE_AGENT', 'parts': [
            {'data': {'type': 'final_answer', 'content': 'MAR'}, 'mediaType': 'application/json'},
            {'data': {'type': 'final_answer', 'content': 'KER'}, 'mediaType': 'application/json'},
        ]}}), 'MARKER')

    def test_reasoning_and_tool_echo_are_not_answers(self):
        for event_type in ['thinking', 'tool', 'deep_thinking', 'user']:
            with self.assertRaisesRegex(AssertionError, 'omitted'):
                verify(self.response({'message': {'parts': [
                    {'data': {'type': event_type, 'content': 'MARKER'}}]}}), 'MARKER')

    def test_runtime_error_is_not_hidden_by_marker(self):
        with self.assertRaisesRegex(AssertionError, 'runtime error'):
            verify(self.response({'message': {'parts': [
                {'data': {'type': 'final_answer', 'content': 'MARKER'}},
                {'data': {'type': 'error', 'content': 'private failure'}},
            ]}}), 'MARKER')
