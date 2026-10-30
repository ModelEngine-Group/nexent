# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline Daily validation policy and execution accounting regressions."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite
import validate_changes
import validate_execution
import validate_test_assets
from suite_runtime import finalize, save
from test_asset_lib import ValidationIssue
from validation_policy import apply_blocks, evaluate, report


def records():
    return [{"case_id": case_id, "stage": "D1", "status": "active", "execution": {"test": True}}
            for case_id in ("CASE-A", "CASE-B")]


@pytest.mark.parametrize("code", ["CASE_EXECUTION_MISSING", "CASE_SCRIPT_MISSING", "CASE_SELECTOR_MISSING"])
def test_known_case_failures_block_only_the_owner_without_changing_contract(tmp_path, code):
    original = records()
    result = report(tmp_path, [ValidationIssue(tmp_path, "", "missing", code, "CASE-A")], original)
    assert result["ready"] and result["blocked_cases"] == ["CASE-A"]
    selected = apply_blocks(original, result)
    assert [r["case_id"] for r in selected] == ["CASE-A", "CASE-B"]
    assert selected[0]["execution"] is None and selected[0]["asset_blocked"]
    assert selected[1] == original[1] and original[0]["execution"]


@pytest.mark.parametrize("issue", [
    ("UNCLASSIFIED", None), ("NEW_UNKNOWN_ERROR", "CASE-A"), ("CASE_SCRIPT_MISSING", "UNKNOWN"),
    ("CASE_SCRIPT_MISSING", None), ("UT_REFERENCE_MISSING", "CASE-A"),
])
def test_unknown_global_or_unscoped_problems_fail_closed(tmp_path, issue):
    result = report(tmp_path, [ValidationIssue(tmp_path, "", "missing", *issue)], records())
    assert not result["ready"]
    with pytest.raises(ValueError, match="Global"):
        apply_blocks(records(), result)


@pytest.mark.parametrize("code", ["UT_REFERENCE_MISSING", "DERIVED_VIEW_STALE"])
def test_metadata_warning_does_not_block_cases_or_make_a_green_batch(tmp_path, code):
    validation = report(tmp_path, [ValidationIssue(tmp_path, "CHANGE", "missing", code)], records())
    assert validation["ready"] and not validation["blocked_cases"]
    save(tmp_path / "asset-validation.json", validation)
    rows = [{**record, "result": "PASS"} for record in records()]
    summary = finalize(tmp_path, records(), rows)
    assert summary["counts"] == {"PASS": 2}
    assert summary["execution_complete"] is True and summary["status"] == "FAILED"
    assert summary["coverage_integrity"] == "INCOMPLETE"
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "asset-validation.json" in text and "not a formal Case failure or a UT pass" in text


def test_missing_ut_is_typed_but_invalid_paths_remain_fatal(tmp_path):
    plan = {"decision": "reuse", "reason": "regression", "behaviors": ["restore"],
            "test_selectors": ["frontend/tests/missing.test.tsx"]}
    findings = validate_changes.traditional_ut_issues(tmp_path, plan, "implementation", typed_missing=True)
    assert len(findings) == 1 and findings[0].code == "UT_REFERENCE_MISSING"
    assert isinstance(validate_changes.traditional_ut_issues(tmp_path, plan, "implementation")[0], str)
    plan["test_selectors"] = ["../outside.py", "/absolute/file.py"]
    findings = validate_changes.traditional_ut_issues(tmp_path, plan, "implementation", typed_missing=True)
    assert findings and all(isinstance(issue, str) for issue in findings)


@pytest.mark.parametrize("mode,code", [("binding", "CASE_EXECUTION_MISSING"), ("script", "CASE_SCRIPT_MISSING"),
                                       ("selector", "CASE_SELECTOR_MISSING"), ("escape", "UNCLASSIFIED")])
def test_real_execution_inspector_emits_scoped_codes_and_preserves_every_case(tmp_path, mode, code):
    folder = tmp_path / "test-e2e/cases/CASE-A"
    folder.mkdir(parents=True)
    case = {"status": "active", "automation": "automated", "feature_id": "F-1"}
    if mode != "binding":
        (folder / "execution.yaml").write_text(
            "schema_version: '1.0'\ncase_id: CASE-A\nimplementations:\n"
            "- framework: pytest\n  file: " + ("../../outside.py" if mode == "escape" else "test.py")
            + "\n  selector: test_proof\n", encoding="utf-8")
    if mode == "selector":
        (folder / "test.py").write_text("def test_other(): pass\n", encoding="utf-8")
    with patch.object(validate_execution, "discover_documents", return_value=[]), \
            patch.object(validate_execution, "case_index", return_value=({"CASE-A": ("D1", case, folder / "case.yaml")}, [])), \
            patch.object(validate_execution, "case_contract_hash", return_value="hash"):
        issues, registry = validate_execution.inspect(tmp_path)
    assert any(issue.code == code for issue in issues)
    assert len(registry["cases"]) == 1
    classified = report(tmp_path, issues, registry["cases"])
    assert classified["ready"] is (mode != "escape")


