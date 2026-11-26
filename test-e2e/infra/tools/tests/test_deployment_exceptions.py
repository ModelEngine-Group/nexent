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


def test_daily_tfp_group_contains_only_the_two_deployed_cases():
    rules = modes.catalog(REPO)
    records = [{"case_id": key, "status": "active"}
               for key in ("TFP-D3-001", "TFP-D4-001", "TFP-D1-005", "PW-KB-AIDP-01", "CTR-047")]
    selected = modes.groups(records, rules)
    assert list(selected) == ["local", "modelengine", "aidp", "tfp"]
    assert [record["case_id"] for record in selected["tfp"]] == ["TFP-D3-001", "TFP-D4-001"]
    assert [record["case_id"] for record in selected["local"]] == ["TFP-D1-005"]


@pytest.mark.parametrize("variant", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_runtime_workspace_mount_keeps_the_named_volume_as_default(variant):
    compose = yaml.safe_load((REPO / "deploy/docker/compose" / variant).read_bytes())
    assert "nexent_agent_workspace:/mnt/nexent/workdir" in compose["services"]["nexent-runtime"]["volumes"]


@pytest.mark.parametrize("configuration", ["same", "wrong-project", "wrong-root", "different-hash"])
def test_tfp_runtime_override_only_uses_the_reproducible_owned_compose_service(tmp_path, configuration):
    base = str(tmp_path / "deploy/docker/compose/docker-compose.prod.yml")
    workspace = tmp_path / "private/workspace"
    labels = {"com.docker.compose.project": "inventory" if configuration == "wrong-project" else "nexent",
              "com.docker.compose.service": "nexent-runtime",
              "com.docker.compose.project.config_files": "/other/compose.yml" if configuration == "wrong-root" else base,
              "com.docker.compose.config-hash": "owned-hash"}
    replies = [json.dumps([{"Config": {"Labels": labels}}]),
               "nexent-runtime other-hash" if configuration == "different-hash" else "nexent-runtime owned-hash"]
    with patch.object(modes.subprocess, "check_output", side_effect=replies) as inspect, \
            patch.object(modes, "logged", return_value=0) as compose:
        if configuration == "same":
            modes.apply_tfp_workspace(tmp_path, workspace, {}, tmp_path, 30)
            assert "--hash" in inspect.call_args.args[0]
            command, cwd, env, *_ = compose.call_args.args
            assert cwd == tmp_path and env["NEXENT_TFP_WORKSPACE"] == workspace.as_posix()
            assert command[-9:] == ["-f", str(tmp_path / modes.TFP_OVERRIDE), "up", "-d", "--no-deps", "--no-build",
                                     "--pull", "never", "nexent-runtime"]
        else:
            with pytest.raises(RuntimeError, match="TFP overlay"):
                modes.apply_tfp_workspace(tmp_path, workspace, {}, tmp_path, 30)
            compose.assert_not_called()


def test_tfp_mode_verifies_active_bind_mount_and_requires_local_volume_on_restore(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    switch = modes.ModeSwitch(REPO, tmp_path, tmp_path, {}, {}, None)
    switch.tfp_requested = True
    mount_path = switch.tfp_workspace.as_posix()
    local = {"Source": "/docker/volume", "Destination": "/mnt/nexent/workdir", "Type": "volume", "RW": True}
    bound = {"Source": mount_path, "Destination": mount_path, "Type": "bind", "RW": True}
    runtime = {"Name": "/nexent-runtime", "Config": {"Env": []}, "Mounts": [local]}
    management = {"Name": "/nexent-config", "Config": {"Env": []}}
    monkeypatch.setattr(switch, "_gateway_deployment_mode", AsyncMock(return_value={"enable_aidp_knowledge": False}))
    monkeypatch.setattr(modes.subprocess, "check_output", lambda *_args, **_kwargs: json.dumps([runtime, management]))
    monkeypatch.setattr(modes.time, "sleep", lambda _: None)
    switch.verify({}, "local")

    switch.tfp_switched = True
    flags = [f"{key}={value}" for key, value in modes.TFP_CONTAINER_MODE.items()]
    management["Config"]["Env"] = flags
    runtime["Config"]["Env"] = [*flags, "AGENT_WORKSPACE_ROOT=" + mount_path]
    with pytest.raises(RuntimeError, match="mode mismatch"):
        switch.verify(modes.TFP_MODE, "tfp")
    runtime["Mounts"] = [bound]
    switch.verify(modes.TFP_MODE, "tfp")

    runtime["Config"]["Env"] = management["Config"]["Env"] = []
    with pytest.raises(RuntimeError, match="mode mismatch"):
        switch.verify({}, "restore-local")
    runtime["Mounts"] = [local]
    switch.verify({}, "restore-local")


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


@pytest.mark.parametrize("mode,container_mode,expected_error", [
    (True, "true", None),
    (True, "false", "mode mismatch"),
    (1, "true", "mode mismatch"),
    (401, "true", "Gateway returned HTTP 401"),
])
def test_mode_verification_authenticates_via_gateway(tmp_path, monkeypatch, mode, container_mode, expected_error):
    import httpx

    config = tmp_path / "config"
    config.mkdir()
    (config / "users.yaml").write_text(
        "users: [{id: tenant_a_admin, username: admin@example.test, password_env_key: MODE_TEST_PASSWORD}]",
        encoding="utf-8",
    )
    (config / "secrets.env").write_text("MODE_TEST_PASSWORD=fixture-password", encoding="utf-8")
    env = {"NEXENT_CONFIG_URL": "http://management.local:5010", "NEXENT_NORTHBOUND_URL": "http://gateway.local:5013"}
    switch = modes.ModeSwitch(REPO, tmp_path, tmp_path, {}, env, None)
    requests = []
    inspect = [{"Name": "test-container", "Config": {"Env": [f"ENABLE_AIDP_KNOWLEDGE={container_mode}"]}}]

    def respond(request):
        requests.append(request)
        assert request.url.host == "gateway.local"
        if request.method == "POST":
            assert request.url.path == "/api/user/signin"
            assert json.loads(request.content) == {"email": "admin@example.test", "password": "fixture-password"}
            return httpx.Response(200, json={"data": {"access_token": "Bearer fixture-token"}})
        assert request.url.path == "/api/tenant_config/deployment_version"
        assert request.headers["Authorization"] == "Bearer fixture-token"
        if mode == 401:
            return httpx.Response(401)
        return httpx.Response(200, json={"enable_aidp_knowledge": mode})

    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(modes.httpx, "AsyncClient", client)
    monkeypatch.setattr(modes.subprocess, "check_output", lambda *_args, **_kwargs: json.dumps(inspect))
    monkeypatch.setattr(modes.time, "sleep", lambda _: None)
    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            switch.verify({"ENABLE_AIDP_KNOWLEDGE": "true"}, "aidp")
        assert not (tmp_path / "aidp/mode-verification.json").exists()
    else:
        switch.verify({"ENABLE_AIDP_KNOWLEDGE": "true"}, "aidp")
        receipt = (tmp_path / "aidp/mode-verification.json").read_text(encoding="utf-8")
        assert json.loads(receipt)["aidp_enabled"] is True
        assert "fixture-token" not in receipt
    assert [request.method for request in requests[:2]] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_shared_login_and_api_use_gateway_while_readiness_keeps_downstream(tmp_path, monkeypatch):
    import httpx

    monkeypatch.syspath_prepend(str(REPO / "test-e2e/infra/automation"))
    from shared import auth
    from shared.config import readiness_url, service_url
    from shared.http import client

    config = tmp_path / "config"
    config.mkdir()
    (config / "environment.yaml").write_text(
        "services:\n  config:\n    url: http://gateway.local:5013/api\n"
        "    readiness_url: http://management.local:5010/health/ready\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXENT_TEST_HOME", str(tmp_path))
    monkeypatch.delenv("NEXENT_CONFIG_URL", raising=False)
    monkeypatch.delenv("NEXENT_RUNTIME_URL", raising=False)
    routes = []

    def respond(request):
        routes.append((request.url.host, request.url.path))
        if request.url.path == "/api/user/signin":
            return httpx.Response(200, json={"data": {"access_token": "fixture-token"}})
        assert request.headers["Authorization"] == "Bearer fixture-token"
        return httpx.Response(200, json={"data": {"user": {"id": "user-id", "tenant_id": "tenant-id"}}})

    real_client = httpx.AsyncClient

    def fixture_client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", fixture_client)
    identity = await auth.sign_in_credentials("fixture", {"username": "fixture@example.test"}, "fixture-password")
    assert identity.tenant_id == "tenant-id"
    async with client("config", token=identity.access_token) as api:
        assert (await api.get("/config/load_config")).is_success
    assert routes == [
        ("gateway.local", "/api/user/signin"),
        ("gateway.local", "/api/user/current_user_info"),
        ("gateway.local", "/api/config/load_config"),
    ]
    assert readiness_url("config") == "http://management.local:5010/health/ready"
    assert service_url("runtime") == "http://localhost:5013/api"
    monkeypatch.setenv("NEXENT_CONFIG_URL", "http://isolated-fixture.local:5020")
    assert service_url("config") == "http://isolated-fixture.local:5020"


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


@pytest.mark.parametrize("outcome", ["missing", "passed", "interrupted", "smoke_failed"])
def test_tfp_profile_restores_private_config_and_checks_local_without_duplicate_rows(tmp_path, outcome):
    repo, home, env_path, original, records, settings = campaign_fixture(tmp_path)
    catalog_path = repo / modes.CATALOG
    rules = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    rules["cases"] = {case_id: "tfp" for case_id in sorted(modes.TFP_CASES)}
    catalog_path.write_text(yaml.safe_dump(rules, sort_keys=False), encoding="utf-8")
    config_path = repo / "deploy/docker/deploy.options"
    config_path.parent.mkdir(parents=True)
    config = b'# retained\ncomponents:\n  - application\nsandboxMode: "lightweight"\nmonitoringProvider: "otlp"\n'
    config_path.write_bytes(config)
    monitoring_path = repo / "deploy/env/monitoring.env"
    monitoring = b"MONITORING_PROVIDER=otlp\nMONITORING_INSTRUMENT_REQUESTS=false\nOTEL_EXPORTER_OTLP_HEADERS=private\n"
    monitoring_path.write_bytes(monitoring)
    (home / "config/secrets.env").write_text(
        "TFP_TRACE_PUBLIC_KEY=a\nTFP_TRACE_SECRET_KEY=b\nTENANT_A_PASSWORD=c\nTENANT_B_PASSWORD=d\n",
        encoding="utf-8",
    )
    (home / "config/users.yaml").write_text(
        "users:\n"
        "  - {id: tenant_a_admin, username: a@example.test, password_env_key: TENANT_A_PASSWORD}\n"
        "  - {id: tenant_b_user, username: b@example.test, password_env_key: TENANT_B_PASSWORD}\n",
        encoding="utf-8",
    )
    smoke = {**records[-1], "execution": {"implemented": True}}
    records = [smoke, *({"case_id": case_id, "stage": case_id.split("-")[1], "status": "active",
                         "execution": {"implemented": True}} for case_id in sorted(modes.TFP_CASES))]
    touched = []
    settings.update(notify=False, command_timeout_seconds=30)
    original_deploy = ["bash", "{repo}/deploy/docker/deploy.sh", "--use-local-config", "--components", "application"]
    settings["hooks"]["deploy"] = [original_deploy]

    def hook(name, hook_settings, _repo, _home, directory, _env):
        if name != "deploy":
            return
        touched.append(directory.name)
        if directory.name == "tfp":
            assert hook_settings["hooks"]["deploy"] == [
                [*original_deploy[:-1], "application,monitoring", "--monitoring-provider", "langfuse"]]
            config_path.write_bytes(config.replace(b"  - application", b"  - application\n  - monitoring")
                                    .replace(b"otlp", b"langfuse"))
            assert dict(modes.env_file(env_path)[0], **modes.TFP_MODE) == modes.env_file(env_path)[0]
            workspace = home / "runtime/tfp-workspaces" / directory.parent.name
            assert workspace.is_dir()
            assert "AGENT_WORKSPACE_ROOT" not in modes.env_file(env_path)[0]
            assert b"MONITORING_INSTRUMENT_REQUESTS=true" in monitoring_path.read_bytes()
            assert b"OTEL_EXPORTER_OTLP_HEADERS=private" in monitoring_path.read_bytes()
            monitoring_path.write_bytes(b"rendered-by-deploy")
        elif directory.name == "restore-local":
            assert hook_settings["hooks"]["deploy"] == [original_deploy]
            assert monitoring_path.read_bytes() == monitoring
            assert config_path.read_bytes() == config
            monitoring_path.write_bytes(b"rendered-by-restore")

    def execute(_repo, _home, selected, _settings, *, directory, on_result, deployment_profile=None):
        touched.append(directory.name)
        assert deployment_profile == ("tfp" if directory.name == "tfp" else None)
        if directory.name == "tfp" and outcome == "interrupted":
            raise KeyboardInterrupt
        directory.mkdir(parents=True)
        failed = directory.name == "business-smoke" and outcome == "smoke_failed"
        rows = [{"case_id": row["case_id"], "stage": row["stage"],
                 "result": "FAIL" if failed else "PASS", "cleanup_exit_code": 0} for row in selected]
        for row in rows:
            save(directory / "cases" / row["case_id"] / "receipt.json", row)
            on_result(dict(row))
        finalize(directory, selected, rows)
        return int(failed)

    env = {} if outcome == "missing" else {"NEXENT_TFP_LANGFUSE_URL": "http://monitor.example.test"}
    with patch.object(modes, "fingerprint", return_value={"head": "fixture"}), \
            patch.object(modes.ModeSwitch, "verify"), \
            patch.object(modes, "apply_tfp_workspace") as overlay, \
            patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])):
        assert modes.execute_campaign(repo, home, records, settings, daily=False, publish_latest=False,
                                      execute_one=execute, all_records=records, hook=hook,
                                      machine_env=lambda *args: env) == int(outcome != "passed")
    assert overlay.call_count == int(outcome != "missing")
    directory = next((home / "runs/repository-daily").iterdir())
    assert monitoring_path.read_bytes() == monitoring
    assert config_path.read_bytes() == config
    assert env_path.read_bytes() == original
    assert (home / modes.MARKER).exists() == (outcome == "smoke_failed")
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["recorded"] == 3 and not summary["duplicate_case_ids"]
    assert summary["execution_complete"] == (outcome in {"missing", "passed"})
    assert touched == (["local"] if outcome == "missing" else
                       ["local", "tfp", "tfp", "restore-local", "business-smoke"])
    if outcome == "missing":
        assert summary["counts"] == {"PASS": 1, "BLOCKED_BY_DEPENDENCY": 2}
    else:
        receipt = json.loads((directory / "restore-local/business-smoke.json").read_text())
        assert receipt["status"] == ("FAILED" if outcome == "smoke_failed" else "PASS")


