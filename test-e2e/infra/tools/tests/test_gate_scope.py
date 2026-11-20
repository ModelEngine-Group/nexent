# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A local prerequisite or declaration failure must not cancel independent Cases."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import pytest
import yaml

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
import deployment_exceptions as modes
import suite
import validate_execution
import validate_test_assets
from local_preflight import static_config_problems
from suite_runtime import fingerprint, save
from validation_policy import report, apply_blocks


@pytest.fixture
def case_repo(tmp_path):
    case_id = "AGENT-LIST-D1-001"
    target = tmp_path / "test-e2e/cases" / case_id
    shutil.copytree(REPO / "test-e2e/cases" / case_id, target)
    return tmp_path, target, case_id


@pytest.mark.parametrize("field,value", [("timeout_seconds", 0), ("required_mock_services", ["unknown-service"]),
                                         ("preparation", {"families": "invalid"})])
def test_invalid_case_declaration_is_scoped(case_repo, field, value):
    root, target, case_id = case_repo
    schema = root / "test-e2e/infra/schemas"
    schema.mkdir(parents=True)
    shutil.copyfile(REPO / "test-e2e/infra/schemas/preparation.schema.json", schema / "preparation.schema.json")
    path = target / "execution.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    issues, registry = validate_execution.inspect(root)
    validation = report(root, issues, registry["cases"])
    assert validation["ready"] and validation["blocked_cases"] == [case_id]
    assert apply_blocks(registry["cases"], validation)[0]["asset_blocked"]


