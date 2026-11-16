# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Responsibility gaps must not prevent independent Daily execution."""
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ownership_catalog
import suite
import validate_test_assets
from suite_runtime import save
from test_asset_lib import ValidationIssue
from validation_policy import apply_blocks, report

REPO = Path(__file__).resolve().parents[4]
OPS_CASES = ("OPS-BOOTSTRAP-D1-001", "OPS-BOOTSTRAP-D5-001")


@pytest.fixture
def unmapped_repo(tmp_path):
    """Reproduce the assets merged without the new central routing entry."""
    config = tmp_path / "test-e2e/infra/config"
    config.mkdir(parents=True)
    for name in ("report-ownership.yaml", "report-ownership.schema.json"):
        shutil.copyfile(REPO / "test-e2e/infra/config" / name, config / name)
    rules = yaml.safe_load((config / "report-ownership.yaml").read_text(encoding="utf-8"))
    rules["feature_overrides"].pop("OPS-BOOTSTRAP", None)
    (config / "report-ownership.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")
    for kind, identifiers in (("features", ("OPS-BOOTSTRAP",)), ("cases", OPS_CASES)):
        for identifier in identifiers:
            target = tmp_path / "test-e2e" / kind / identifier
            target.mkdir(parents=True)
            filename = "feature.yaml" if kind == "features" else "case.yaml"
            shutil.copyfile(REPO / "test-e2e" / kind / identifier / filename, target / filename)
    return tmp_path


def records():
    return [{"case_id": cid, "feature_id": "OPS-BOOTSTRAP" if cid in OPS_CASES else "OTHER",
             "stage": "D5" if "D5" in cid else "D1", "status": "active", "execution": {"test": True}}
            for cid in (*OPS_CASES, "OTHER-SMOKE-D1-001")]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_real_catalog_emits_typed_warnings_and_preserves_all_workers(unmapped_repo, ambiguous):
    if ambiguous:
        path = unmapped_repo / "test-e2e/infra/config/report-ownership.yaml"
        rules = yaml.safe_load(path.read_text(encoding="utf-8"))
        for domain in ("system", "deployment"):
            rules["domains"][domain]["feature_id_patterns"].append("^OPS-BOOTSTRAP$")
        path.write_text(yaml.safe_dump(rules), encoding="utf-8")
    _, _, features, cases = ownership_catalog.catalog(unmapped_repo)
    expected = "AMBIGUOUS" if ambiguous else "UNASSIGNED"
    assert features["OPS-BOOTSTRAP"]["status"] == expected
    assert all(cases[cid]["status"] == expected for cid in OPS_CASES)
    issues = ownership_catalog.validate(unmapped_repo)
    assert len(issues) == 3
    assert {i.code for i in issues} == {"FEATURE_RESPONSIBILITY_UNRESOLVED", "CASE_RESPONSIBILITY_UNRESOLVED"}
    assert {i.case_id for i in issues if i.code == "CASE_RESPONSIBILITY_UNRESOLVED"} == set(OPS_CASES)
    original = records()
    result = report(unmapped_repo, issues, original)
    assert result["ready"] and result["status"] == "INCOMPLETE"
    assert not result["blocked_cases"]
    assert all(i["severity"] == "WARNING" for i in result["issues"])
    assert apply_blocks(original, result) == original


def test_unmapped_planned_feature_without_cases_is_a_daily_warning(unmapped_repo):
    shutil.rmtree(unmapped_repo / "test-e2e/cases")
    path = unmapped_repo / "test-e2e/features/OPS-BOOTSTRAP/feature.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["feature"]["status"] = "planned"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    issues = ownership_catalog.validate(unmapped_repo)
    assert len(issues) == 1 and issues[0].code == "FEATURE_RESPONSIBILITY_UNRESOLVED"
    assert report(unmapped_repo, issues, [])["ready"]


@pytest.mark.parametrize("case_id", [None, "UNKNOWN"])
def test_unknown_case_scope_cannot_be_downgraded(tmp_path, case_id):
    issue = ValidationIssue(tmp_path, "responsibility", "unresolved", "CASE_RESPONSIBILITY_UNRESOLVED", case_id)
    result = report(tmp_path, [issue], records())
    assert not result["ready"] and result["issues"][0]["severity"] == "FATAL"


