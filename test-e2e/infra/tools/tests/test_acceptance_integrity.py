"""Acceptance references and real execution evidence cannot silently lose obligations."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from acceptance_integrity import binding_issues, contract_issues, execution_report  # noqa: E402
import run_cases  # noqa: E402
import validate_execution  # noqa: E402
import validate_test_assets  # noqa: E402
from validate_changes import traditional_ut_issues  # noqa: E402
from suite_runtime import finalize  # noqa: E402
from test_asset_lib import schema_validator  # noqa: E402


def contract():
    return {"case_id": "CHECK-01", "feature_id": "FEATURE-01", "title": "Component contract",
            "type": "BE-UT", "priority": "P1", "status": "active", "automation": "automated",
            "objective": "Validate component output", "preconditions": [], "test_data": {},
            "steps": [{"order": 1, "action": "Call component", "expected": "Correct result"}],
            "expected_results": ["Correct result"], "forbidden_side_effects": ["No write"],
            "unit_boundary": "Component", "inputs": [42], "assertions": ["Correct result"],
            "acceptance": [{"id": "AC-01", "description": "Correct result without writing",
                            "steps": [1], "expected_results": [1], "forbidden_side_effects": [1]}]}


def record(framework="pytest", names=None):
    return {"case_id": "CHECK-01", "stage": "D1", "acceptance": contract()["acceptance"],
            "contract_hash": "contract-version", "execution": {
                "implementation_hash": "script-version", "implementations": [{"framework": framework}],
                "acceptance_bindings": {"AC-01": names or ["test_component"]}}}


class AcceptanceIntegrityTests(unittest.TestCase):
    def test_obligation_metadata_validates_against_real_case_schema(self):
        repo = TOOLS.parents[2]
        document = {"schema_version": "1.0", "stage": "D1", "module": "CHECK-MODULE", "cases": [contract()]}
        validator = schema_validator(repo, "cases")
        self.assertEqual(list(validator.iter_errors(document)), [])
        document["cases"][0]["acceptance"][0]["steps"] = ["invented"]
        self.assertTrue(list(validator.iter_errors(document)))

    def test_traditional_ut_design_and_implementation_are_distinct(self):
        plan = {"decision": "add", "behaviors": ["Reject excess quota"], "reason": "Changed domain rule"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(traditional_ut_issues(root, plan, "design"), [])
            self.assertTrue(traditional_ut_issues(root, plan, "implementation"))
            path = root / "test/backend/test_quota.py"
            path.parent.mkdir(parents=True)
            path.write_text("def test_reject_excess():\n    pass\n", encoding="utf-8")
            plan["test_selectors"] = ["test/backend/test_quota.py::test_reject_excess"]
            self.assertEqual(traditional_ut_issues(root, plan, "implementation"), [])
            for bad in ("test-e2e/cases/CHECK-01/test.py::test_component", str(path.resolve()), "../outside.py"):
                plan["test_selectors"] = [bad]
                self.assertTrue(traditional_ut_issues(root, plan, "implementation"))
            self.assertTrue(traditional_ut_issues(root, {"decision": {}}, "design"))

    def test_traditional_ut_record_is_optional_for_history_and_structured_for_new_changes(self):
        empty_delta = {key: [] for key in ("existing", "added", "modified", "retired")}
        change = {"change_id": "CHANGE-01", "change_type": "requirement", "requirement_id": "REQ-01",
                  "title": "Unit change", "description": "Changed domain rule",
                  "affected_features": empty_delta, "affected_cases": empty_delta}
        document = {"schema_version": "1.0", "changes": [change]}
        validator = schema_validator(TOOLS.parents[2], "changes")
        self.assertEqual(list(validator.iter_errors(document)), [])
        change["traditional_ut"] = {"decision": "add", "behaviors": ["Reject excess quota"], "reason": "New boundary"}
        self.assertEqual(list(validator.iter_errors(document)), [])
        change["traditional_ut"]["decision"] = "skip-because-environment-is-missing"
        self.assertTrue(list(validator.iter_errors(document)))

    def test_traditional_ut_exemption_requires_rationale_and_no_selected_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {"decision": "exempt", "behaviors": [], "reason": "Documentation only"}
            self.assertEqual(traditional_ut_issues(root, plan, "implementation"), [])
            plan["test_selectors"] = ["test/backend/test_quota.py"]
            self.assertTrue(traditional_ut_issues(root, plan, "implementation"))
            plan["reason"] = ""
            self.assertTrue(traditional_ut_issues(root, plan, "design"))

    def test_legacy_contract_remains_compatible_and_unreviewed(self):
        case = contract()
        case.pop("acceptance")
        self.assertEqual(contract_issues(case), [])
        self.assertEqual(binding_issues(case, None, required=True), [])
        item = record()
        item.pop("acceptance")
        with tempfile.TemporaryDirectory() as temporary:
            result = execution_report(item, Path(temporary), "PASS")
        self.assertEqual(result["status"], "UNREVIEWED")
        self.assertEqual(result["semantic_review"], "UNREVIEWED")

    def test_complete_references_and_design_before_bindings(self):
        self.assertEqual(contract_issues(contract()), [])
        self.assertEqual(binding_issues(contract(), None, required=False), [])
        self.assertTrue(binding_issues(contract(), None, required=True))

    def test_every_step_expectation_and_forbidden_effect_requires_mapping(self):
        for key in ("steps", "expected_results", "forbidden_side_effects"):
            case = contract()
            case["acceptance"][0].pop(key)
            self.assertTrue(any(key in message for message in contract_issues(case)))

    def test_bad_references_and_duplicate_ids_are_not_complete(self):
        case = contract()
        case["acceptance"][0]["expected_results"] = [2]
        self.assertTrue(contract_issues(case))
        case = contract()
        case["acceptance"].append(deepcopy(case["acceptance"][0]))
        self.assertTrue(any("Duplicate" in message for message in contract_issues(case)))

    def test_bindings_reject_omitted_extra_empty_or_duplicate_tests(self):
        for names in ({}, {"AC-OTHER": ["test_component"]}, {"AC-01": []},
                      {"AC-01": ["test_component", "test_component"]}, {"AC-01": [{}]}):
            self.assertTrue(binding_issues(contract(), names, required=True))
        self.assertTrue(binding_issues({}, {"AC-01": ["test_component"]}, required=True))
        self.assertTrue(binding_issues({"acceptance": None}, {}, required=True))

    def junit_report(self, xml, item=None, execution_status="PASS"):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "junit.xml").write_text(xml, encoding="utf-8")
            return execution_report(item or record(), directory, execution_status)

    def test_actual_pass_is_not_semantic_certification(self):
        result = self.junit_report('<testsuite><testcase name="test_component"/></testsuite>')
        self.assertEqual(result["status"], "MAPPED_EXECUTION_PASSED")
        self.assertEqual(result["semantic_review"], "UNREVIEWED")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["contract_hash"], "contract-version")

    def test_different_test_passing_does_not_satisfy_missing_binding(self):
        result = self.junit_report('<testsuite><testcase name="test_unrelated"/></testsuite>')
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["obligations"][0]["missing_tests"], ["test_component"])

    def test_class_and_parameter_variants_include_skipped_and_failed_items(self):
        item = record(names=["TestComponent::test_component"])
        for terminal, expected in (("<skipped/>", "BLOCKED"), ("<failure/>", "FAIL")):
            result = self.junit_report(
                '<testsuite><testcase classname="cases.TestComponent" name="test_component[good]"/>'
                '<testcase classname="cases.TestComponent" name="test_component[bad]">'
                + terminal + '</testcase></testsuite>', item)
            self.assertEqual(result["status"], expected)

    def test_process_failure_never_certifies_green_junit(self):
        result = self.junit_report('<testsuite><testcase name="test_component"/></testsuite>',
                                   execution_status="AUTOMATION_ERROR")
        self.assertEqual(result["status"], "BLOCKED")

    def test_vitest_tap_and_fixed_journey_evidence(self):
        vitest = record("vitest", ["handles component error"])
        self.assertEqual(self.junit_report(
            '<testsuite><testcase name="handles component error"/></testsuite>', vitest)["passed"], 1)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            item = record("custom", ["component result"])
            (directory / "step-1.log").write_text('ok 1 - component result # SKIP missing input\n', encoding="utf-8")
            self.assertEqual(execution_report(item, directory, "BLOCKED")["status"], "BLOCKED")
            item = record("playwright", ["CHECK-01"])
            self.assertEqual(execution_report(item, directory, "FAIL")["status"], "FAIL")

    def test_binding_changes_have_distinct_evidence_fingerprints(self):
        xml = '<testsuite><testcase name="test_component"/><testcase name="test_other"/></testsuite>'
        first = self.junit_report(xml)
        second = self.junit_report(xml, record(names=["test_other"]))
        self.assertNotEqual(first["bindings_sha256"], second["bindings_sha256"])

    def test_case_local_inspection_preserves_legacy_and_gates_new_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "test-e2e/cases/CHECK-01"
            directory.mkdir(parents=True)
            case = contract()
            (directory / "case.yaml").write_text(yaml.safe_dump({"schema_version": "1.0", "stage": "D1",
                "module": "CHECK-MODULE", "case": case}), encoding="utf-8")
            (directory / "test.py").write_text('# CHECK-01\ndef test_component():\n    assert 1 == 1\n', encoding="utf-8")
            binding = {"schema_version": "1.0", "case_id": "CHECK-01", "implementations": [
                {"framework": "pytest", "file": "test.py", "selector": "CHECK-01"}]}
            path = directory / "execution.yaml"
            path.write_text(yaml.safe_dump(binding), encoding="utf-8")
            self.assertEqual(validate_execution.inspect(root, "design")[0], [])
            self.assertTrue(validate_execution.inspect(root)[0])
            binding["acceptance_bindings"] = {"AC-01": ["test_component"]}
            path.write_text(yaml.safe_dump(binding), encoding="utf-8")
            issues, registry = validate_execution.inspect(root)
            self.assertEqual(issues, [])
            self.assertEqual(registry["cases"][0]["execution"]["acceptance_bindings"], binding["acceptance_bindings"])
            # Static structure deliberately does not certify this constant assertion.
            with tempfile.TemporaryDirectory() as output:
                self.assertEqual(execution_report(registry["cases"][0], Path(output), "PASS")["status"], "INCOMPLETE")

    def test_runner_with_real_pytest_rejects_uncollected_obligation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            (root / "test-e2e").mkdir()
            (root / "test-e2e/pytest.ini").write_text('[pytest]\n', encoding="utf-8")
            (root / "test.py").write_text('def test_component():\n    assert sum([1, 2]) == 3\n', encoding="utf-8")
            item = record(names=["test_missing"])
            item["execution"]["implementations"][0]["file"] = "test.py"
            for names, expected in ((["test_missing"], "INCOMPLETE"), (["test_component"], "PASS")):
                item["execution"]["acceptance_bindings"]["AC-01"] = names
                _, result, directory = run_cases.run_one(item, root, home, dict(os.environ))
                self.assertEqual(result, expected)
                status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
                self.assertEqual(status["execution_status"], "PASS")
                self.assertEqual(status["acceptance_semantic_review"], "UNREVIEWED")
                self.assertTrue((directory / "acceptance-execution.json").is_file())

    def test_batch_report_never_describes_legacy_pass_as_reviewed_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            row = {"case_id": "CHECK-01", "stage": "D1", "result": "PASS"}
            summary = finalize(directory, [row], [row])
            self.assertEqual(summary["counts"], {"PASS": 1})
            self.assertEqual(summary["acceptance_counts"], {"UNREVIEWED": 1})
            self.assertIn("not semantic completeness", (directory / "report.md").read_text(encoding="utf-8"))

    def test_required_unknown_current_change_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(validate_test_assets.validate_features, "validate", return_value=[]), \
                    patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
                    patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
                    patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
                    patch.object(validate_test_assets.validate_execution, "inspect", return_value=([], {"cases": []})):
                issues = validate_test_assets.validate(root, "design", False, ["UNKNOWN-01"])
            self.assertTrue(any("does not exist" in item.message for item in issues))


if __name__ == "__main__":
    unittest.main()
