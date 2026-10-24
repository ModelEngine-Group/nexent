# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline regression for exception selection, opt-in, backups and recovery."""
from pathlib import Path
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deployment_exceptions as modes
from suite_runtime import finalize, save

REPO = Path(__file__).resolve().parents[4]


def test_suite_mock_runtime_state_never_changes_source_json(tmp_path):
    source = tmp_path / "checkout/mock"
    shutil.copytree(REPO / "test-e2e/infra/mock-services/ext-knowledge-mock", source,
                    ignore=shutil.ignore_patterns("_state", "__pycache__"))
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.json")}
    state = tmp_path / "test-home/case/runtime/ext-knowledge-state"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**os.environ, "EXT_KNOWLEDGE_AIDP_MOCK_PATH": str(
        REPO / "test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py")}
    with (tmp_path / "mock.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen([sys.executable, str(source / "server.py"), "--host", "127.0.0.1",
                                    "--port", str(port), "--state-dir", str(state)],
                                   env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 20
            while True:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    assert process.poll() is None, (tmp_path / "mock.log").read_text()
                    assert time.monotonic() < deadline, "Mock did not become ready"
                    time.sleep(0.1)
            with opener.open(Request(f"http://127.0.0.1:{port}/_reset", method="POST"), timeout=3) as response:
                assert response.status == 200
            assert (state / "aidp.json").is_file()
            assert (state / "dify.json").is_file()
            after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.json")}
            assert after == before
            assert not (source / "_state").exists()
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_only_active_exceptions_switch_and_normal_cases_run_once():
    rules = modes.catalog(REPO)
    records = [{"case_id": key, "status": status} for key, status in [
        ("ORDINARY-01", "active"), ("CTR-047", "active"), ("PW-KB-AIDP-01", "retired")]]
    grouped = modes.groups(records, rules)
    assert [r["case_id"] for r in grouped["local"]] == ["ORDINARY-01", "PW-KB-AIDP-01"]
    assert [r["case_id"] for r in grouped["modelengine"]] == ["CTR-047"]
    assert "aidp" not in grouped


def test_every_feature_gated_aidp_case_has_deployment_and_owned_mock():
    policy = json.loads((REPO / 'test-e2e/infra/automation/feature-test-policy.json').read_text())
    gated = policy['required_features']['aidp_knowledge']
    rules = modes.catalog(REPO)
    assert len(gated) == 6
    records = [{'case_id': case_id, 'status': 'active'} for case_id in gated]
    assert {row['case_id'] for row in modes.groups(records, rules)['aidp']} == set(gated)
    for case_id in gated:
        binding = yaml.safe_load((REPO / 'test-e2e/cases' / case_id / 'execution.yaml').read_text(encoding='utf-8'))
        assert 'knowledge-provider' in binding['required_mock_services']
        assert binding['preparation']['anchors'] is True


def test_mode_switch_updates_pytest_flag_and_restores_original_local_bytes(tmp_path):
    repo, home, env_path, original, records, settings = campaign_fixture(tmp_path)
    environment = home / 'config/environment.yaml'
    before = environment.read_bytes()
    calls = []
    switch = modes.ModeSwitch(repo, home, tmp_path / 'campaign', settings, {},
                              lambda name, *args: calls.append(name))
    switch.snapshot()
    with patch.object(switch, 'verify'):
        switch.apply('aidp', {'ENABLE_AIDP_KNOWLEDGE': 'true'})
        assert yaml.safe_load(environment.read_text())['features']['aidp_knowledge'] is True
        switch.restore()
    assert environment.read_bytes() == before
    assert env_path.read_bytes() == original
    assert calls == ['deploy', 'preflight', 'deploy', 'preflight']


def test_catalog_rejects_unknown_cases_and_profiles(tmp_path):
    config = tmp_path / "test-e2e/infra/config"
    config.mkdir(parents=True)
    import shutil
    for suffix in (".yaml", ".schema.json"):
        shutil.copyfile(REPO / (modes.CATALOG.removesuffix(".yaml") + suffix), config / ("deployment-exceptions" + suffix))
    with pytest.raises(ValueError, match="unknown Case"):
        modes.catalog(tmp_path, [])
    path = tmp_path / modes.CATALOG
    data = yaml.safe_load(path.read_text())
    data["cases"]["CTR-047"] = "invented"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="unknown profile"):
        modes.catalog(tmp_path)


