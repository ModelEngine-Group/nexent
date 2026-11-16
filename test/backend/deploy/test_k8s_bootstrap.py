# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pause/bootstrap/activate sequencing without mutating a Kubernetes cluster."""

import subprocess

import pytest

from .test_workbench_publication import BASH, shell_function


def run(script):
    return subprocess.run([BASH, "-c", script], check=False, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("failure", ["", "validate", "stop", "pause", "bootstrap", "activate", "ready"])
def test_application_stays_paused_until_bootstrap_success(failure):
    result = run(shell_function("k8s", "deploy_application_release") + r'''
DEPLOYMENT_COMPONENTS=application
failure="''' + failure + r'''"
deployment_csv_contains() { return 0; }
stage() { echo "EVENT:$1"; [ "$failure" != "$1" ]; }
validate_application_release() { stage validate; }
stop_old_business_workloads() { stage stop; }
helm_upgrade_application_release() { if [ "$1" = true ]; then stage pause; else stage activate; fi; }
run_system_agent_bootstrap() { stage bootstrap; }
wait_for_nexent_ready() { stage ready; }
deploy_application_release
''')
    expected = ["validate", "stop", "pause", "bootstrap", "activate", "ready"]
    if failure:
        expected = expected[:expected.index(failure) + 1]
    assert result.stdout.splitlines() == ["EVENT:" + item for item in expected]
    assert result.returncode == (1 if failure else 0)


def test_non_application_selection_does_not_stop_application_or_run_bootstrap():
    result = run(shell_function("k8s", "deploy_application_release") + r'''
DEPLOYMENT_COMPONENTS=data-process
deployment_csv_contains() { return 1; }
validate_application_release() { return 0; }
stop_old_business_workloads() { echo UNEXPECTED; return 1; }
run_system_agent_bootstrap() { echo UNEXPECTED; return 1; }
helm_upgrade_application_release() { echo "HELM:$1"; }
wait_for_nexent_ready() { echo READY; }
deploy_application_release
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["HELM:false", "READY"]


@pytest.mark.parametrize("fresh,failure", [(True, ""), (False, ""), (False, "scale"), (False, "pods")])
def test_shutdown_waits_for_business_pods_and_never_scales_infrastructure(fresh, failure):
    result = run(shell_function("k8s", "stop_old_business_workloads") + r'''
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=0
fresh="''' + str(fresh).lower() + r'''"
failure="''' + failure + r'''"
kubectl() {
  printf 'KUBE:%s\n' "$*" >&2
  if [ "$1 $2" = 'get deployment' ]; then
    [ "$fresh" = true ] || echo "deployment/$3"
  elif [ "$1" = scale ]; then
    [ "$failure" != scale ] || return 7
  elif [ "$1 $2" = 'get pods' ]; then
    [ "$failure" != pods ] || echo pod/still-running
  fi
}
stop_old_business_workloads
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    scales = [line for line in result.stderr.splitlines() if line.startswith("KUBE:scale")]
    if fresh:
        assert not scales
    elif not failure:
        assert len(scales) == 6
        assert all("--replicas=0" in line for line in scales)
        assert len([line for line in result.stderr.splitlines() if line.startswith("KUBE:get pods")]) == 6
    assert not any(resource in line for line in scales for resource in ("postgres", "redis", "minio", "elasticsearch", "supabase"))


@pytest.mark.parametrize("failure", ["", "job", "ready_timeout", "copy", "start", "complete", "complete_timeout"])
def test_job_gates_sql_on_skill_sync_and_fails_closed(failure):
    result = run(shell_function("k8s", "run_system_agent_bootstrap") + r'''
NAMESPACE=test-ns
APPLICATION_RELEASE_NAME=nexent
K8S_WAIT_TIMEOUT_SECONDS=2
failure="''' + failure + r'''"
sleep() { return 0; }
sync_official_skills_to_workspace() { echo "SYNC:$1"; [ "$failure" != copy ]; }
bootstrap_job_failed() { echo "FAILED:$1"; return 1; }
kubectl() {
  printf 'KUBE:%s\n' "$*" >&2
  if [ "$1 $2" = 'get jobs' ]; then
    echo bootstrap-7
  elif [ "$1 $2" = 'get job' ]; then
    if [[ "$*" == *succeeded* ]]; then
      case "$failure" in complete) echo ':1' ;; complete_timeout) echo ':' ;; *) echo '1:' ;; esac
    elif [ "$failure" = job ]; then echo 1; fi
  elif [ "$1 $2" = 'get pods' ]; then
    [ "$failure" = ready_timeout ] || echo bootstrap-pod
  elif [ "$1" = exec ]; then
    [ "$failure" != start ] || return 8
  fi
}
run_system_agent_bootstrap
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    if failure:
        assert "FAILED:bootstrap-7" in result.stdout
    else:
        assert result.stdout.splitlines() == ["SYNC:bootstrap-pod"]
    if failure in ("job", "ready_timeout", "copy"):
        assert "nexent-bootstrap-start" not in result.stderr
    else:
        assert "nexent-bootstrap-start" in result.stderr


@pytest.mark.parametrize("logs_fail", [False, True])
def test_failed_job_logs_and_cleanup_never_activate_business(logs_fail):
    result = run(shell_function("k8s", "bootstrap_job_failed") + r'''
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=7
kubectl() {
  printf 'KUBE:%s\n' "$*" >&2
  if [ "$1" = logs ]; then return ''' + str(3 if logs_fail else 0) + r'''; fi
}
bootstrap_job_failed bootstrap-7
''')
    assert result.returncode == 1
    assert "logs -n test-ns job/bootstrap-7" in result.stderr
    assert "delete job bootstrap-7 -n test-ns --wait=true --timeout=7s" in result.stderr
    assert "business workloads remain paused" in result.stderr
