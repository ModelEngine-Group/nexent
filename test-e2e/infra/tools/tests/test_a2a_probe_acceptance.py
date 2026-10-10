"""A2A transport success or echoed input must not be counted as completion."""
import ast
import asyncio
from pathlib import Path
import types
import unittest

PATH = Path(__file__).resolve().parents[2] / 'automation/d4/a2a_client.py'
tree = ast.parse(PATH.read_text(encoding='utf-8'))
definitions = ast.Module(body=[node for node in tree.body if
    isinstance(node, (ast.FunctionDef, ast.ClassDef)) and
    node.name in ('ProbeFailure', 'verify_invocation') or
    isinstance(node, ast.AsyncFunctionDef) and node.name == 'run'], type_ignores=[])
namespace = {}
exec(compile(definitions, str(PATH), 'exec'), namespace)
verify = namespace['verify_invocation']


class AcceptanceTests(unittest.TestCase):
    def test_publication_configuration_does_not_require_mock(self):
        def unavailable_mock():
            self.fail('publication configuration must not construct an A2A Mock')

        services = []

        def configured_url(service):
            services.append(service)
            return 'http://northbound.example:5013'

        run_namespace = dict(namespace, A2AMock=unavailable_mock, service_url=configured_url)
        run = types.FunctionType(namespace['run'].__code__, run_namespace)
        result = asyncio.run(run(types.SimpleNamespace(command='northbound-config')))
        self.assertEqual(result, {'northbound_url': 'http://northbound.example:5013'})
        self.assertEqual(services, ['northbound'])

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