def test_duplicate_yaml_keys_and_unsafe_env_are_rejected(tmp_path):
    path = tmp_path / "settings.yaml"
    schema = REPO / "test-e2e/infra/config/deployment-switch.schema.json"
    path.write_text("schema_version: 1\nenabled: true\nenabled: false\n")
    with pytest.raises(ValueError, match="Duplicate"):
        modes.checked_yaml(path, schema)
    path.write_text("schema_version: 1\nenabled: true\ndatabase: destroy\n")
    with pytest.raises(ValueError, match="Invalid"):
        modes.checked_yaml(path, schema)


def test_opt_in_is_not_implicit_and_pending_blocks(tmp_path):
    assert not modes.enabled(REPO, tmp_path)
    save(tmp_path / modes.MARKER, {"status": "RESTORE_FAILED"})
    with pytest.raises(RuntimeError, match="Pending"):
        modes.assert_recovered(tmp_path)


def test_env_patch_preserves_other_settings_and_is_not_shell_evaluation():
    original = b"# retained\nDATABASE=original\nENABLE_AIDP_KNOWLEDGE=false\nAPI_KEY='secret'\n"
    patched = modes.patch_env(original, {"ENABLE_AIDP_KNOWLEDGE": "true"})
    assert patched == original.replace(b"ENABLE_AIDP_KNOWLEDGE=false", b"ENABLE_AIDP_KNOWLEDGE=true")
    with pytest.raises(ValueError, match="Duplicate"):
        modes.patch_env(b"MODEL_ENGINE_ENABLED=false\nMODEL_ENGINE_ENABLED=false\n", {"MODEL_ENGINE_ENABLED": "true"})


@pytest.mark.parametrize("host", ["", "host/path", "user@host", "host\nINJECT=true", "host:1234"])
def test_invalid_mock_host_never_reaches_deployment(host):
    with pytest.raises(ValueError):
        modes.mock_product_url({"NEXENT_TEST_ASSETS_CONTAINER_HOST": host})


def test_valid_mock_host_and_registered_port():
    assert modes.mock_product_url({"NEXENT_TEST_ASSETS_CONTAINER_HOST": "172.17.0.1"}) == "http://172.17.0.1:30090"


def test_single_case_cli_uses_the_same_switching_controller(tmp_path):
    import run_cases
    from types import SimpleNamespace
    record = {"case_id": "CTR-047", "stage": "D3", "status": "active", "execution": {"implemented": True}}
    with patch.object(run_cases, "repository_root", return_value=REPO), \
         patch.object(run_cases, "inspect", return_value=([], {"cases": [record]})), \
         patch.object(run_cases, "machine_environment", return_value={}), \
         patch.object(run_cases.subprocess, "run", return_value=SimpleNamespace(returncode=2)) as launch, \
         patch.object(sys, "argv", ["run_cases.py", "CTR-047", "--test-home", str(tmp_path)]):
        assert run_cases.main() == 2
        command = launch.call_args.args[0]
        assert command[2] == "run" and command[-2:] == ["--case", "CTR-047"]
        assert "--execute" in command


def test_failed_runtime_mode_verification_cannot_pass(tmp_path):
    switch = modes.ModeSwitch(REPO, tmp_path, tmp_path, {}, {"NEXENT_CONFIG_URL": "http://localhost:5010"}, None)
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"enable_aidp_knowledge":true}'
    container = {"Name": "/nexent-config", "Config": {"Env": ["ENABLE_AIDP_KNOWLEDGE=false", "MODEL_ENGINE_ENABLED=false"]}}
    with patch.object(modes, "build_opener") as opener, \
         patch.object(modes.subprocess, "check_output", return_value=json.dumps([container])), \
         patch.object(modes.time, "sleep"):
        opener.return_value.open.return_value = response
        with pytest.raises(RuntimeError, match="verification failed"):
            switch.verify({"ENABLE_AIDP_KNOWLEDGE": "true"}, "aidp")


