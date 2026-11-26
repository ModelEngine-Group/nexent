# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment command ordering with controlled cluster and Helm boundaries."""

from uuid import UUID

import pytest
from test_k8s_helm import _deploy_command, _run
from test_k8s_helm import isolated_k8s_project as _isolated_project

isolated_k8s_project = _isolated_project


@pytest.mark.parametrize("failure", ["", "lock", "previous_writer", "scale", "bootstrap", "lock_loss"])
def test_existing_release_stops_writers_and_activates_only_after_bootstrap(isolated_k8s_project, failure):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true"})
    if failure:
        env[f"MOCK_FAIL_{failure.upper()}"] = "true"
    result = _run(_deploy_command(project, scope="nexent"), check=False, env=env)
    assert result.returncode == (1 if failure else 0), result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    scales = [i for i, line in enumerate(commands) if line.startswith("kubectl scale ")]
    upgrades = [i for i, line in enumerate(commands) if line.startswith("helm upgrade --install nexent ")]
    lock = next(i for i, line in enumerate(commands) if "pg_try_advisory_lock" in line)
    assert not any("helm upgrade --install nexent-infrastructure " in line for line in commands)
    if failure in ("lock", "previous_writer"):
        assert not scales and not upgrades
        if failure == "previous_writer":
            assert "Job nexent/nexent-runtime-maintenance-prior is not terminal" in result.stderr
        return
    assert scales
    assert lock < min(scales)
    assert all("--replicas=0" in commands[i] for i in scales)
    if failure == "scale":
        assert not upgrades
        assert not any("nexent-bootstrap-start" in line for line in commands)
        return
    assert len(scales) == 7
    assert [commands[index].split()[2] for index in scales[:3]] == [
        "deployment/nexent-gateway", "deployment/nexent-web", "deployment/nexent-northbound",
    ]
    assert max(scales) < upgrades[0]
    assert "global.businessPaused=true" in commands[upgrades[0]]
    bootstrap_id = next(argument.split("=", 1)[1] for argument in commands[upgrades[0]].split()
                        if argument.startswith("global.bootstrapRunId="))
    assert str(UUID(bootstrap_id)) == bootstrap_id
    if failure == "bootstrap":
        assert len(upgrades) == 1
        assert any(line.startswith("kubectl delete job nexent-system-bootstrap-test ") for line in commands)
        assert not any("nexent-bootstrap-start" in line for line in commands)
        assert not any(line.startswith("kubectl apply -f -") for line in commands)
        return
    start = next(i for i, line in enumerate(commands) if "nexent-bootstrap-start" in line)
    complete = next(i for i, line in enumerate(commands) if ".status.succeeded" in line and "kubectl get job " in line)
    recheck = next(i for i, line in enumerate(commands) if i > complete and "pg_locks" in line)
    assert upgrades[0] < start < complete < recheck
    assert any("kubectl get jobs" in line and f"nexent.io/bootstrap-run-id={bootstrap_id}" in line for line in commands)
    assert not any(line.startswith("kubectl apply -f -") or "execution_reservation_t" in line for line in commands)
    if failure:
        assert "Runtime deployment lock could not be verified" in result.stderr
        assert len(upgrades) == 1
        return
    assert len(upgrades) == 2
    assert recheck < upgrades[1]
    assert "global.bootstrapRunId=" in commands[upgrades[1]].split()
    assert "global.businessPaused=false" in commands[upgrades[1]]
    assert {commands[i].split()[2] for i in scales} == {
        f"deployment/nexent-{name}"
        for name in ("config", "runtime", "mcp", "gateway", "northbound", "web", "data-process")
    }