def test_tfp_deploy_keeps_implicit_components_and_overrides_only_monitoring():
    hook = ["bash", "{repo}/deploy/docker/deploy.sh", "--use-local-config", "--monitoring-provider", "otlp"]
    settings = {"hooks": {"deploy": [hook], "preflight": [["probe"]]}}
    original = b'components: [infrastructure, application, data-process]\nsandboxMode: "full"\n'
    scoped = modes.tfp_deploy_settings(settings, original)
    assert scoped["hooks"]["deploy"][0] == [
        *hook[:-1], "langfuse", "--components", "infrastructure,application,data-process,monitoring"]
    assert settings["hooks"]["deploy"][0][-1] == "otlp"


def test_daily_campaign_does_not_abort_all_groups_for_one_unavailable_fixture(tmp_path):
    repo, home, _, _, records, settings = campaign_fixture(tmp_path)
    settings.update(notify=False)
    settings["hooks"]["build"] = [["offline-build"]]
    groups = []

    def execute(repo, home, selected, settings, *, directory, on_result=None):
        groups.append(directory.name)
        directory.mkdir(parents=True)
        rows = [{"case_id": record["case_id"], "stage": record["stage"], "result":
                 "BLOCKED" if record["case_id"] == "PW-KB-LOCAL-01" else "PASS"} for record in selected]
        for row in rows:
            on_result(dict(row))
        finalize(directory, selected, rows)
        return int(any(row["result"] == "BLOCKED" for row in rows))

    with patch.object(modes, "fingerprint", return_value={"head": "fixture"}), \
            patch.object(modes.ModeSwitch, "verify"), \
            patch.object(modes.subprocess, "check_output", return_value=""), \
            patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])), \
            patch("static_assets.inventory", return_value=[{"asset_id": "missing", "path": "file.txt", "destination": "MISSING"}]):
        assert modes.execute_campaign(repo, home, records, settings, daily=True, publish_latest=False,
            execute_one=execute, all_records=records, hook=lambda *args: None,
            machine_env=lambda *args: {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "127.0.0.1"}) == 1
    assert groups == ["local", "aidp", "modelengine"]
    directory = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["execution_complete"] and summary["counts"] == {"BLOCKED": 1, "PASS": 2}
    assert json.loads((directory / "status.json").read_text())["local_restored_and_verified"]


