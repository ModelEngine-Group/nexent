# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Naming style warnings preserve Daily identity, selection and accounting."""
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_naming import LEGACY_CATALOG, naming_issues
from generate_feature_links import expected_pages
import suite
from suite_runtime import save
from test_asset_lib import ValidationIssue, case_index, discover_documents
import validate_cases
import validate_execution
import validate_test_assets
from validation_policy import apply_blocks, report

REPO = Path(__file__).resolve().parents[4]
GOOD = "CHECK-SMOKE-D1-001"
OLD_STYLE = "CHECK-SMOKE"
BLOCKED = "CHECK-PENDING"


@pytest.fixture
def repository(tmp_path):
    tmp_path = tmp_path / "repo"
    (tmp_path / ".git").mkdir(parents=True)
    shutil.copytree(REPO / "test-e2e/infra/schemas", tmp_path / "test-e2e/infra/schemas")
    config = tmp_path / "test-e2e/infra/config"
    config.mkdir(parents=True)
    for name in ("case-naming-legacy.json", "report-ownership.yaml", "report-ownership.schema.json"):
        shutil.copyfile(REPO / "test-e2e/infra/config" / name, config / name)
    path = config / "report-ownership.yaml"
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules["feature_overrides"]["CHECK-SUITE"] = "system"
    path.write_text(yaml.safe_dump(rules), encoding="utf-8")
    feature = {"schema_version": "1.0", "module": {"id": "CHECK-MODULE", "name": "Checks"},
               "feature": {"feature_id": "CHECK-SUITE", "name": "Offline policy checks", "status": "active",
                           "description": "Check naming independently of executable proof",
                           "business_rules": [{"rule_id": "CHECK-RULE-01", "description": "Preserve execution identity"}],
                           "required_test_stages": ["D1"]}}
    path = tmp_path / "test-e2e/features/CHECK-SUITE/feature.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(feature), encoding="utf-8")
    for cid in (GOOD, OLD_STYLE, BLOCKED):
        case = {"case_id": cid, "feature_id": "CHECK-SUITE", "title": "Prove the selected contract",
                "type": "BE-UT", "priority": "P1", "status": "blocked" if cid == BLOCKED else "active",
                "automation": "automated", "objective": "Execute independent component proof", "preconditions": [],
                "test_data": {}, "steps": [{"order": 1, "action": "Check input", "expected": "Keep identity"}],
                "expected_results": ["Keep identity"], "forbidden_side_effects": ["No external writes"],
                "unit_boundary": "Offline component", "inputs": ["input"], "assertions": ["Identity is stable"]}
        folder = tmp_path / "test-e2e/cases" / cid
        folder.mkdir(parents=True)
        (folder / "case.yaml").write_text(yaml.safe_dump({"schema_version": "1.0", "stage": "D1",
                                                        "module": "CHECK-MODULE", "case": case}), encoding="utf-8")
        if cid != BLOCKED:
            (folder / "test.py").write_text("def test_proof(): pass\n", encoding="utf-8")
            (folder / "execution.yaml").write_text(yaml.safe_dump({"schema_version": "1.0", "case_id": cid,
                "implementations": [{"framework": "pytest", "file": "test.py", "selector": "test_proof"}]}), encoding="utf-8")
    path = tmp_path / "test-e2e/changes/test-fixes/CHECK-POLICY.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"schema_version": "1.0", "change": {"change_id": "CHECK-POLICY",
        "change_type": "test-fix", "title": "Offline policy", "description": "Verify stable execution identity",
        "affected_features": {"existing": ["CHECK-SUITE"], "added": [], "modified": [], "retired": []},
        "affected_cases": {"existing": [GOOD, OLD_STYLE, BLOCKED], "added": [], "modified": [], "retired": []},
        "no_case_change_reason": "Policy checks only"}}), encoding="utf-8")
    for path, content in expected_pages(tmp_path).items():
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_real_naming_checks_preserve_case_scope_and_bindings(repository):
    issues = validate_cases.validate(repository)
    assert {issue.code for issue in issues} == {"CASE_ID_FORMAT_INVALID"}
    assert {issue.case_id for issue in issues} == {OLD_STYLE, BLOCKED}
    execution_issues, registry = validate_execution.inspect(repository)
    assert execution_issues == []
    validation = report(repository, issues, registry["cases"])
    assert validation["ready"] and validation["status"] == "INCOMPLETE"
    assert not validation["blocked_cases"]
    assert all(row["severity"] == "WARNING" for row in validation["issues"])
    assert apply_blocks(registry["cases"], validation) == registry["cases"]


@pytest.mark.parametrize("phase", ["design", "implementation"])
def test_strict_gate_rejects_format_but_daily_retains_it_as_warning(repository, phase):
    strict = validate_test_assets.validate(repository, phase, False)
    daily = validate_test_assets.validate(repository, phase, False, daily=True)
    assert len(strict) == len(daily) == 2
    assert all(row.code == "CASE_ID_FORMAT_INVALID" for row in strict)
    _, registry = validate_execution.inspect(repository)
    assert report(repository, daily, registry["cases"])["ready"]


