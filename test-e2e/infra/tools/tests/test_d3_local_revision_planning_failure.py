"""Negative detection for local revisions and observed Planning failures."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))


def load_case(identifier):
    spec = importlib.util.spec_from_file_location(identifier.replace('-', '_'),
                                                ROOT / 'test-e2e/cases' / identifier / 'test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


revision = load_case('AGT-AUTO-6A6BC7594487E771')
planning = load_case('AGT-025')


class LocalRevisionTests(unittest.TestCase):
    def test_idempotent_optimization_still_requires_real_save_and_nonempty_readback(self):
        result = self.result()
        snapshot = {'duty_prompt': 'already good', 'tools': []}
        revision.assert_local_save(result, snapshot, dict(snapshot), 23, {'duty_prompt'}, require_change=False)
        with self.assertRaises(AssertionError):
            revision.assert_local_save(result, snapshot, {**snapshot, 'duty_prompt': ''}, 23,
                                       {'duty_prompt'}, require_change=False)
        with self.assertRaises(AssertionError):
            self.check(result, {'duty_prompt': 'old', 'tools': []})

    def test_duty_content_ignores_only_trailing_punctuation_not_changed_meaning(self):
        revision.assert_requested_duty('我负责为用户提供专业的数据分析并输出可视化报告。')
        with self.assertRaises(AssertionError):
            revision.assert_requested_duty('我负责为用户查询天气并输出报告。')

    def test_no_sync_action_respects_required_card_validation(self):
        optional = {'question_id': 'sync', 'question_type': 'multiple_choice', 'required': False, 'options': []}
        self.assertEqual(revision.no_sync_answers([optional])[0]['value'], [])
        required = {**optional, 'required': True, 'options': [{'option_id': 'actual-none', 'label': '不需要同步其他字段'}]}
        self.assertEqual(revision.no_sync_answers([required])[0]['value'], ['actual-none'])
        with self.assertRaises(AssertionError):
            revision.no_sync_answers([{**required, 'options': [{'option_id': 'constraint', 'label': '约束 Prompt'}]}])

    def test_required_card_allows_a_real_open_other_answer(self):
        card = {'question_id': 'sync', 'question_type': 'multiple_choice', 'required': True,
                'allow_other': True, 'options': [{'option_id': 'constraint', 'label': '约束 Prompt'}]}
        answer = revision.no_sync_answers([card])[0]
        self.assertEqual(answer['value'], [])
        self.assertEqual(answer['other_text'], '不需要同步其他字段，仅修改职责。')

    def result(self, event='agent_generation_completed'):
        return {'save_results': [{'status': 'success', 'agent_id': 23, 'created': False,
                                  'updated_fields': ['duty_prompt']}],
                'tool_names': [revision.SAVE_TOOL], 'nl2a_payloads': [], 'final_text': 'Updated duty only',
                'state_events': [{'agent_id': 23, 'event': event, 'updated_fields': ['duty_prompt']}]}

    def check(self, result, after=None):
        revision.assert_local_save(result, {'duty_prompt': 'old', 'tools': []},
                                   after or {'duty_prompt': 'new', 'tools': []}, 23, {'duty_prompt'})

    def test_both_trusted_state_markers_accept_a_real_single_field_save(self):
        for event in ('agent_generation_completed', 'agent_draft_fields_saved'):
            self.check(self.result(event))

    def test_completion_marker_without_a_tool_receipt_is_rejected(self):
        result = self.result()
        result['save_results'] = []
        with self.assertRaises(AssertionError):
            self.check(result)

    def test_extra_field_resource_change_duplicate_save_and_foreign_target_are_rejected(self):
        for mutation in ('extra_field', 'resource', 'duplicate', 'foreign'):
            result = self.result()
            after = {'duty_prompt': 'new', 'tools': []}
            if mutation == 'extra_field':
                result['save_results'][0]['updated_fields'].append('description')
            elif mutation == 'resource':
                after['tools'] = [{'tool_id': 99}]
            elif mutation == 'duplicate':
                result['save_results'].append(copy.deepcopy(result['save_results'][0]))
            else:
                result['state_events'][0]['agent_id'] = 99
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.check(result, after)


class PlanningFailureTests(unittest.TestCase):
    def fixture(self):
        return ([{'data': {'type': 'plan', 'content': {'plan_id': 'owned', 'steps': [
                    {'id': 'a'}, {'id': 'b'}, {'id': 'c'}]}}},
                 {'data': {'type': 'plan_step_update', 'content': {'step_id': 'b', 'status': 'skipped'}}},
                 {'data': {'type': 'final_answer', 'content': 'Actual failure: CONTROLLED'}}],
                [{'error': 'CONTROLLED'}])

    def test_actual_plan_skip_terminal_and_failure_receipt_are_required(self):
        events, wire = self.fixture()
        planning.assert_failed_plan(events, wire, 'CONTROLLED')

    def test_prose_simulation_without_wire_is_rejected(self):
        events, _ = self.fixture()
        with self.assertRaises(AssertionError):
            planning.assert_failed_plan(events, [], 'CONTROLLED')

    def test_foreign_step_missing_plan_no_skip_and_concealed_failure_are_rejected(self):
        for mutation in ('foreign', 'no_plan', 'no_skip', 'concealed'):
            events, wire = self.fixture()
            if mutation == 'foreign':
                events[1]['data']['content']['step_id'] = 'other'
            elif mutation == 'no_plan':
                events.pop(0)
            elif mutation == 'no_skip':
                events[1]['data']['content']['status'] = 'completed'
            else:
                events[-1]['data']['content'] = 'Everything succeeded'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                planning.assert_failed_plan(events, wire, 'CONTROLLED')


if __name__ == '__main__':
    unittest.main()
