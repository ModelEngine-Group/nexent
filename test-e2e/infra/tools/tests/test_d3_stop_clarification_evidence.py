"""Test-side oracles reject incomplete cancellation and malformed clarification."""
from __future__ import annotations

import importlib.util
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

spec = importlib.util.spec_from_file_location('clarification_case', ROOT / 'test-e2e/cases/AGT-005/test.py')
clarification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clarification)


def card_events(**question_updates):
    question = {'question_id': 'purpose', 'title': 'Which capability is required?',
                'question_type': 'text', 'required': True, **question_updates}
    return [{'event': 'message', 'data': {'type': 'nl2a', 'content': json.dumps({
        'subtype': 'requirement_clarification', 'questions': [question],
    })}}]


class ClarificationTests(unittest.TestCase):
    def test_semantic_rewording_does_not_require_exact_missing_tool_token(self):
        clarification.assert_clarification_cards(card_events())

    def test_absent_card_is_not_accepted(self):
        with self.assertRaises(AssertionError):
            clarification.assert_clarification_cards([{'data': {'type': 'final_answer', 'content': 'OK'}}])

    def test_choice_without_options_is_not_accepted(self):
        with self.assertRaises(AssertionError):
            clarification.assert_clarification_cards(card_events(question_type='single_choice'))

    def test_saved_state_or_error_is_not_safe_clarification(self):
        for kind in ('nl2a_state', 'error'):
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                clarification.assert_clarification_cards(card_events() + [{'data': {'type': kind}}])

    def test_draft_snapshot_detects_new_resource_binding(self):
        self.assertNotEqual(clarification.draft_snapshot({'tools': []}),
                            clarification.draft_snapshot({'tools': [{'tool_id': 23}]}))

    def test_completed_degradation_requires_persisted_fields_and_no_new_binding(self):
        events = [{'data': {'type': 'nl2a_state', 'content': {
            'event': 'agent_generation_completed', 'agent_id': 23,
        }}}, {'data': {'type': 'final_answer', 'content': 'Unsupported capability omitted'}}]
        before = {'tools': []}
        after = {'tools': [], 'duty_prompt': 'A safe assistant',
                 'greeting_message': 'Hello', 'example_questions': ['What can you do?']}
        clarification.assert_safe_missing_capability(events, before, after, 23)
        for broken in ({**after, 'tools': [{'tool_id': 99}]}, {**after, 'duty_prompt': ''}):
            with self.assertRaises(AssertionError):
                clarification.assert_safe_missing_capability(events, before, broken, 23)

    def test_natural_language_completion_alone_is_not_degradation_evidence(self):
        with self.assertRaises(AssertionError):
            clarification.assert_safe_missing_capability(
                [{'data': {'type': 'final_answer', 'content': 'All done'}}], {}, {}, 23)

    def test_user_pause_requires_a_real_accessible_unbound_tool_and_unchanged_draft(self):
        resource = {'candidate': {'resource_type': 'tool', 'candidate_ref': 'tool:34'}, 'is_bound': False}
        card = {'subtype': 'installed_resource_binding', 'agent_id': 23, 'resources': [resource]}
        events = [{'data': {'type': 'nl2a', 'content': card}}]
        clarification.assert_safe_missing_capability(events, {}, {}, 23, accessible_tool_ids={34})
        with self.assertRaises(AssertionError):
            clarification.assert_safe_missing_capability(events, {}, {}, 23, accessible_tool_ids=set())
        with self.assertRaises(AssertionError):
            clarification.assert_safe_missing_capability(events, {}, {'duty_prompt': 'changed'}, 23,
                                                        accessible_tool_ids={34})
        card['resources'][0]['is_bound'] = True
        with self.assertRaises(AssertionError):
            clarification.assert_safe_missing_capability(events, {}, {}, 23, accessible_tool_ids={34})


class EvidenceTests(unittest.TestCase):
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