def test_worker_keeps_unrelated_cases_executable_but_targeted_selection_stays_strict(tmp_path):
    issue = ValidationIssue(tmp_path, "", "missing", "CASE_SCRIPT_MISSING", "CASE-A")
    args = argparse.Namespace(case=["CASE-B"], change=None, stage=None, feature=None)
    with patch.object(suite, "inspect", return_value=([issue], {"cases": records()})):
        with pytest.raises(ValueError, match="binding issues"):
            suite.selection(tmp_path, args)
        assert suite.selection(tmp_path, args, worker=True) == [records()[1]]


def test_offline_batch_records_blocked_case_then_runs_unrelated_worker(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    validation = report(repo, [ValidationIssue(repo, "", "missing", "CASE_SCRIPT_MISSING", "CASE-A")], records())
    selected = apply_blocks(records(), validation)
    workers = []

    def logged(command, cwd, env, log, timeout):
        assert "worker" in command
        case_id = command[command.index("--case") + 1]
        workers.append(case_id)
        batch = Path(command[command.index("--batch-dir") + 1])
        save(batch / "cases" / case_id / "receipt.json", {"case_id": case_id, "stage": "D1", "result": "PASS"})
        return 0

    with patch.object(suite, "machine_environment", return_value={}), \
            patch.object(suite, "fingerprint", return_value={"head": "test"}), \
            patch.object(suite, "static_requirements", return_value=set()), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite, "logged", side_effect=logged):
        result = suite._execute(repo, home, selected, {"hooks": {}, "case_timeout_seconds": 20},
                                validation_report=validation)
    assert result == 1 and workers == ["CASE-B"]
    batch = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((batch / "summary.json").read_text())
    assert summary["counts"] == {"BLOCKED": 1, "PASS": 1}
    assert summary["execution_complete"] and summary["d6_complete"]
    receipt = json.loads((batch / "cases/CASE-A/receipt.json").read_text())
    assert receipt["acceptance_status"] == "INCOMPLETE"


def test_strict_validation_still_fails_and_daily_checks_derived_views_without_writing(tmp_path):
    stale = tmp_path / "test-e2e/features/F/cases.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    missing = ValidationIssue(tmp_path, "", "missing", "UT_REFERENCE_MISSING")
    with patch.object(validate_test_assets.validate_features, "validate", return_value=[missing]), \
            patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
            patch.object(validate_test_assets.ownership_catalog, "validate", return_value=[]), \
            patch.object(validate_test_assets, "discover_documents", return_value=[]), \
            patch.object(validate_test_assets.validate_execution, "inspect", return_value=([], {"cases": records()})), \
            patch.object(validate_test_assets.generate_feature_links, "expected_pages", return_value={stale: "new"}), \
            patch.object(validate_test_assets.generate_excel, "write_workbook", side_effect=lambda _root, path: path.touch()):
        assert validate_test_assets.validate(tmp_path, "implementation", False) == [missing]
        issues = validate_test_assets.validate(tmp_path, "implementation", False, daily=True)
        assert {issue.code for issue in issues} == {"UT_REFERENCE_MISSING", "DERIVED_VIEW_STALE"}
        assert stale.read_text() == "old"
        with pytest.raises(ValueError, match="must not regenerate"):
            validate_test_assets.validate(tmp_path, "implementation", True, daily=True)


def test_launcher_uses_daily_report_and_never_regenerates():
    script = (Path(__file__).resolve().parents[2] / "scripts/daily-launch.py").read_text(encoding="utf-8")
    assert '"--daily-report"' in script and '"--generate"' not in script


def test_campaign_receives_validation_and_a_disabled_case_without_rebuilding_in_children(tmp_path):
    validation = report(tmp_path, [], records())
    settings = {"hooks": {}}
    with patch("deployment_exceptions.assert_recovered"), \
            patch("deployment_exceptions.catalog", return_value={}), \
            patch("deployment_exceptions.groups", return_value={"aidp": records()}), \
            patch("validation_policy.evaluate", return_value=(validation, records())), \
            patch("deployment_exceptions.execute_campaign", return_value=1) as campaign:
        assert suite.execute(tmp_path, tmp_path, records(), settings, daily=True) == 1
    assert campaign.call_args.kwargs["validation_report"] == validation
    assert campaign.call_args.kwargs["execute_one"].keywords["validation_report"] == validation


