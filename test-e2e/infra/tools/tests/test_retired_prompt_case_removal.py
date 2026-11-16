# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Protect the explicit deletion boundary without removing active generation proof."""
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[4]
REMOVED = {'AGT-006', 'AGT-007', 'AGT-008'}


def test_retired_prompt_case_contracts_scripts_and_bindings_are_absent():
    for case_id in REMOVED:
        directory = REPO / 'test-e2e/cases' / case_id
        for filename in ['case.yaml', 'test.py', 'execution.yaml', 'execution.retired.yaml']:
            assert not (directory / filename).exists(), f'Removed Case asset returned: {case_id}/{filename}'


def test_change_records_have_no_dangling_structured_case_references():
    for path in (REPO / 'test-e2e/changes').rglob('*.yaml'):
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        changes = document.get('changes', [document.get('change', {})])
        for change in changes:
            for case_ids in change.get('affected_cases', {}).values():
                assert not REMOVED.intersection(case_ids), str(path)


def test_retired_feature_has_no_stage_requirement_and_current_generation_is_retained():
    historical = yaml.safe_load((REPO / 'test-e2e/features/F-046/feature.yaml').read_text(encoding='utf-8'))['feature']
    current = yaml.safe_load((REPO / 'test-e2e/features/F-045/feature.yaml').read_text(encoding='utf-8'))['feature']
    assert historical['status'] == 'retired'
    assert historical['required_test_stages'] == []
    assert current['status'] == 'active'
    for case_id in ['AGT-009', 'AGT-010', 'AGT-011', 'AGT-012', 'NL2AGENT-PROTOCOL-D4-001']:
        directory = REPO / 'test-e2e/cases' / case_id
        assert (directory / 'case.yaml').is_file()
        assert (directory / 'execution.yaml').is_file()
