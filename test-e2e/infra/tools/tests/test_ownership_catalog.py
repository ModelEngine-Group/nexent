# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Responsibility coverage is checked before execution, including new Features."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ownership_catalog as catalog
from report_ownership import load_rules, route
import validate_test_assets

REPO = Path(__file__).resolve().parents[4]


class CatalogTests(unittest.TestCase):
    def test_repository_has_unique_feature_and_case_routes(self):
        self.assertEqual(catalog.validate(REPO), [])
        features, cases, feature_routes, case_routes = catalog.catalog(REPO)
        self.assertGreater(len(features), 300)
        self.assertGreater(len(cases), 700)
        self.assertTrue(all(feature_routes[f]['status'] == 'ASSIGNED' for f, v in features.items()
                            if v.get('status') in {'active', 'planned'}))
        self.assertTrue(all(case_routes[c]['status'] == 'ASSIGNED' for c, (_, v, _) in cases.items()
                            if v.get('status') != 'retired'))

    def test_new_feature_without_cases_must_be_assigned(self):
        with patch.object(catalog, 'catalog', return_value=({'NEW': {'status': 'planned'}}, {},
                           {'NEW': {'status': 'UNASSIGNED'}}, {})):
            self.assertEqual(len(catalog.validate(REPO)), 1)

    def test_both_unified_phases_reject_unassigned_planned_feature_without_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'test-e2e/infra/config'
            config.mkdir(parents=True)
            for filename in ('report-ownership.yaml', 'report-ownership.schema.json'):
                shutil.copyfile(REPO / 'test-e2e/infra/config' / filename, config / filename)
            shutil.copytree(REPO / 'test-e2e/infra/schemas', root / 'test-e2e/infra/schemas')
            document = yaml.safe_load((REPO / 'test-e2e/features/F-173/feature.yaml').read_text(encoding='utf-8'))
            document['feature'].update(feature_id='NEW-CAPABILITY', status='planned', description='New unmapped capability')
            path = root / 'test-e2e/features/NEW-CAPABILITY/feature.yaml'
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump(document), encoding='utf-8')
            for phase in ('design', 'implementation'):
                with self.subTest(phase=phase):
                    issues = validate_test_assets.validate(root, phase, False)
                    self.assertTrue(any(issue.path == path and issue.location == 'responsibility' for issue in issues))

    def test_ambiguous_nonretired_case_is_rejected(self):
        with patch.object(catalog, 'catalog', return_value=({},
                           {'C': ('D1', {'status': 'active'}, REPO / 'case.yaml')}, {},
                           {'C': {'status': 'AMBIGUOUS'}})):
            self.assertEqual(len(catalog.validate(REPO)), 1)

    def test_retired_assets_do_not_require_new_assignment(self):
        with patch.object(catalog, 'catalog', return_value=({'F': {'status': 'retired'}},
                           {'C': ('D1', {'status': 'retired'}, REPO / 'case.yaml')},
                           {'F': {'status': 'UNASSIGNED'}}, {'C': {'status': 'UNASSIGNED'}})):
            self.assertEqual(catalog.validate(REPO), [])

    def test_configuration_error_is_a_validation_issue(self):
        with patch.object(catalog, 'catalog', side_effect=ValueError('invalid')):
            self.assertIn('invalid', catalog.validate(REPO)[0].message)

    def test_placeholder_contact_is_invalid(self):
        for owner in ('@未分配', '@ 未分配 ', '  @TODO ', '@', '   ', 'UNKNOWN'):
            with self.subTest(owner=owner):
                rules = load_rules(REPO)
                rules['domains']['runtime']['owner'] = owner
                with patch('report_ownership.yaml.safe_load', return_value=rules):
                    with self.assertRaises(ValueError):
                        load_rules(REPO)

    def test_central_contact_change_propagates_without_case_edit(self):
        rules = load_rules(REPO)
        record = {'case_id': 'C-NEW', 'feature_id': 'CHAT-SIDEBAR'}
        first = route(record, {}, rules)
        rules['domains']['runtime']['owner'] = '@Replacement'
        self.assertNotEqual(first['owner'], route(record, {}, rules)['owner'])
        self.assertEqual(route(record, {}, rules)['owner'], '@Replacement')

    def test_export_is_versioned_metadata_without_execution_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'routing.json'
            result = catalog.export_current(REPO, output)
            self.assertEqual(result['payload_sha256'], hashlib.sha256(catalog.canonical(result['routing'])).hexdigest())
            self.assertEqual(len(result['source']['head']), 40)
            self.assertIs(type(result['source']['uncommitted']), bool)
            self.assertNotIn(str(REPO), output.read_text(encoding='utf-8'))
            self.assertNotIn('result', result['routing']['cases'][next(iter(result['routing']['cases']))])

    def test_export_inside_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            catalog.export_current(REPO, REPO / 'current-ownership.json')

    def test_export_marks_uncommitted_routing_code_and_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'routing.json'
            with patch.object(catalog.subprocess, 'check_output',
                              side_effect=['a' * 40, ' M test-e2e/infra/tools/report_ownership.py']) as git:
                result = catalog.export_current(REPO, output)
            self.assertTrue(result['source']['uncommitted'])
            paths = git.call_args_list[1].args[0]
            self.assertIn('test-e2e/infra/tools/report_ownership.py', paths)
            self.assertIn('test-e2e/infra/config/report-ownership.schema.json', paths)
