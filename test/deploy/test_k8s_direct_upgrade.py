# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check direct Helm upgrade sequencing against isolated deployment commands."""

from pathlib import Path

import pytest

from test_k8s_helm import _deploy_command, _run
from test_k8s_helm import isolated_k8s_project as _isolated_project


isolated_k8s_project = _isolated_project


def _direct_command(project: Path, *, scope: str | None, mode: str, replicas: int | None) -> list[str]:
    command = _deploy_command(project, scope=scope or "all")
    if scope is None:
        scope_flag = command.index("--release-scope")
        del command[scope_flag:scope_flag + 2]
    command.extend(["--direct-upgrade", "--persistence-mode", mode])
    if replicas is not None:
        command.extend(["--runtime-replicas", str(replicas)])
    return command


def _assert_no_pause(commands: list[str]) -> None:
    assert not any(command.startswith(("kubectl scale ", "kubectl cp ")) for command in commands)
    assert not any("businessPaused=true" in command or "nexent-bootstrap-start" in command for command in commands)
    assert not any(command.startswith("helm upgrade --install nexent ") for command in commands)


def _config_state_checks(commands: list[str]) -> list[int]:
    return [
        index for index, command in enumerate(commands)
        if command.startswith("kubectl get deployment nexent-config ")
        and "/release-name" in command and ".spec.replicas" in command
    ]


@pytest.mark.parametrize(("scope", "mode", "replicas"), [
    (None, "dynamic", 4),
    ("nexent", "existing", 3),
    ("nexent", "local", 1),
])
def test_direct_upgrade_applies_once_and_waits_for_configured_replicas(isolated_k8s_project, scope, mode, replicas):
    project, env, mock_log = isolated_k8s_project
    env.update({
        "MOCK_APP_EXISTS": "true",
        "MOCK_INFRA_EXISTS": "true",
        "MOCK_CHART_RUNTIME_REPLICAS": str(replicas),
    })
    command = _direct_command(project, scope=scope, mode=mode, replicas=replicas if scope else None)
    if mode == "existing":
        command.extend(["--existing-claim-prefix", "shared"])

    result = _run(command, check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    _assert_no_pause(commands)
    active, = [index for index, command in enumerate(commands) if command.startswith("helm upgrade nexent ")]
    assert "global.businessPaused=false" in commands[active]
    assert "global.bootstrapRunId=" in commands[active].split()
    assert f"nexent-runtime.replicaCount={replicas}" in commands[active].split()
    assert sum(command.startswith("helm template nexent ") for command in commands) == 1

    first_check, locked_check = _config_state_checks(commands)
    lock = next(index for index, command in enumerate(commands) if "pg_try_advisory_lock" in command)
    previous_jobs = next(index for index, command in enumerate(commands) if command.startswith("kubectl get jobs "))
    assert first_check < lock < locked_check < active
    assert lock < previous_jobs < active
    infra = [
        index for index, command in enumerate(commands)
        if command.startswith("helm upgrade --install nexent-infrastructure ")
    ]
    if scope is None:
        infra_upgrade, = infra
        assert first_check < infra_upgrade < active
    else:
        assert not infra

    claims = {command.split()[3] for command in commands[:active] if command.startswith("kubectl get pvc ")}
    volumes = {
        command.split()[3] for command in commands[:active]
        if command.startswith("kubectl get pv pv-")
    }
    expected_claims = set()
    if replicas > 1:
        prefix = "shared-" if mode == "existing" else ""
        expected_claims = {
            f"{prefix}nexent-workspace", f"{prefix}nexent-skills", f"{prefix}nexent-logs",
            "nexent-memory-plugins", "nexent-trajectory",
        }
    assert claims == expected_claims
    assert volumes == {f"pv-{claim}" for claim in expected_claims}
    ready = next(index for index, command in enumerate(commands)
                 if command.startswith("kubectl rollout status deployment/nexent-runtime "))
    assert active < ready
    assert any("pg_locks" in command for command in commands[ready + 1:])


@pytest.mark.parametrize(("settings", "message"), [
    ({"MOCK_APP_EXISTS": "false"}, "requires an existing 'nexent' Helm release"),
    ({"MOCK_MISSING_CONFIG": "true"}, "requires an active nexent-config Deployment"),
    ({"MOCK_CONFIG_REPLICAS": "0"}, "requires an active nexent-config Deployment"),
    ({"MOCK_CONFIG_OWNER": "other-release"}, "requires an active nexent-config Deployment"),
    ({"MOCK_CONFIG_NAMESPACE": "other-namespace"}, "requires an active nexent-config Deployment"),
])
def test_direct_upgrade_rejects_ineligible_release_before_cluster_mutation(isolated_k8s_project, settings, message):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", **settings})

    result = _run(_direct_command(project, scope=None, mode="dynamic", replicas=4), check=False, env=env)

    assert result.returncode != 0
    assert message in result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert all(command.startswith(("helm status ", "helm get ", "helm template ", "kubectl get "))
               for command in commands)


@pytest.mark.parametrize(("mode", "settings", "message", "upgraded", "waited"), [
    ("dynamic", {"MOCK_FAIL_LOCK": "true"}, "holds the Runtime deployment lock", False, False),
    ("dynamic", {"MOCK_FAIL_PREVIOUS_WRITER": "true"}, "is not terminal", False, False),
    ("dynamic", {"MOCK_RUNTIME_STORAGE": "rwo"}, "must be Bound with ReadWriteMany", False, False),
    ("existing", {"MOCK_RUNTIME_STORAGE": "pv-block"}, "Filesystem volume mode", False, False),
    ("dynamic", {"MOCK_FAIL_DIRECT_UPGRADE": "true"}, "application deployment failed", True, False),
    ("dynamic", {"MOCK_FAIL_ROLLOUT": "nexent-runtime"}, "nexent-runtime did not become ready", True, True),
    ("dynamic", {"MOCK_FAIL_DIRECT_LOCK_LOSS": "true"}, "deployment lock could not be verified", True, True),
])
def test_direct_upgrade_reports_failure_without_running_paused_path(
    isolated_k8s_project, mode, settings, message, upgraded, waited,
):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true", **settings})

    result = _run(_direct_command(project, scope="nexent", mode=mode, replicas=4), check=False, env=env)

    assert result.returncode != 0
    assert message in result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    _assert_no_pause(commands)
    assert sum(command.startswith("helm upgrade nexent ") for command in commands) == int(upgraded)
    assert any(command.startswith("kubectl rollout status deployment/nexent-runtime ")
               for command in commands) is waited


def test_direct_upgrade_keeps_infrastructure_only_scope(isolated_k8s_project):
    project, env, mock_log = isolated_k8s_project

    result = _run(_direct_command(project, scope="infrastructure", mode="dynamic", replicas=4), check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(command.startswith("helm upgrade --install nexent-infrastructure ") for command in commands) == 1
    assert not any(command.startswith("helm upgrade nexent ") for command in commands)
    _assert_no_pause(commands)
