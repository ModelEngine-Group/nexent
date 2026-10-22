# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Test-side oracles protect cancellation and sanitized stream evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))
from shared import case_evidence, stop_observation

class EvidenceTests(unittest.TestCase):
    def test_deleted_api059_has_no_formal_assets_or_shared_template_dispatch(self):
        for filename in ('case.yaml', 'test.py', 'execution.yaml', 'execution.retired.yaml'):
            self.assertFalse((ROOT / 'test-e2e/cases/API-059' / filename).exists())
        from d3.scenarios import scenario_agent_configuration_scenarios as scenarios
        self.assertNotIn('API-059', scenarios.AGENT_CONFIG_CASES)
        self.assertFalse(hasattr(scenarios, '_template_crud'))
        self.assertFalse(hasattr(scenarios, '_template_content'))
        self.assertIn('API-060', scenarios.AGENT_CONFIG_CASES)
        self.assertIn('API-066', scenarios.AGENT_CONFIG_CASES)

    def test_deleted_agt005_has_no_formal_definition_script_binding_or_dispatch(self):
        for filename in ('case.yaml', 'test.py', 'execution.yaml'):
            self.assertFalse((ROOT / 'test-e2e/cases/AGT-005' / filename).exists())
        from d3.scenarios import scenario_agent_configuration_scenarios as scenarios
        self.assertNotIn('AGT-005', scenarios.AGENT_CONFIG_CASES)

    def test_signed_url_credentials_are_removed_even_inside_serialized_content(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {'RESULT_DIR': temporary}), \
                patch.object(case_evidence, 'load_secret_env', return_value={}):
            case_evidence.write_case_evidence('signed-url', {'content': json.dumps({
                'url': 'https://fixture.invalid/file?X-Amz-Credential=private-credential&X-Amz-Signature=private-signature',
                'nested': 'https://fixture.invalid/fetch?url=https%3A%2F%2Fupstream%2Ffile%3FX-Amz-Signature%3Dencoded-signature',
            })})
            text = (Path(temporary) / 'runtime/signed-url.json').read_text(encoding='utf-8')
            for secret in ('private-credential', 'private-signature', 'encoded-signature'):
                self.assertNotIn(secret, text)

    def test_known_secret_embedded_in_content_and_sensitive_fields_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {'RESULT_DIR': temporary}), \
                patch.object(case_evidence, 'load_secret_env', return_value={'KEY': 'private-fixture-value'}):
            case_evidence.write_case_evidence('probe', {
                'content': 'private-fixture-value failed; Bearer private-session',
                'authorization': 'unconfigured-private-value', 'status': 'failed',
            })
            text = (Path(temporary) / 'runtime/probe.json').read_text(encoding='utf-8')
            self.assertNotIn('private-fixture-value', text)
            self.assertNotIn('private-session', text)
            self.assertNotIn('unconfigured-private-value', text)
            self.assertIn('failed', text)

    def test_error_depth_and_state_subtype_are_preserved(self):
        diagnostic = case_evidence.stream_diagnostics([
            {'data': {'type': 'error', 'depth': 1, 'content': 'child timeout'}},
            {'data': {'type': 'nl2a_state', 'content': '{"event":"agent_generation_completed"}'}},
        ])
        self.assertEqual(diagnostic['protocol_events'][0]['data']['depth'], 1)
        self.assertIn('agent_generation_completed', diagnostic['tail'][-1]['content'])