def test_deploy_changes_fixed_runtime_count_only_through_offline_windows(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true"})
    bootstrap_ids = set()
    for count in (3, 2, 1):
        mock_log.write_text("", encoding="utf-8")
        result = _run([*_deploy_command(project, scope="nexent"), "--runtime-replicas", str(count)],
                      check=False, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        commands = mock_log.read_text(encoding="utf-8").splitlines()
        pause, activate = [index for index, line in enumerate(commands)
                           if line.startswith("helm upgrade --install nexent ")]
        assert any("kubectl scale deployment/nexent-runtime" in line and "--replicas=0" in line
                   for line in commands[:pause])
        assert f"nexent-runtime.replicaCount={count}" in commands[pause]
        assert f"nexent-runtime.replicaCount={count}" in commands[activate]
        assert "global.businessPaused=true" in commands[pause]
        assert "global.businessPaused=false" in commands[activate]
        bootstrap_id = next(argument.split("=", 1)[1] for argument in commands[pause].split()
                            if argument.startswith("global.bootstrapRunId="))
        bootstrap_ids.add(bootstrap_id)
        assert "global.bootstrapRunId=" in commands[activate].split()
        assert any("nexent-bootstrap-start" in line for line in commands[pause:activate])
        assert not any(line.startswith("kubectl apply -f -") for line in commands[pause:activate])
        assert any(line.startswith("kubectl rollout status deployment/nexent-runtime") for line in commands[activate:])
        assert f"runtimeReplicas: {count}" in (project / "deploy/k8s/deploy.options").read_text(encoding="utf-8")
    assert len(bootstrap_ids) == 3


@pytest.mark.parametrize(
    "chart_count,saved_count,previous_chart_count,explicit_count,expected",
    [
        ("3", "1", None, None, 3),
        ("1", "3", "3", None, 1),
        ("1", "3", None, None, 3),
        ("3", "2", "3", None, 2),
        ("3", "1", "1", "2", 2),
        ("unset", "2", "3", None, 2),
    ],
)
def test_runtime_replica_configuration_precedence(
    isolated_k8s_project, chart_count, saved_count, previous_chart_count, explicit_count, expected,
):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_CHART_RUNTIME_REPLICAS": chart_count})
    options = project / "deploy/k8s/deploy.options"
    saved_options = f"k8s:\n  runtimeReplicas: {saved_count}\n"
    if previous_chart_count is not None:
        saved_options += f'  runtimeChartReplicas: "{previous_chart_count}"\n'
    options.write_text(saved_options, encoding="utf-8")

    command = _deploy_command(project, scope="nexent")
    if explicit_count is not None:
        command.extend(["--runtime-replicas", explicit_count])
    result = _run(command, check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    upgrades = [line for line in mock_log.read_text(encoding="utf-8").splitlines()
                if line.startswith("helm upgrade --install nexent ")]
    assert len(upgrades) == 2
    assert all(f"nexent-runtime.replicaCount={expected}" in line for line in upgrades)
    saved = options.read_text(encoding="utf-8")
    assert f"runtimeReplicas: {expected}" in saved
    assert f'runtimeChartReplicas: "{chart_count}"' in saved


def test_invalid_runtime_chart_count_fails_before_stopping_business(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project
    env["MOCK_CHART_RUNTIME_REPLICAS"] = "invalid"

    result = _run(_deploy_command(project, scope="nexent"), check=False, env=env)

    assert result.returncode == 1
    assert "nexent-runtime.replicaCount in values.yaml" in result.stderr
    assert not mock_log.exists()
    assert not (project / "deploy/k8s/deploy.options").exists()


def test_removed_maintenance_retry_option_fails_before_cluster_access(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project
    command = _deploy_command(project, scope="nexent")
    result = _run([*command, "--retry-runtime-maintenance", str(UUID(int=1))], check=False, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "--retry-runtime-maintenance was removed" in result.stderr
    assert not mock_log.exists()


@pytest.mark.parametrize("storage", ["", "omitted-volume-mode"])
def test_existing_rwx_claims_are_checked_before_pause_and_bootstrap_writes(isolated_k8s_project, storage):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_RUNTIME_STORAGE": storage})
    result = _run([*_deploy_command(project, scope="nexent"), "--persistence-mode", "existing",
                   "--existing-claim-prefix", "shared", "--runtime-replicas", "3"], check=False, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    first_scale = next(index for index, line in enumerate(commands) if line.startswith("kubectl scale "))
    pause = next(index for index, line in enumerate(commands)
                 if line.startswith("helm upgrade --install nexent ") and "businessPaused=true" in line)
    first_copy = next(index for index, line in enumerate(commands) if line.startswith("kubectl cp "))
    claims = {"shared-nexent-workspace", "shared-nexent-skills", "shared-nexent-logs", "nexent-memory-plugins",
              "nexent-trajectory"}
    for window in (commands[:first_scale], commands[pause:first_copy]):
        assert {line.split()[3] for line in window if line.startswith("kubectl get pvc ")} == claims
        assert {line.split()[3] for line in window if line.startswith("kubectl get pv ")} == {
            f"pv-{claim}" for claim in claims
        }
        for line in window:
            if line.startswith(("kubectl get pvc ", "kubectl get pv ")):
                assert '{range .spec.accessModes[*]}{@}{","}{end}' in line


@pytest.mark.parametrize("mode", ["dynamic", "existing"])
def test_rwx_hostpath_pv_allows_multi_replica_activation(isolated_k8s_project, mode):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_RUNTIME_STORAGE": "hostpath"})
    result = _run([*_deploy_command(project, scope="nexent"), "--persistence-mode", mode, "--runtime-replicas", "3"],
                  check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    activated, = [line for line in commands if line.startswith("helm upgrade --install nexent ")
                  and "global.businessPaused=false" in line]
    assert "nexent-runtime.replicaCount=3" in activated


@pytest.mark.parametrize("mode,failure", [("dynamic", "local"),
                                          ("dynamic", "wrong-pv-mode"), ("dynamic", "unavailable"),
                                          ("dynamic", "pv-block"), ("existing", "pvc-block"),
                                          ("existing", "pv-block"), ("existing", "rwo"),
                                          ("existing", "pending"), ("existing", "missing")])
def test_multi_replica_storage_failures_never_activate_runtime(isolated_k8s_project, mode, failure):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_RUNTIME_STORAGE": failure})
    result = _run([*_deploy_command(project, scope="nexent"), "--persistence-mode", mode, "--runtime-replicas", "3"],
                  check=False, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Error: " in result.stderr and "Runtime" in result.stderr
    if failure.endswith("-block"):
        assert "Filesystem" in result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("kubectl apply -f -") for line in commands)
    assert not any(line.startswith("kubectl cp ") or "nexent-bootstrap-start" in line for line in commands)
    upgrades = [line for line in commands if line.startswith("helm upgrade --install nexent ")]
    if mode == "existing":
        assert not upgrades
        assert not any(line.startswith("kubectl scale ") for line in commands)
    else:
        paused, = upgrades
        assert "global.businessPaused=true" in paused


@pytest.mark.parametrize("args,error", [
    (["--runtime-replicas", "0"], "must be a positive integer"),
    (["--runtime-replicas", "-1"], "must be a positive integer"),
    (["--runtime-replicas", "3.5"], "must be a positive integer"),
    (["--runtime-replicas", "2147483648"], "must be a positive integer"),
    (["--runtime-replicas", "3", "--persistence-mode", "local"], "not local hostPath"),
    (["--runtime-replicas", "3", "--storage-class", ""], "explicit RWX --storage-class"),
    (["--runtime-replicas"], "requires a replica count"),
])
def test_invalid_replica_options_fail_before_cluster_interaction(isolated_k8s_project, args, error):
    project, env, mock_log = isolated_k8s_project
    result = _run([*_deploy_command(project, scope="nexent"), *args], check=False, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert error in result.stderr
    assert not mock_log.exists()
