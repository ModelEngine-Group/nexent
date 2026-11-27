# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment milestones, diagnostics and interactive output use their intended destinations."""

import os
import re
import shutil
import subprocess

import pytest

from .test_workbench_publication import BASH, REPO, run_shell, shell_function


@pytest.mark.parametrize("target,status", [("docker", 0), ("k8s", 17)])
@pytest.mark.parametrize("image_action", ["load", "push"])
def test_entrypoint_keeps_offline_and_platform_output_in_one_private_log(tmp_path, monkeypatch, target, status, image_action):
    monkeypatch.delenv("NEXENT_DEPLOY_LOG_FILE", raising=False)
    monkeypatch.setenv("DEPLOYMENT_LANG", "en")
    root = tmp_path / "offline package"
    for path in ("common", "env", target):
        (root / "deploy" / path).mkdir(parents=True)
    for source in ("deploy.sh", "deploy/deploy.sh", "deploy/common/common.sh"):
        shutil.copyfile(REPO / source, root / source)
    (root / "deploy/env/.env.example").write_text("", encoding="utf-8")
    (root / f"{image_action}-images.sh").write_text(
        f"printf 'image {image_action} details\\n'\n", encoding="utf-8"
    )
    (root / "deploy" / target / "deploy.sh").write_text(
        'source "$(dirname "$0")/../common/common.sh"\n'
        'deployment_start_log "$(cd "$(dirname "$0")/../.." && pwd)"\n'
        'deployment_log "Bootstrap"\n'
        "deployment_run_logged bash -c 'echo SQL details; echo Python details >&2'\n"
        f"exit {status}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [BASH, "deploy.sh", f"--{image_action}-images", "--image-registry-prefix", "registry.example.com/nexent", target],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == status, result.stderr
    log, = (root / "logs/deploy").iterdir()
    assert re.fullmatch(r"deploy-\d{8}-\d{6}\.log", log.name)
    if os.name != "nt":
        assert log.stat().st_mode & 0o777 == 0o600
    output = result.stdout + result.stderr
    assert "Deployment log:" in output and log.name in output
    assert "Bootstrap" in result.stdout
    contents = log.read_text(encoding="utf-8")
    assert "Bootstrap" in contents
    image_details = f"image {image_action} details"
    assert image_details in contents and image_details in result.stdout
    for detail in ("SQL details", "Python details"):
        assert detail in contents and detail not in output
    assert f"Deployment exit status: {status}" in contents
    if status:
        assert f"Deployment failed (exit {status})" in result.stderr


def test_logged_commands_leave_prompts_and_initial_password_on_console(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", (tmp_path / "deployment.log").as_posix())
    result = run_shell(r'''
deployment_run_logged bash -c 'echo "Password prompt" >&"$NEXENT_DEPLOY_PROMPT_FD"; echo "Command output"'
deployment_report_super_admin_creation '{"created":true}' 'SyntheticPassword123' true
''')
    assert result.returncode == 0, result.stderr
    assert "Password prompt" in result.stderr
    assert "SyntheticPassword123" in result.stdout
    contents = (tmp_path / "deployment.log").read_text(encoding="utf-8")
    assert "Command output" in contents and '{"created":true}' in contents
    assert "Password prompt" not in contents and "SyntheticPassword123" not in contents


@pytest.mark.parametrize("shell_options", ["set -e", "set -euo pipefail"])
@pytest.mark.parametrize("status", [0, 17])
def test_visible_commands_mirror_output_and_preserve_status(tmp_path, monkeypatch, shell_options, status):
    log = tmp_path / "deployment log.txt"
    log.write_text("Earlier stage\n", encoding="utf-8")
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.delenv("NEXENT_DEPLOY_PROMPT_FD", raising=False)
    result = run_shell(shell_options + r'''
deployment_run_visible bash -c '
  echo "Registry password prompt" >&"$NEXENT_DEPLOY_PROMPT_FD"
  echo "Command output"
  echo "Command diagnostic" >&2
  exit "$1"
' cli-fixture ''' + str(status))

    assert result.returncode == status, result.stderr
    output = result.stdout + result.stderr
    assert "Registry password prompt" in result.stderr
    contents = log.read_text(encoding="utf-8")
    assert contents.startswith("Earlier stage\n")
    assert "Registry password prompt" not in contents
    for detail in ("Command output", "Command diagnostic"):
        assert output.count(detail) == 1
        assert contents.count(detail) == 1


@pytest.mark.parametrize("compose_command", ["docker compose", "docker-compose"])
@pytest.mark.parametrize("compose_status,detail", [
    (0, "Container nexent-postgresql Started"),
    (17, "Compose failed to start the container"),
])
def test_compose_startup_output_is_visible(tmp_path, monkeypatch, compose_command, compose_status, detail):
    log = tmp_path / "deployment.log"
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.setenv("docker_compose_command", compose_command)
    monkeypatch.setenv("COMPOSE_PROGRESS", "quiet")
    monkeypatch.setenv("COMPOSE_ANSI", "always")
    monkeypatch.setenv("FIXTURE_COMPOSE_STATUS", str(compose_status))
    monkeypatch.setenv("FIXTURE_COMPOSE_DETAIL", detail)
    result = run_shell(shell_function("docker", "deploy_infrastructure") + r'''
DEPLOYMENT_COMPONENTS=infrastructure
ROOT_ENV_FILE="/deployment with spaces/.env"
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
docker() { [ "$1" = compose ] || return 9; shift; docker-compose "$@"; }
docker-compose() {
  [ "$2" = "$ROOT_ENV_FILE" ] && [ "$7" = up ] && [ "$8" = -d ] || return 9
  case "$docker_compose_command:$COMPOSE_PROGRESS:$COMPOSE_ANSI" in
    'docker compose:plain:never'|'docker-compose:quiet:always') ;;
    *) printf 'Unexpected Compose mode: %s/%s\n' "$COMPOSE_PROGRESS" "$COMPOSE_ANSI" >&2; return 9 ;;
  esac
  echo 'Compose is starting infrastructure containers'
  printf '%s\n' "$FIXTURE_COMPOSE_DETAIL" >&2
  return "$FIXTURE_COMPOSE_STATUS"
}
status=0
deploy_infrastructure || status=$?
printf 'Caller Compose mode: %s/%s\n' "$COMPOSE_PROGRESS" "$COMPOSE_ANSI"
exit "$status"
''')

    assert result.returncode == (1 if compose_status else 0), result.stdout + result.stderr
    assert ("Failed to start infrastructure services" in result.stdout) == bool(compose_status)
    assert "Caller Compose mode: quiet/always" in result.stdout
    for destination in (result.stdout + result.stderr, log.read_text(encoding="utf-8")):
        assert "Compose is starting infrastructure containers" in destination
        assert detail in destination
        assert f"+ {compose_command}" not in destination


@pytest.mark.parametrize("compose_status", [0, 17])
def test_workbench_publication_output_stays_in_deploy_log(tmp_path, monkeypatch, compose_status):
    log = tmp_path / "deployment.log"
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.setenv("FIXTURE_COMPOSE_STATUS", str(compose_status))
    result = run_shell(shell_function("docker", "publish_shared_workbench") + r'''
docker_compose_command='docker compose'
DEPLOYMENT_SELECTED_DOCKER_SERVICES=nexent-config
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
docker() {
  [ "$1" = compose ] && [ "$8" = run ] || return 9
  echo '[sql-migrations] apply __init.sql'
  echo '{"released": 1}'
  echo 'Python Workbench diagnostic' >&2
  return "$FIXTURE_COMPOSE_STATUS"
}
publish_shared_workbench
''')

    output = result.stdout + result.stderr
    assert result.returncode == (1 if compose_status else 0), output
    assert "Applying database migrations and publishing shared Workbench" in result.stdout
    assert ("Shared Workbench initialization or publication failed" in output) == bool(compose_status)
    contents = log.read_text(encoding="utf-8")
    for detail in ("[sql-migrations] apply __init.sql", '{"released": 1}', "Python Workbench diagnostic"):
        assert detail in contents and detail not in output


def test_compose_cleanup_output_is_visible_after_stop_failure(tmp_path, monkeypatch):
    log = tmp_path / "deployment.log"
    (tmp_path / "docker-compose.yml").write_text("", encoding="utf-8")
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.setenv("COMPOSE_DIR", tmp_path.as_posix())
    result = run_shell(shell_function("docker", "stop_unselected_data_process_service") + r'''
docker_compose_command='docker compose'
DEPLOYMENT_COMPONENTS=infrastructure
ROOT_ENV_FILE=/deployment/.env
COMPOSE_FILE_SUFFIX=.yml
docker() {
  [ "$1" = compose ] || return 9
  case "$8:${9:-}:${10:-}" in
    stop:nexent-data-process:) echo 'Compose could not stop data-process' >&2; return 17 ;;
    rm:-f:nexent-data-process) echo 'Compose removed data-process' ;;
    *) return 9 ;;
  esac
}
stop_unselected_data_process_service
''')

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for destination in (output, log.read_text(encoding="utf-8")):
        assert destination.index("Compose could not stop data-process") < destination.index("Compose removed data-process")


def test_rollout_diagnostics_are_visible_on_failure(tmp_path, monkeypatch):
    log = tmp_path / "deployment.log"
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    result = run_shell(shell_function("k8s", "wait_for_deployment_ready") + r'''
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=7
kubectl() {
  printf '%s\n' "$*"
  echo 'Rollout timed out' >&2
  return 17
}
wait_for_deployment_ready nexent-runtime
''')

    assert result.returncode == 17, result.stderr
    output = result.stdout + result.stderr
    contents = log.read_text(encoding="utf-8")
    for detail in ("rollout status deployment/nexent-runtime -n test-ns --timeout=7s", "Rollout timed out"):
        assert detail in output and detail in contents


@pytest.mark.parametrize("function,arguments,helm_prefix", [
    ("helm_upgrade_application_release", "true test-bootstrap", "upgrade --install nexent"),
    ("helm_upgrade_infrastructure_release", "", "upgrade --install nexent-infrastructure"),
    ("deploy_application_release", "", "upgrade nexent"),
])
@pytest.mark.parametrize("helm_status", [0, 17])
def test_helm_release_output_is_visible(tmp_path, monkeypatch, function, arguments, helm_prefix, helm_status):
    log = tmp_path / "deployment.log"
    password = "SyntheticHelmPassword123"
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.setenv("FIXTURE_HELM_PREFIX", helm_prefix)
    monkeypatch.setenv("FIXTURE_HELM_STATUS", str(helm_status))
    monkeypatch.setenv("SSH_PASSWORD", password)
    definitions = "\n".join(shell_function("k8s", name) for name in ("helm_application_chart", function))
    result = run_shell(definitions + r'''
APPLICATION_RELEASE_NAME=nexent
APPLICATION_CHART_DIR=/charts/nexent
INFRASTRUCTURE_RELEASE_NAME=nexent-infrastructure
INFRASTRUCTURE_CHART_DIR=/charts/nexent-infrastructure
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=7
DIRECT_UPGRADE=true
DEPLOYMENT_COMPONENTS=application
RUNTIME_REPLICAS=1
start_runtime_deploy_lock() { return 0; }
require_direct_upgrade_target() { return 0; }
require_previous_deployment_jobs_stopped() { return 0; }
require_runtime_deploy_lock() { return 0; }
wait_for_nexent_ready() { return 0; }
helm() {
  if [ "$1" = template ]; then
    printf 'Rendered manifest with %s\n' "$SSH_PASSWORD"
    return 0
  fi
  [[ "$*" == "$FIXTURE_HELM_PREFIX "* ]] || return 9
  echo 'Helm release progress'
  if [ "$FIXTURE_HELM_STATUS" -ne 0 ]; then
    echo 'Helm release failed' >&2
  fi
  return "$FIXTURE_HELM_STATUS"
}
''' + f"{function} {arguments}\n")

    expected_status = bool(helm_status) if function == "deploy_application_release" else helm_status
    output = result.stdout + result.stderr
    assert result.returncode == expected_status, output
    for destination in (output, log.read_text(encoding="utf-8")):
        assert "Helm release progress" in destination
        assert ("Helm release failed" in destination) == bool(helm_status)
        assert password not in destination and "Rendered manifest" not in destination


@pytest.mark.parametrize("job_status,exit_status", [("1:0", 0), ("0:1", 1)])
def test_bootstrap_job_logs_are_collected_on_success_and_failure(tmp_path, monkeypatch, job_status, exit_status):
    log = tmp_path / "deployment.log"
    monkeypatch.setenv("NEXENT_DEPLOY_LOG_FILE", log.as_posix())
    monkeypatch.setenv("FIXTURE_JOB_STATUS", job_status)
    result = run_shell(shell_function("k8s", "bootstrap_job_failed") + "\n" +
                       shell_function("k8s", "run_system_agent_bootstrap") + r'''
NAMESPACE=test-ns
APPLICATION_RELEASE_NAME=nexent
K8S_WAIT_TIMEOUT_SECONDS=7
require_runtime_deploy_lock() { return 0; }
sync_official_skills_to_workspace() { return 0; }
kubectl() {
  case "$1:$2" in
    get:jobs) echo bootstrap-7 ;;
    get:pods) echo bootstrap-pod ;;
    get:job)
      case "$*" in *status.succeeded*) echo "$FIXTURE_JOB_STATUS" ;; *) echo 0 ;; esac ;;
    logs:*) echo 'Job SQL and Python details' ;;
    delete:job) echo 'Cleaned up failed Job' >&2 ;;
    exec:*) return 0 ;;
    *) return 9 ;;
  esac
}
run_system_agent_bootstrap test-id
''')
    assert result.returncode == exit_status, result.stderr
    assert "Job SQL and Python details" not in result.stdout + result.stderr
    contents = log.read_text(encoding="utf-8")
    assert "Job SQL and Python details" in contents
    assert ("Cleaned up failed Job" in contents) == bool(exit_status)
    assert ("Cleaned up failed Job" in result.stdout + result.stderr) == bool(exit_status)
    assert ("Business workloads remain paused" in result.stderr) == bool(exit_status)