def test_daily_refuses_a_shortened_plan_even_when_assets_are_valid(tmp_path):
    with patch("deployment_exceptions.assert_recovered"), \
            patch("validation_policy.evaluate", return_value=(report(tmp_path, [], records()), records())):
        with pytest.raises(ValueError, match="full validated registry"):
            suite.execute(tmp_path, tmp_path, records()[:1], {}, daily=True)


def test_daily_refuses_duplicate_plan_before_build(tmp_path):
    with patch("deployment_exceptions.assert_recovered"), \
            patch("validation_policy.evaluate", return_value=(report(tmp_path, [], records()), records())):
        with pytest.raises(ValueError, match="full validated registry"):
            suite.execute(tmp_path, tmp_path, records() + records()[:1], {}, daily=True)


def test_fatal_validation_cannot_start_build_or_worker(tmp_path):
    fatal = report(tmp_path, [ValidationIssue(tmp_path, "", "invalid configuration")], records())
    with patch("deployment_exceptions.assert_recovered"), \
            patch("validate_test_assets.validate", return_value=[ValidationIssue(tmp_path, "", "invalid configuration")]), \
            patch("validate_execution.inspect", return_value=([], {"cases": records()})), \
            patch.object(suite, "execute_hooks") as hooks, patch.object(suite, "logged") as commands:
        with pytest.raises(ValueError, match="Global"):
            suite.execute(tmp_path, tmp_path, records(), {}, daily=True)
    assert not fatal["ready"]
    hooks.assert_not_called()
    commands.assert_not_called()


def test_real_ut_reference_is_warning_only_in_daily_validator(tmp_path):
    change = {"traditional_ut": {"decision": "reuse", "reason": "regression", "behaviors": ["resume"],
                                 "test_selectors": ["frontend/tests/missing.test.tsx"]}}
    with patch.object(validate_test_assets.validate_features, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
            patch.object(validate_test_assets.ownership_catalog, "validate", return_value=[]), \
            patch.object(validate_test_assets, "discover_documents", return_value=[]), \
            patch.object(validate_test_assets, "change_index", return_value=({"CHANGE": change}, [])), \
            patch.object(validate_test_assets.validate_execution, "inspect", return_value=([], {"cases": records()})), \
            patch.object(validate_test_assets.generate_feature_links, "expected_pages", return_value={}), \
            patch.object(validate_test_assets.generate_excel, "write_workbook", side_effect=lambda _root, path: path.touch()):
        strict = validate_test_assets.validate(tmp_path, "implementation", False)
        daily = validate_test_assets.validate(tmp_path, "implementation", False, daily=True)
    assert len(strict) == len(daily) == 1
    assert strict[0].code == daily[0].code == "UT_REFERENCE_MISSING"
    assert report(tmp_path, daily, records())["ready"]


def test_validation_receipt_is_kept_in_publication_allowlist(tmp_path):
    import suite_publish
    save(tmp_path / "asset-validation.json", {"status": "INCOMPLETE", "issues": []})
    selected, _ = suite_publish.selected_files(tmp_path, [])
    assert [path.name for path in selected] == ["asset-validation.json"]


def test_daily_cli_saves_fatal_parser_receipt_without_echoing_untrusted_values(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "test-e2e").mkdir()
    output = tmp_path / "asset-validation.json"
    with patch.object(sys, "argv", ["validate", "--root", str(repo), "--daily-report", str(output)]), \
            patch.object(validate_test_assets, "validate", side_effect=ValueError("untrusted-secret-value")):
        assert validate_test_assets.main() == 1
    receipt = json.loads(output.read_text())
    assert receipt["ready"] is False and receipt["status"] == "INVALID"
    assert receipt["issues"][0]["severity"] == "FATAL"
    assert "untrusted-secret-value" not in output.read_text()


def test_second_execution_inspection_cannot_drop_a_new_global_failure(tmp_path):
    issue = ValidationIssue(tmp_path, "", "unsafe script path")
    with patch("validate_test_assets.validate", return_value=[]), \
            patch("validate_execution.inspect", return_value=([issue], {"cases": records()})):
        with pytest.raises(ValueError, match="Global"):
            evaluate(tmp_path)


def test_cli_second_inspection_retains_and_deduplicates_findings(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "test-e2e").mkdir()
    output = tmp_path / "asset-validation.json"
    issue = ValidationIssue(repo, "", "unsafe script path")
    with patch.object(sys, "argv", ["validate", "--root", str(repo), "--daily-report", str(output)]), \
            patch.object(validate_test_assets, "validate", return_value=[issue]), \
            patch.object(validate_test_assets.validate_execution, "inspect", return_value=([issue], {"cases": records()})):
        assert validate_test_assets.main() == 1
    receipt = json.loads(output.read_text())
    assert not receipt["ready"] and len(receipt["issues"]) == 1
