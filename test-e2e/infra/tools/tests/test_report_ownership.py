"""Routing and Git provenance are evidence, not inferred defect attribution."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_ownership import enrich, git_provenance, load_rules, route
from suite_runtime import finalize

REPO = Path(__file__).resolve().parents[4]


class OwnershipTests(unittest.TestCase):
    def test_repository_rules_and_all_user_supplied_domains(self):
        rules = load_rules(REPO)
        self.assertEqual({domain['label'] for domain in rules['domains'].values()}, {
            'Skill仓库', 'MCP仓库', 'Agent仓库', 'Nexent知识库 & AIDP知识库', '模型管理', '智能体评估',
            '系统管理整体', '记忆系统', '智能体运行', '上下文工程', '定时任务', '智能体开发配置', '沙箱', '安装部署/升级'})
        self.assertEqual(rules['domains']['sandbox']['owner'], '@杜宇骁')
        self.assertEqual(rules['domains']['task']['owner'], '@董济宝')

    def test_category_is_not_overridden_by_incidental_agent_or_mcp_words(self):
        rules = load_rules(REPO)
        record = {'case_id': 'TEST-01', 'feature_id': 'F-097', 'title': 'Agent uses MCP and knowledge'}
        result = route(record, {'description': '知识库与文件 / 知识库: models and MCP'}, rules)
        self.assertEqual(result['owner'], '@曹杰')

    def test_override_and_case_override_precedence(self):
        rules = load_rules(REPO)
        record = {'case_id': 'TEST-01', 'feature_id': 'F-046'}
        feature = {'description': '智能体配置 / Prompt生成: details'}
        self.assertEqual(route(record, feature, rules)['owner'], '@夏一辰')
        rules['case_overrides']['TEST-01'] = 'runtime'
        self.assertEqual(route(record, feature, rules)['owner'], '@潘业宏')

    def test_unknown_and_ambiguous_are_not_guessed(self):
        rules = load_rules(REPO)
        record = {'case_id': 'TEST-01', 'feature_id': 'UNKNOWN-01', 'title': 'Agent MCP API failure'}
        self.assertEqual(route(record, {}, rules)['status'], 'UNASSIGNED')
        rules['domains']['mcp']['feature_id_patterns'].append('^UNKNOWN-')
        rules['domains']['runtime']['feature_id_patterns'].append('^UNKNOWN-')
        self.assertEqual(route(record, {}, rules)['status'], 'AMBIGUOUS')

    def test_d4_a2a_and_mcp_have_separate_routing(self):
        rules = load_rules(REPO)
        for identifier, expected in [('V5-PW-A2A-DISCOVERY-01', '@潘业宏'), ('V5-PW-MCP-API-01', '@马群')]:
            result = route({'case_id': identifier[3:], 'feature_id': identifier}, {}, rules)
            self.assertEqual(result['owner'], expected)

    def test_core_agent_specific_cases_do_not_all_inherit_runtime_owner(self):
        rules = load_rules(REPO)
        for identifier, expected in [('UT-SDK-018', '@杜宇骁'), ('UT-SDK-AUTO-74430BEE8438F486', '@夏一辰'),
                                     ('UT-SDK-AUTO-E6DDFB4661E0D8B4', '@马群'), ('UT-SDK-016', '@潘业宏')]:
            result = route({'case_id': identifier, 'feature_id': 'F-171'}, {}, rules)
            self.assertEqual(result['owner'], expected)

    def test_cross_area_security_cases_remain_unassigned(self):
        rules = load_rules(REPO)
        for identifier in ['V5-SEC-06', 'V5-SEC-07']:
            self.assertEqual(route({'case_id': identifier[3:], 'feature_id': identifier}, {}, rules)['status'],
                             'UNASSIGNED')

    def test_git_uses_pinned_case_assets_not_shared_helper_or_current_head(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'user.name', 'Initial author')
            directory = repo / 'test-e2e/cases/TEST-01'
            directory.mkdir(parents=True)
            script = directory / 'test.py'
            script.write_text('first', encoding='utf-8')
            definition = directory / 'case.yaml'
            definition.write_text('first', encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'initial')
            git('config', 'user.name', 'Script author')
            script.write_text('second', encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'script change')
            pinned = git('rev-parse', 'HEAD')
            git('config', 'user.name', 'Later author')
            definition.write_text('second', encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'later definition')
            record = {'case_id': 'TEST-01', 'execution': {'implementations': [{'file': 'test-e2e/cases/TEST-01/test.py'}]}}
            result = git_provenance(repo, [record], pinned)['TEST-01']
            self.assertEqual(result['author'], 'Script author')
            self.assertEqual(result['commit'], pinned)
            self.assertFalse(result['uncommitted_changes'])
            current = git('rev-parse', 'HEAD')
            self.assertEqual(git_provenance(repo, [record], current)['TEST-01']['author'], 'Later author')
            helper = repo / 'test-e2e/infra/helper.py'
            helper.parent.mkdir(parents=True)
            helper.write_text('shared', encoding='utf-8')
            git('config', 'user.name', 'Helper author')
            git('add', '.')
            git('commit', '-qm', 'shared helper')
            result = git_provenance(repo, [record], git('rev-parse', 'HEAD'))['TEST-01']
            self.assertEqual(result['author'], 'Later author')
            self.assertFalse(result['uncommitted_changes'])
            script.write_text('uncommitted', encoding='utf-8')
            self.assertTrue(git_provenance(repo, [record], git('rev-parse', 'HEAD'))['TEST-01']['uncommitted_changes'])

    def test_unavailable_history_and_rules_leave_unknowns_without_mutating_input(self):
        record = {'case_id': 'TEST-01', 'stage': 'D1', 'feature_id': 'MISSING-01'}
        with tempfile.TemporaryDirectory() as root:
            result, warnings = enrich(Path(root), [record], 'HEAD')
        self.assertEqual(len(warnings), 2)
        self.assertEqual(result[0]['git_last_modifier']['status'], 'UNKNOWN')
        self.assertEqual(result[0]['responsibility']['status'], 'UNASSIGNED')
        self.assertNotIn('responsibility', record)

    def test_invalid_override_is_rejected(self):
        rules = load_rules(REPO)
        rules['case_overrides']['TEST-01'] = 'invented'
        with patch('report_ownership.yaml.safe_load', return_value=rules):
            with self.assertRaisesRegex(ValueError, 'unknown domain'):
                load_rules(REPO)

    def test_report_and_checkpoint_keep_two_fields_even_for_unexecuted_cases(self):
        plan = [{'case_id': 'TEST-01', 'stage': 'D2',
                 'git_last_modifier': {'author': 'Test author', 'commit': 'a' * 40},
                 'responsibility': {'status': 'ASSIGNED', 'owner': '@马群', 'domain': 'MCP仓库', 'basis': 'explicit'}}]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            summary = finalize(directory, plan, [], 'Interrupted')
            report = (directory / 'report.md').read_text(encoding='utf-8')
            row = json.loads((directory / 'checkpoints/results.jsonl').read_text(encoding='utf-8'))
        self.assertIn('Git最近修改者', report)
        self.assertIn('责任田负责人', report)
        self.assertIn('Test author (aaaaaaaaaaaa)', report)
        self.assertIn('MCP仓库 / @马群', report)
        self.assertEqual(row['responsibility']['basis'], 'explicit')
        self.assertFalse(summary['execution_complete'])
        self.assertEqual(row['result'], 'NOT_EXECUTED')


if __name__ == '__main__':
    unittest.main()
