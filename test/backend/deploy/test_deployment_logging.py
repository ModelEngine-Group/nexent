# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment milestones, diagnostics and interactive output use their intended destinations."""

import os
import shutil
import subprocess

import pytest

from .test_workbench_publication import BASH, REPO, run_shell, shell_function


@pytest.mark.parametrize("target,status", [("docker", 0), ("k8s", 17)])
def test_entrypoint_keeps_offline_and_platform_output_in_one_private_log(tmp_path, monkeypatch, target, status):
    monkeypatch.delenv("NEXENT_DEPLOY_LOG_FILE", raising=False)
    monkeypatch.setenv("DEPLOYMENT_LANG", "en")
    root = tmp_path / "offline package"
    for path in ("common", "env", target):
        (root / "deploy" / path).mkdir(parents=True)
    for source in ("deploy.sh", "deploy/deploy.sh", "deploy/common/common.sh"):
        shutil.copyfile(REPO / source, root / source)
    (root / "deploy/env/.env.example").write_text("", encoding="utf-8")
    (root / "load-images.sh").write_text("printf 'image loader details\\n'\n", encoding="utf-8")
    (root / "deploy" / target / "deploy.sh").write_text(
        'source "$(dirname "$0")/../common/common.sh"\n'
        'deployment_start_log "$(cd "$(dirname "$0")/../.." && pwd)"\n'
        'deployment_log "Bootstrap"\n'
        "deployment_run_logged bash -c 'echo SQL details; echo Python details >&2'\n"
        f"exit {status}\n",
        encoding="utf-8",
    )
    result = subprocess.run([BASH, "deploy.sh", "--load-images", target], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == status, result.stderr
    log, = (root / "logs/deploy").iterdir()
    if os.name != "nt":
        assert log.stat().st_mode & 0o777 == 0o600
    output = result.stdout + result.stderr
    assert "Deployment log:" in output and log.name in output
    assert "Bootstrap" in result.stdout
    contents = log.read_text(encoding="utf-8")
    assert "Bootstrap" in contents
    for detail in ("image loader details", "SQL details", "Python details"):
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
    assert ("Business workloads remain paused" in result.stderr) == bool(exit_status)