def test_cli_strict_still_exits_nonzero_and_daily_saves_warning_without_editing(repository, tmp_path):
    before = {p.relative_to(repository): p.read_bytes() for p in repository.rglob("*") if p.is_file()}
    output = tmp_path / "receipt/asset-validation.json"
    with patch.object(sys, "argv", ["validate", "--root", str(repository), "--phase", "implementation"]):
        assert validate_test_assets.main() == 1
    with patch.object(sys, "argv", ["validate", "--root", str(repository), "--daily-report", str(output)]):
        assert validate_test_assets.main() == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["ready"] and len(receipt["issues"]) == 2
    assert before == {p.relative_to(repository): p.read_bytes() for p in repository.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case_id", [None, "UNKNOWN"])
def test_unresolved_naming_scope_stays_fatal(repository, case_id):
    issue = ValidationIssue(repository, "case_id", "format", "CASE_ID_FORMAT_INVALID", case_id)
    assert not report(repository, [issue], [{"case_id": GOOD}])["ready"]


@pytest.mark.parametrize("fault", ["duplicate", "folder", "unsafe_id", "stage", "script_escape", "catalog"])
def test_structural_and_safety_failures_cannot_be_hidden_by_a_format_warning(repository, fault):
    path = repository / "test-e2e/cases" / GOOD / "case.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if fault == "duplicate":
        duplicate = repository / "test-e2e/cases/CHECK-DUPLICATE/case.yaml"
        duplicate.parent.mkdir()
        duplicate.write_text(yaml.safe_dump(document), encoding="utf-8")
    elif fault in {"folder", "unsafe_id"}:
        document["case"]["case_id"] = "OTHER-SMOKE" if fault == "folder" else "../outside"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
    elif fault == "stage":
        document["stage"] = "D9"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
    elif fault == "script_escape":
        binding = path.with_name("execution.yaml")
        value = yaml.safe_load(binding.read_text(encoding="utf-8"))
        value["implementations"][0]["file"] = "../../outside.py"
        binding.write_text(yaml.safe_dump(value), encoding="utf-8")
    else:
        (repository / LEGACY_CATALOG).write_text("{}", encoding="utf-8")
    issues = validate_test_assets.validate(repository, "implementation", False, daily=True)
    _, registry = validate_execution.inspect(repository)
    assert not report(repository, issues, registry["cases"])["ready"]


@pytest.mark.parametrize("include_declared_blocked", [True, False])
def test_offline_workers_preserve_identity_and_never_hide_coverage_gap(repository, tmp_path, include_declared_blocked):
    if not include_declared_blocked:
        folder = repository / "test-e2e/cases" / BLOCKED
        path = folder / "case.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["case"]["status"] = "active"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        source = repository / "test-e2e/cases" / GOOD
        shutil.copyfile(source / "test.py", folder / "test.py")
        binding = yaml.safe_load((source / "execution.yaml").read_text(encoding="utf-8"))
        binding["case_id"] = BLOCKED
        (folder / "execution.yaml").write_text(yaml.safe_dump(binding), encoding="utf-8")
    issues = validate_cases.validate(repository)
    _, registry = validate_execution.inspect(repository)
    validation = report(repository, issues, registry["cases"])
    workers = []

    def logged(command, cwd, env, log, timeout):
        cid = command[command.index("--case") + 1]
        workers.append(cid)
        directory = Path(command[command.index("--batch-dir") + 1])
        save(directory / "cases" / cid / "receipt.json", {"case_id": cid, "stage": "D1", "result": "PASS"})
        return 0

    home = tmp_path / "home"
    with patch.object(suite, "machine_environment", return_value={}), \
            patch.object(suite, "fingerprint", return_value={"head": "test"}), \
            patch.object(suite, "static_requirements", return_value=set()), \
            patch.object(suite, "static_inventory", return_value=[]), patch.object(suite, "logged", side_effect=logged):
        code = suite._execute(repository, home, apply_blocks(registry["cases"], validation),
                              {"hooks": {}, "case_timeout_seconds": 20}, validation_report=validation)
    assert code == 1 and set(workers) == ({GOOD, OLD_STYLE} if include_declared_blocked else {GOOD, OLD_STYLE, BLOCKED})
    batch = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((batch / "summary.json").read_text())
    assert summary["counts"] == ({"PASS": 2, "BLOCKED": 1} if include_declared_blocked else {"PASS": 3})
    assert summary["execution_complete"]
    assert summary["status"] == "FAILED" and summary["coverage_integrity"] == "INCOMPLETE"
    assert {row["case_id"] for row in json.loads((batch / "plan.json").read_text())["cases"]} == {GOOD, OLD_STYLE, BLOCKED}


def test_embedded_stage_conflict_is_not_a_pure_format_warning(repository):
    path = repository / "test-e2e/cases" / GOOD / "case.yaml"
    issues = naming_issues(repository, {GOOD: ("D2", {"title": "Keep contract consistency"}, path)})
    assert len(issues) == 1 and issues[0].location == "stage"
    assert not report(repository, issues, [{"case_id": GOOD}])["ready"]


def test_repository_format_warnings_preserve_plan_and_other_execution_findings():
    cases, semantic = case_index(discover_documents(REPO, "cases"))
    assert not semantic
    issues = naming_issues(REPO, cases)
    format_issues = [row for row in issues if row.code == "CASE_ID_FORMAT_INVALID"]
    assert all(row.case_id in cases for row in format_issues)
    execution_issues, registry = validate_execution.inspect(REPO)
    result = report(REPO, [*issues, *execution_issues], registry["cases"])
    other = report(REPO, [row for row in [*issues, *execution_issues] if row not in format_issues], registry["cases"])
    assert result["ready"] == other["ready"]
    assert result["blocked_cases"] == other["blocked_cases"]
    if not result["ready"]:
        with pytest.raises(ValueError, match="Global"):
            apply_blocks(registry["cases"], result)
        return
    selected = apply_blocks(registry["cases"], result)
    assert [(r["case_id"], r["stage"], r["status"]) for r in selected] == [
        (r["case_id"], r["stage"], r["status"]) for r in registry["cases"]]
