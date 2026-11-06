# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Current asset readiness repairs retain declared proof boundaries."""
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ownership_catalog
from report_ownership import load_rules
from validate_changes import traditional_ut_issues

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def current_routing():
    _, _, features, cases = ownership_catalog.catalog(REPO)
    return features, cases, load_rules(REPO)


@pytest.mark.parametrize("feature_id,domain", [
    ("AIDP-RETRIEVAL", "knowledge"), ("AUTH-LOCAL", "system"),
    ("F-003", "system"), ("SYS-AGENT-LIFECYCLE", "system"),
])
def test_features_use_existing_functional_domains(current_routing, feature_id, domain):
    features, _, rules = current_routing
    expected = rules["domains"][domain]
    route = features[feature_id]
    assert route["status"] == "ASSIGNED"
    assert (route["owner"], route["domain"]) == (expected["owner"], expected["label"])


@pytest.mark.parametrize("case_id,domain", [
    ("AIDP-RET-CONFIG-API-D2-001", "knowledge"), ("AIDP-RET-JOURNEY-D4-001", "knowledge"),
    ("AIDP-RET-MIGRATION-D5-001", "knowledge"), ("AIDP-RET-PROTOCOL-D2-001", "knowledge"),
    ("AIDP-RET-REAL-D3-001", "knowledge"), ("AIDP-RET-RUNTIME-D3-001", "knowledge"),
    ("API-005", "system"), ("API-006", "system"),
    ("AUTH-LOCAL-D2-001", "system"), ("AUTH-LOCAL-D5-001", "system"),
    ("SYS-AGENT-D5-001", "system"),
])
def test_cases_inherit_their_feature_contact_without_contract_edits(current_routing, case_id, domain):
    _, cases, rules = current_routing
    expected = rules["domains"][domain]
    route = cases[case_id]
    assert route["status"] == "ASSIGNED"
    assert (route["owner"], route["domain"]) == (expected["owner"], expected["label"])
    assert route["basis"] == "Feature override: " + route["feature_id"]


def test_cpu_change_references_current_ut_without_reviving_removed_deployment_suite():
    path = REPO / "test-e2e/changes/requirements/CPU-DEFAULT-UV-20261026.yaml"
    plan = yaml.safe_load(path.read_text(encoding="utf-8"))["change"]["traditional_ut"]
    assert plan["decision"] == "strengthen" and plan["behaviors"]
    assert "test/backend/deploy/test_k8s_env_injection.py" not in plan["test_selectors"]
    assert traditional_ut_issues(REPO, plan, "implementation", typed_missing=True) == []
    assert len(plan["test_selectors"]) == 6


def test_protocol_declares_self_owned_http_fixture_without_shared_factories():
    path = REPO / "test-e2e/cases/AIDP-RET-PROTOCOL-D2-001/execution.yaml"
    binding = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert binding["preparation"] == {"families": [], "anchors": False, "special_assets": False, "d4_groups": []}
    assert not binding.get("required_assets") and not binding.get("required_mock_services")
    assert binding["acceptance_bindings"]["AC-01"] == [
        "test_wire_channels_and_sources", "test_wire_retry_errors_and_no_invalid_http"]