def campaign_fixture(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    import shutil
    shutil.copytree(REPO / "test-e2e/infra/config", repo / "test-e2e/infra/config")
    catalog_path = repo / modes.CATALOG
    rules = yaml.safe_load(catalog_path.read_text(encoding='utf-8'))
    rules['cases'] = {key: value for key, value in rules['cases'].items()
                      if key in {'CTR-047', 'PW-KB-AIDP-01'}}
    catalog_path.write_text(yaml.safe_dump(rules), encoding='utf-8')
    (repo / ".git").mkdir()
    env_path = repo / "deploy/env/.env"
    env_path.parent.mkdir(parents=True)
    original = b"ENABLE_AIDP_KNOWLEDGE=false\nMODEL_ENGINE_ENABLED=false\nDATABASE=do-not-change\n"
    env_path.write_bytes(original)
    (home / "config").mkdir(parents=True)
    (home / "config/environment.yaml").write_text("features:\n  aidp_knowledge: false\n")
    (home / "config/deployment-switch.yaml").write_text("schema_version: 1\nenabled: true\n")
    records = [{"case_id": case_id, "stage": "D4" if case_id.startswith("PW") else "D3",
                "status": "active", "execution": {}} for case_id in ["CTR-047", "PW-KB-AIDP-01", "PW-KB-LOCAL-01"]]
    settings = {"hooks": {"deploy": [["deploy"]], "preflight": [["wait"]]}, "notify": True}
    return repo, home, env_path, original, records, settings


@pytest.mark.parametrize("failure", [None, "aidp", "restore-local"])
def test_campaign_restores_on_failures_and_accounts_for_every_case(tmp_path, failure):
    repo, home, env_path, original, records, settings = campaign_fixture(tmp_path)
    calls = []

    def hook(name, settings, repo, home, directory, env):
        calls.append((directory.name, name))
        if failure == directory.name and name == "deploy":
            raise RuntimeError("injected deployment failure")

    def execute(repo, home, selected, settings, *, directory, on_result=None):
        assert settings["notify"] is False
        directory.mkdir(parents=True)
        save(directory / "status.json", {})
        results = [{"case_id": r["case_id"], "stage": r["stage"], "result": "PASS", "evidence": []} for r in selected]
        for record in selected:
            case_dir = directory / "cases" / record["case_id"]
            case_dir.mkdir(parents=True)
            (case_dir / "evidence.log").write_text("original evidence path must remain valid")
        for result in results:
            if on_result:
                on_result(dict(result))
                if directory.name != "restore-local":
                    assert (directory.parents[1] / "progress.json").exists()
        finalize(directory, selected, results)
        return 0

    with patch.object(modes, "fingerprint", return_value={"head": "a" * 40}), \
         patch.object(modes.ModeSwitch, "verify"), \
         patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])), \
         patch("suite_notify.send_report") as notify:
        result = modes.execute_campaign(repo, home, records[:2], settings, daily=False, publish_latest=False,
            execute_one=execute, all_records=records, hook=hook,
            machine_env=lambda *_: {"NEXENT_CONFIG_URL": "http://localhost:5010", "NEXENT_TEST_ASSETS_CONTAINER_HOST": "host"})
        notify.assert_not_called()
    assert env_path.read_bytes() == original
    directories = list((home / "runs/repository-daily").glob("deployment-*"))
    summary = json.loads((directories[0] / "summary.json").read_text())
    assert summary["recorded"] == summary["planned"] == 2
    assert result == (0 if failure is None else 1)
    assert (home / modes.MARKER).exists() == (failure == "restore-local")
    assert (home / "runtime/deployment-switch-backups" / directories[0].name / "0").read_bytes() == original
    assert ("restore-local", "deploy") in calls
    if failure != "aidp":
        original_evidence = directories[0] / "profiles/modelengine/cases/CTR-047/evidence.log"
        assert original_evidence.is_file()
        assert (directories[0] / "cases/CTR-047/evidence.log").read_text() == original_evidence.read_text()