@pytest.mark.parametrize("problem", ["yaml", "regex", "domain", "placeholder", "missing"])
def test_invalid_shared_routing_configuration_remains_fatal(unmapped_repo, problem):
    path = unmapped_repo / "test-e2e/infra/config/report-ownership.yaml"
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    if problem == "regex":
        rules["domains"]["system"]["feature_id_patterns"].append("[")
    elif problem == "domain":
        rules["feature_overrides"]["OPS-BOOTSTRAP"] = "unknown-domain"
    elif problem == "placeholder":
        rules["domains"]["system"]["owner"] = "@TODO"
    path.write_text("domains: [" if problem == "yaml" else yaml.safe_dump(rules), encoding="utf-8")
    if problem == "missing":
        path.unlink()
    issues = ownership_catalog.validate(unmapped_repo)
    assert len(issues) == 1
    result = report(unmapped_repo, issues, records())
    assert not result["ready"] and result["issues"][0]["severity"] == "FATAL"
    with pytest.raises(ValueError, match="Global"):
        apply_blocks(records(), result)


@pytest.mark.parametrize("phase", ["design", "implementation"])
def test_strict_gate_rejects_same_gap_that_daily_reports_without_writing(unmapped_repo, phase):
    with patch.object(validate_test_assets.validate_features, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_execution, "inspect", return_value=([], {"cases": records()})), \
            patch.object(validate_test_assets.generate_feature_links, "expected_pages", return_value={}), \
            patch.object(validate_test_assets.generate_excel, "write_workbook", side_effect=lambda _root, path: path.touch()):
        strict = validate_test_assets.validate(unmapped_repo, phase, False)
        daily = validate_test_assets.validate(unmapped_repo, phase, False, daily=True)
    assert len(strict) == len(daily) == 3
    assert report(unmapped_repo, daily, records())["ready"]
    assert not (unmapped_repo / "test-e2e/infra/generated").exists()


def test_offline_daily_executes_unassigned_and_unrelated_cases_but_cannot_be_green(unmapped_repo, tmp_path):
    validation = report(unmapped_repo, ownership_catalog.validate(unmapped_repo), records())
    home = tmp_path / "home"
    workers = []

    def logged(command, cwd, env, log, timeout):
        cid = command[command.index("--case") + 1]
        workers.append(cid)
        batch = Path(command[command.index("--batch-dir") + 1])
        save(batch / "cases" / cid / "receipt.json", {"case_id": cid, "result": "PASS"})
        return 0

    with patch.object(suite, "machine_environment", return_value={}), \
            patch.object(suite, "fingerprint", return_value={"head": "test"}), \
            patch.object(suite, "static_requirements", return_value=set()), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite, "logged", side_effect=logged):
        code = suite._execute(unmapped_repo, home, apply_blocks(records(), validation),
                              {"hooks": {}, "case_timeout_seconds": 20}, validation_report=validation)
    assert code == 1 and set(workers) == {r["case_id"] for r in records()}
    batch = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((batch / "summary.json").read_text())
    assert summary["counts"] == {"PASS": 3} and summary["execution_complete"] and summary["d6_complete"]
    assert summary["status"] == "FAILED" and summary["coverage_integrity"] == "INCOMPLETE"
    rows = [json.loads(line) for line in (batch / "checkpoints/results.jsonl").read_text().splitlines()]
    assert all(row["responsibility"]["status"] == "UNASSIGNED" for row in rows if row["case_id"] in OPS_CASES)


def test_ops_feature_and_both_cases_inherit_existing_system_domain():
    _, _, features, cases = ownership_catalog.catalog(REPO)
    rules = ownership_catalog.load_rules(REPO)
    expected = rules["domains"]["system"]
    for route in (features["OPS-BOOTSTRAP"], *(cases[cid] for cid in OPS_CASES)):
        assert route["status"] == "ASSIGNED"
        assert route["domain"] == expected["label"] and route["owner"] == expected["owner"]
        assert route["basis"] == "Feature override: OPS-BOOTSTRAP"