def test_daily_does_not_reparse_blocked_execution_via_excel(case_repo):
    root, target, case_id = case_repo
    (target / "execution.yaml").write_text("invalid: [", encoding="utf-8")
    with patch.object(validate_test_assets.validate_features, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
            patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
            patch.object(validate_test_assets.ownership_catalog, "validate", return_value=[]), \
            patch.object(validate_test_assets.generate_feature_links, "expected_pages", return_value={}), \
            patch.object(validate_test_assets.generate_excel, "write_workbook", side_effect=AssertionError("No raw reparse")):
        registry = {}
        issues = validate_test_assets.validate(root, "implementation", False, daily=True, registry_out=registry)
        validation = report(root, issues, registry["cases"])
        assert validation["ready"] and validation["blocked_cases"] == [case_id]
        assert any(issue.code == "DERIVED_VIEW_STALE" for issue in issues)
        assert validate_test_assets.validate(root, "implementation", False)[0].code == "CASE_EXECUTION_INVALID"


def test_unsafe_case_path_remains_fatal(case_repo):
    root, target, _ = case_repo
    path = target / "execution.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["implementations"][0]["file"] = "../../outside.py"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    issues, registry = validate_execution.inspect(root)
    assert not report(root, issues, registry["cases"])["ready"]


def test_worker_checks_only_requested_case_not_unrelated_broken_yaml(case_repo):
    root, _, case_id = case_repo
    broken = root / "test-e2e/cases/UNRELATED/case.yaml"
    broken.parent.mkdir()
    broken.write_text("invalid: [", encoding="utf-8")
    args = argparse.Namespace(case=[case_id], change=None, stage=None, feature=None)
    assert [row["case_id"] for row in suite.selection(root, args, worker=True)] == [case_id]
    with pytest.raises(yaml.YAMLError):
        validate_execution.inspect(root)


def test_legacy_recovery_case_reference_cannot_block_campaign(tmp_path):
    config = tmp_path / "test-e2e/infra/config"
    config.mkdir(parents=True)
    shutil.copyfile(REPO / (modes.CATALOG.removesuffix(".yaml") + ".schema.json"),
                    config / "deployment-exceptions.schema.json")
    data = yaml.safe_load((REPO / modes.CATALOG).read_text(encoding="utf-8"))
    records = [{"case_id": case_id} for case_id in data["cases"]]
    for legacy in (None, [], ["REMOVED-RECOVERY-CASE"]):
        data.pop("recovery_cases", None)
        if legacy is not None:
            data["recovery_cases"] = legacy
        (tmp_path / modes.CATALOG).write_text(yaml.safe_dump(data), encoding="utf-8")
        assert modes.catalog(tmp_path, records)["cases"] == data["cases"]


def test_common_config_check_ignores_unused_business_profiles(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "daily.env").write_text("KEY=value\n")
    secret = config / "secrets.env"
    secret.write_text("KEY=value\n")
    secret.chmod(0o600)
    (config / "environment.yaml").write_text(yaml.safe_dump({"base_url": "http://localhost:3000", "services": {
        name: {"url": "http://localhost:8000"} for name in ("config", "runtime", "northbound", "data_process")}}))
    rows = [{"stage": "D2", "status": "active", "execution": {"preparation": {"families": []}}}]
    assert static_config_problems(tmp_path, rows, repo=REPO, common_only=True) == []
    assert any("models.yaml" in issue for issue in static_config_problems(tmp_path, rows, repo=REPO))
    (config / "environment.yaml").write_text("base_url: invalid\n")
    assert static_config_problems(tmp_path, rows, repo=REPO, common_only=True)


def test_runtime_check_is_reused_only_for_cases_using_that_framework(tmp_path):
    rows = [{"case_id": case_id, "status": "active", "execution": {
        "implementations": [{"framework": framework}]}}
        for case_id, framework in (("A", "vitest"), ("B", "vitest"), ("C", "pytest"), ("D", "custom"))]
    with patch.object(suite, "node_runtime_problems", return_value=["unusable jsdom"]) as probe:
        assert suite.runtime_blocks(REPO, tmp_path, rows) == {"A": ["unusable jsdom"], "B": ["unusable jsdom"]}
    probe.assert_called_once()


@pytest.mark.parametrize("full", [False, True])
def test_deploy_doctor_checks_common_environment_unless_full_diagnostics_requested(tmp_path, capsys, full):
    repo, home = tmp_path / "repo", tmp_path / "home"
    with patch.object(suite, "repository_root", return_value=repo), \
            patch.object(suite, "config", return_value={}), \
            patch.object(suite, "selection", return_value=[]), \
            patch.object(suite, "doctor", return_value=[]) as doctor:
        assert suite.main(["doctor", "--test-home", str(home), "--live", *(["--full"] if full else [])]) == 0
    doctor.assert_called_once_with(repo, home, [], live=True, common_only=not full)
    assert json.loads(capsys.readouterr().out)["ready"]


def test_deploy_doctor_does_not_reject_a_blocked_case_during_selection(case_repo, capsys):
    repo, target, _ = case_repo
    (target / "execution.yaml").write_text("invalid: [", encoding="utf-8")
    home = repo.parent / (repo.name + "-home")
    with patch.object(suite, "repository_root", return_value=repo), \
            patch.object(suite, "config", return_value={}), \
            patch.object(suite, "doctor", return_value=[]) as doctor:
        assert suite.main(["doctor", "--test-home", str(home), "--live"]) == 0
    assert doctor.call_args.args[2][0]["asset_blocked"]
    assert json.loads(capsys.readouterr().out)["ready"]


def test_browser_probe_uses_actual_batch_channel_and_test_home(tmp_path):
    import node_preflight
    from types import SimpleNamespace
    with patch.object(node_preflight.shutil, "which", return_value="node"), \
            patch.object(node_preflight.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
        assert node_preflight.node_toolchain_problems(REPO, tmp_path, {"playwright"}, environment={
            "NEXENT_TEST_BROWSER_CHANNEL": "chrome", "PLAYWRIGHT_BROWSERS_PATH": "wrong-cache"}) == []
    assert run.call_args.args[0][-1] == "chrome"
    assert run.call_args.kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "runtime/playwright-browsers")


def test_missing_browser_blocks_only_browser_case_and_batch_continues(tmp_path):
    rows = [{"case_id": name, "stage": "D1", "status": "active", "execution": {
        "implementations": [{"framework": framework, "file": "unused", "selector": name}]}}
        for name, framework in (("BROWSER", "playwright"), ("INDEPENDENT", "pytest"))]
    calls = []

    def run(command, cwd, env, log, timeout):
        if "--case" in command:
            case_id = command[command.index("--case") + 1]
            calls.append(case_id)
            batch = Path(command[command.index("--batch-dir") + 1])
            save(batch / "cases" / case_id / "receipt.json", {"case_id": case_id, "stage": "D1", "result": "PASS"})
        return 0

    with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
            patch.object(suite, "fingerprint", return_value={"head": "fixed"}), \
            patch.object(suite, "static_requirements", return_value=set()), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite, "node_runtime_problems", return_value=["missing browser"]), \
            patch.object(suite, "logged", side_effect=run):
        assert suite.execute(tmp_path, tmp_path, rows, {"hooks": {}, "case_timeout_seconds": 20}) == 1
    batch = next((tmp_path / "runs/repository-daily").iterdir())
    summary = json.loads((batch / "summary.json").read_text())
    assert calls == ["INDEPENDENT"]
    assert summary["counts"] == {"BLOCKED": 1, "PASS": 1} and summary["execution_complete"]
    assert json.loads((batch / "cases/BROWSER/receipt.json").read_text())["reason"] == "missing browser"


def test_fingerprint_prunes_dependency_directories_but_checks_source_bytes(tmp_path):
    asset = tmp_path / "test-e2e/cases/A/test.py"
    asset.parent.mkdir(parents=True)
    asset.write_text("one")
    dependency = tmp_path / "test-e2e/infra/node_modules/deep/huge.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("ignored")
    with patch("suite_runtime.subprocess.check_output", side_effect=lambda argv, **kwargs:
               "head" if "rev-parse" in argv else b""):
        first = fingerprint(tmp_path)
        with patch.object(Path, "rglob", side_effect=AssertionError("Do not traverse node_modules per Case")):
            assert fingerprint(tmp_path) == first
        previous = asset.stat()
        asset.write_text("two")
        os.utime(asset, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert fingerprint(tmp_path) != first