class StopTests(unittest.IsolatedAsyncioTestCase):
    def test_history_list_envelope_requires_the_correct_conversation(self):
        history = {'conversation_id': '23', 'message': [{'role': 'assistant', 'status': 'stopped'}]}
        self.assertEqual(stop_observation.owned_history({'data': [history]}, 23), history)
        for broken in ({'data': []}, {'data': [history, history]}, {'data': {**history, 'conversation_id': '99'}}):
            with self.assertRaises(AssertionError):
                stop_observation.owned_history(broken, 23)

    def test_persistence_count_uses_metadata_not_none_equals_none(self):
        self.assertEqual(stop_observation.conversation_total({'data': {'items': [], 'metadata': {'total': 3}}}), 3)
        for broken in ({'data': {'total': 3}}, {'data': {'metadata': {}}}, {'data': {'metadata': {'total': None}}}):
            with self.assertRaises(AssertionError):
                stop_observation.conversation_total(broken)

    def observer(self, states):
        observer = object.__new__(stop_observation.StopObservation)
        observer.read = Mock(side_effect=states)
        observer.record = Mock()
        return observer

    async def test_finished_slot_and_stable_stream_are_accepted(self):
        state = {'run_status': 'stopped', 'stream_status': 'stopped',
                 'stream_length': 5, 'last_event_id': '1-0'}
        observer = self.observer([state, dict(state)])
        with patch.object(stop_observation.asyncio, 'sleep', new_callable=AsyncMock):
            self.assertEqual(await observer.wait_stopped('owned'), state)

    async def test_acknowledgment_does_not_hide_a_running_slot(self):
        observer = self.observer([{'run_status': 'running'}])
        clock = SimpleNamespace(time=Mock(side_effect=[0, 61]))
        with patch.object(stop_observation.asyncio, 'get_running_loop', return_value=clock):
            with self.assertRaisesRegex(AssertionError, 'did not reach stopped'):
                await observer.wait_stopped('owned')

    async def test_growth_after_stop_is_rejected(self):
        before = {'run_status': 'stopped', 'stream_length': 5}
        observer = self.observer([before, {**before, 'stream_length': 6}])
        with patch.object(stop_observation.asyncio, 'sleep', new_callable=AsyncMock):
            with self.assertRaisesRegex(AssertionError, 'continued emitting'):
                await observer.wait_stopped('owned')

    def test_optional_already_stopped_flag_does_not_define_acknowledgment(self):
        for body in ({'status': 'success', 'message': 'accepted'},
                     {'status': 'success', 'message': 'no running tasks', 'already_stopped': True}):
            stop_observation.assert_stop_ack(body)
        with self.assertRaises(AssertionError):
            stop_observation.assert_stop_ack({'status': 'failed', 'message': 'failure'})

    def test_mismatched_runtime_endpoint_blocks_before_connection(self):
        identity = SimpleNamespace(user_id='owned')
        runtime = {'Config': {'Env': ['REDIS_URL=redis://other/0']}}
        config = {'Config': {'Env': ['REDIS_URL=redis://configured/0']}}
        with patch.object(stop_observation, '_inspect', side_effect=[runtime, config]), \
                patch.object(stop_observation.redis, 'from_url') as connect:
            with self.assertRaises(stop_observation.AssetDependencyError):
                stop_observation.StopObservation(identity, 'AGT-018')
            connect.assert_not_called()


class InterruptedEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_phase_diagnostics_survive_timeout_without_treating_fragments_as_tokens(self):
        class BrokenResponse:
            async def aiter_lines(self):
                for frame in ({'type': 'step_count', 'content': '1'},
                              {'type': 'model_attempt_control', 'phase': 'begin'},
                              {'type': 'model_output_deep_thinking', 'content': 'abc'},
                              {'type': 'model_output_deep_thinking', 'content': 'def'},
                              {'type': 'parse', 'content': 'private-model-action'}):
                    yield 'data: ' + json.dumps(frame)
                    yield ''
                raise TimeoutError('controlled interruption')
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {'RESULT_DIR': temporary}), \
                patch.object(case_evidence, 'load_secret_env', return_value={}):
            with self.assertRaises(TimeoutError):
                await case_evidence.read_sse_with_evidence(BrokenResponse(), 'timed')
            saved = json.loads((Path(temporary) / 'runtime/timed.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['types']['model_output_deep_thinking'], 2)
        self.assertEqual(saved['content_characters']['model_output_deep_thinking'], 6)
        self.assertEqual([m['type'] for m in saved['milestones']],
                         ['step_count', 'model_attempt_control', 'parse'])
        self.assertEqual(saved['milestones'][1]['phase'], 'begin')
        self.assertNotIn('private-model-action', json.dumps(saved['milestones']))
        self.assertGreaterEqual(saved['event_timings']['parse']['first_seconds'],
                                saved['event_timings']['step_count']['first_seconds'])

    async def test_timeout_preserves_root_error_and_does_not_return_success(self):
        class BrokenResponse:
            async def aiter_lines(self):
                yield 'data: {"type":"error","depth":0,"content":"private-fixture-value timeout"}'
                yield ''
                raise TimeoutError('controlled interruption')

        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {'RESULT_DIR': temporary}), \
                patch.object(case_evidence, 'load_secret_env', return_value={'KEY': 'private-fixture-value'}):
            with self.assertRaises(TimeoutError):
                await case_evidence.read_sse_with_evidence(BrokenResponse(), 'interrupted')
            text = (Path(temporary) / 'runtime/interrupted.json').read_text(encoding='utf-8')
            saved = json.loads(text)
            self.assertEqual(saved['ending'], 'TimeoutError')
            self.assertEqual(saved['protocol_events'][0]['depth'], 0)
            self.assertNotIn('private-fixture-value', text)


if __name__ == '__main__':
    unittest.main()