@pytest.mark.parametrize("marker_timing", ["before", "during"])
def test_fault_marker_does_not_block_build_deploy_groups_or_local_completion(tmp_path, marker_timing):
    repo, home, _, original_env, records, settings = campaign_fixture(tmp_path)
    settings.update(notify=False)
    settings["hooks"]["build"] = [["offline-build"]]
    fault = home / "state/deployment-guard/pending.json"
    content = {"record": {"pending": ["nexent-runtime"]}, "evidence": "original-fault"}
    if marker_timing == "before":
        save(fault, content)
    groups, hooks = [], []

    def execute(repo, home, selected, settings, *, directory, on_result=None):
        groups.append(directory.name)
        directory.mkdir(parents=True)
        rows = [{"case_id": record["case_id"], "stage": record["stage"], "result": "PASS"} for record in selected]
        for row in rows:
            on_result(dict(row))
        if marker_timing == "during" and directory.name == "local":
            save(fault, content)
        finalize(directory, selected, rows)
        return 0

    with patch.object(modes, "fingerprint", return_value={"head": "fixture"}), \
            patch.object(modes.ModeSwitch, "verify"), \
            patch.object(modes.subprocess, "check_output", return_value=""), \
            patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])), \
            patch("static_assets.inventory", return_value=[]):
        assert modes.execute_campaign(repo, home, records, settings, daily=True, publish_latest=False,
            execute_one=execute, all_records=records, hook=lambda name, *args: hooks.append(name),
            machine_env=lambda *args: {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "127.0.0.1"}) == 0
    assert hooks[:3] == ["build", "deploy", "preflight"]
    assert groups == ["local", "aidp", "modelengine"]
    assert (repo / "deploy/env/.env").read_bytes() == original_env
    assert json.loads(fault.read_text()) == content
    assert not (home / modes.MARKER).exists()
    directory = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["execution_complete"] and summary["counts"] == {"PASS": 3}


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
    ownership = json.loads((directories[0] / "report-ownership.json").read_text())
    provenance = json.loads((directories[0] / "provenance.json").read_text())
    assert ownership["head"] == provenance["head"] == "a" * 40
    assert {item["case_id"] for item in ownership["cases"]} == {item["case_id"] for item in records[:2]}
    assert summary["recorded"] == summary["planned"] == 2
    assert result == (0 if failure is None else 1)
    assert (home / modes.MARKER).exists() == (failure == "restore-local")
    assert (home / "runtime/deployment-switch-backups" / directories[0].name / "0").read_bytes() == original
    assert ("restore-local", "deploy") in calls
    if failure != "aidp":
        original_evidence = directories[0] / "profiles/modelengine/cases/CTR-047/evidence.log"
        assert original_evidence.is_file()
        assert (directories[0] / "cases/CTR-047/evidence.log").read_text() == original_evidence.read_text()
