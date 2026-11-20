# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment command ordering with controlled cluster and Helm boundaries."""

from uuid import UUID

import pytest
from test_k8s_helm import _deploy_command, _run
from test_k8s_helm import isolated_k8s_project as _isolated_project

isolated_k8s_project = _isolated_project


@pytest.mark.parametrize("failure", ["", "lock", "previous_writer", "scale", "bootstrap", "maintenance",
                                    "epoch", "completion", "lock_loss"])
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
    epoch = next(argument.split("=", 1)[1] for argument in commands[upgrades[0]].split()
                 if argument.startswith("global.maintenanceEpoch="))
    assert str(UUID(epoch)) == epoch
    if failure == "bootstrap":
        assert len(upgrades) == 1
        assert any(line.startswith("kubectl delete job nexent-system-bootstrap-test ") for line in commands)
        assert not any("nexent-bootstrap-start" in line for line in commands)
        assert not any(line.startswith("kubectl apply -f -") for line in commands)
        return
    start = next(i for i, line in enumerate(commands) if "nexent-bootstrap-start" in line)
    maintenance = next(i for i, line in enumerate(commands) if line.startswith("kubectl apply -f -"))
    assert upgrades[0] < start < maintenance
    assert any("kubectl get jobs" in line and f"nexent.io/maintenance-epoch={epoch}" in line for line in commands)
    assert any(f"kubectl get job nexent-runtime-maintenance-{epoch} " in line for line in commands)
    if failure:
        assert len(upgrades) == 1
        return
    assert len(upgrades) == 2
    committed = next(i for i, line in enumerate(commands) if "execution_reservation_t" in line)
    assert maintenance < committed < upgrades[1]
    assert f"global.maintenanceEpoch={epoch}" in commands[upgrades[1]]
    assert "global.businessPaused=false" in commands[upgrades[1]]
    assert {commands[i].split()[2] for i in scales} == {
        f"deployment/nexent-{name}"
        for name in ("config", "runtime", "mcp", "gateway", "northbound", "web", "data-process")
    }


def test_deploy_changes_fixed_runtime_count_only_through_offline_windows(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true"})
    epochs = set()
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
        epoch = next(argument.split("=", 1)[1] for argument in commands[pause].split()
                     if argument.startswith("global.maintenanceEpoch="))
        epochs.add(epoch)
        assert f"global.maintenanceEpoch={epoch}" in commands[activate]
        assert any(line.startswith("kubectl apply -f -") for line in commands[pause:activate])
        assert any(line.startswith("kubectl rollout status deployment/nexent-runtime") for line in commands[activate:])
        assert f"runtimeReplicas: {count}" in (project / "deploy/k8s/deploy.options").read_text(encoding="utf-8")
    assert len(epochs) == 3


@pytest.mark.parametrize("job_state", ["failed", "absent", "running", "foreign"])
def test_maintenance_retry_reuses_paused_epoch_without_touching_an_unowned_job(isolated_k8s_project, job_state):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_FAIL_MAINTENANCE": "true"})
    command = [*_deploy_command(project, scope="nexent"), "--runtime-replicas", "3"]
    failure = _run(command, check=False, env=env)
    assert failure.returncode == 1, failure.stdout + failure.stderr
    original_commands = mock_log.read_text(encoding="utf-8").splitlines()
    pause = next(line for line in original_commands if line.startswith("helm upgrade --install nexent "))
    epoch = next(argument.removeprefix("global.maintenanceEpoch=") for argument in pause.split()
                 if argument.startswith("global.maintenanceEpoch="))
    assert not any("global.businessPaused=false" in line for line in original_commands if line.startswith("helm upgrade"))

    env.update({"MOCK_FAIL_MAINTENANCE": "false", "MOCK_RETRY_JOB_STATE": job_state})
    retry = _run([*command, "--retry-runtime-maintenance", epoch], check=False, env=env)
    commands = mock_log.read_text(encoding="utf-8").splitlines()[len(original_commands):]
    job = f"nexent-runtime-maintenance-{epoch}"
    expected_success = job_state in ("failed", "absent")
    assert retry.returncode == (0 if expected_success else 1), retry.stdout + retry.stderr
    deletions = [index for index, line in enumerate(commands) if line.startswith(f"kubectl delete job {job} ")]
    upgrades = [line for line in commands if line.startswith("helm upgrade --install nexent ")]
    if not expected_success:
        assert not deletions and not upgrades
        assert not any(line.startswith("kubectl apply -f -") for line in commands)
        return
    assert len(upgrades) == 2
    assert all(f"global.maintenanceEpoch={epoch}" in line for line in upgrades)
    assert "global.businessPaused=false" in upgrades[-1]
    apply_index = next(index for index, line in enumerate(commands) if line.startswith("kubectl apply -f -"))
    if job_state == "failed":
        assert len(deletions) == 1 and deletions[0] < apply_index
        assert "--cascade=foreground --wait=true" in commands[deletions[0]]
    else:
        assert not deletions


@pytest.mark.parametrize("mismatch", ["wrong-count", "wrong-epoch", "already-active"])
def test_maintenance_retry_rejects_mismatched_pause_before_job_or_rollout(isolated_k8s_project, mismatch):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true",
                "MOCK_FAIL_MAINTENANCE": "false" if mismatch == "already-active" else "true"})
    command = _deploy_command(project, scope="nexent")
    first = _run(command, check=False, env=env)
    assert first.returncode == (0 if mismatch == "already-active" else 1), first.stdout + first.stderr
    original_commands = mock_log.read_text(encoding="utf-8").splitlines()
    pause = next(line for line in original_commands if line.startswith("helm upgrade --install nexent "))
    epoch = next(argument.removeprefix("global.maintenanceEpoch=") for argument in pause.split()
                 if argument.startswith("global.maintenanceEpoch="))
    if mismatch == "wrong-epoch":
        epoch = "00000000-0000-4000-8000-000000000001"
    count = "2" if mismatch == "wrong-count" else "1"
    retry = _run([*command, "--runtime-replicas", count, "--retry-runtime-maintenance", epoch], check=False, env=env)
    assert retry.returncode == 1, retry.stdout + retry.stderr
    assert "does not match the paused maintenance batch" in retry.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()[len(original_commands):]
    assert not any(line.startswith(("kubectl scale ", "kubectl delete job", "kubectl apply -f -", "helm upgrade "))
                   for line in commands)


def test_existing_rwx_claims_are_checked_before_pause_and_bootstrap_writes(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true"})
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


@pytest.mark.parametrize("mode,failure", [("dynamic", "hostpath"), ("dynamic", "local"),
                                          ("dynamic", "wrong-pv-mode"), ("dynamic", "unavailable"),
                                          ("existing", "rwo"), ("existing", "pending"), ("existing", "missing")])
def test_multi_replica_storage_failures_never_activate_runtime(isolated_k8s_project, mode, failure):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", "MOCK_RUNTIME_STORAGE": failure})
    result = _run([*_deploy_command(project, scope="nexent"), "--persistence-mode", mode, "--runtime-replicas", "3"],
                  check=False, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Error: " in result.stderr and "Runtime" in result.stderr
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
