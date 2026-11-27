# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pause/bootstrap/activate sequencing without mutating a Kubernetes cluster."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from .test_workbench_publication import BASH, run_shell, shell_function


def run(script):
    return run_shell(script)


def test_config_deployment_launches_as_python_module():
    helm = shutil.which("helm")
    assert helm, "Helm is required for Kubernetes deployment template tests"
    chart = Path(__file__).resolve().parents[3] / "deploy/k8s/helm/nexent"
    result = subprocess.run(
        [helm, "template", "nexent", str(chart),
         "--show-only", "charts/nexent-config/templates/deployment.yaml",
         "--set", "nexent-runtime.replicaCount=1",
         "--set", "global.sandboxProvider=docker",
         "--set-string", "nexent-common.secrets.jwtSecret=test-config-launch"],
        check=False, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load(result.stdout)["spec"]["template"]["spec"]["containers"][0]
    assert config["command"] == [
        "/opt/nexent/scripts/start-backend.sh", "python", "-m", "backend.http.config_service"
    ]


@pytest.mark.parametrize(
    "previous,chart,saved,explicit,expected",
    [
        ("", "3", "1", "", "3"),
        ("", "1", "3", "", "3"),
        ("3", "1", "3", "", "1"),
        ("3", "3", "2", "", "2"),
        ("3", "unset", "2", "", "2"),
        ("1", "3", "2", "true", "2"),
        ("1", "invalid", "1", "", "invalid"),
        ("invalid", "invalid", "1", "", "invalid"),
        ("1", "invalid", "2", "true", "2"),
        ("1", "", "1", "", ""),
    ],
)
def test_resolve_runtime_replicas_from_chart_and_saved_options(previous, chart, saved, explicit, expected):
    result = subprocess.run(
        [BASH, "-c", shell_function("k8s", "resolve_runtime_replicas") + r'''
SAVED_RUNTIME_CHART_REPLICAS="$1"
RUNTIME_REPLICAS="$3"
K8S_RUNTIME_REPLICAS_EXPLICIT="$4"
candidate="$2"
read_runtime_chart_replicas() { printf '%s\n' "$candidate"; }
resolve_runtime_replicas && printf '%s:%s\n' "$RUNTIME_REPLICAS" "$SAVED_RUNTIME_CHART_REPLICAS"
''', "replica-resolution", previous, chart, saved, explicit],
        check=False, capture_output=True, text=True, timeout=20,
    )
    if not expected:
        assert result.returncode == 1
        assert "unable to read nexent-runtime.replicaCount" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{expected}:{chart}"


@pytest.mark.parametrize("source,expected", [("hostPath", 0), ("local", 1)])
def test_runtime_volume_source_validation(source, expected):
    result = subprocess.run(
        [BASH, "-c", shell_function("k8s", "require_runtime_rwx_claim") + r'''
NAMESPACE=nexent
source_type="$1"
kubectl() {
    if [ "$2" = pvc ]; then
        printf 'Bound:workspace-pv:ReadWriteMany,:Filesystem'
        return
    fi
    printf 'Bound:ReadWriteMany,:Filesystem:'
    if [[ "$*" == *'.spec.hostPath.path'* ]]; then
        if [ "$source_type" = hostPath ]; then printf '/mnt/k8s-shared'; fi
        printf ':'
    fi
    if [ "$source_type" = local ]; then printf '/var/lib/nexent'; fi
    return 0
}
require_runtime_rwx_claim nexent-workspace
''', "volume-validation", source],
        check=False, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == expected, result.stderr
    if source == "local":
        assert "uses spec.local" in result.stderr


@pytest.mark.parametrize(
    "failure", ["", "validate", "lock", "previous-writer", "stop", "pause", "bootstrap", "lock-before-activation",
                "activate", "ready"]
)
def test_application_stays_paused_until_bootstrap_success(failure):
    result = run(shell_function("k8s", "deploy_application_release") + r'''
DEPLOYMENT_COMPONENTS=application
failure="''' + failure + r'''"
deployment_csv_contains() { return 0; }
stage() { echo "EVENT:$1"; [ "$failure" != "$1" ]; }
validate_application_release() { stage validate; }
start_runtime_deploy_lock() { stage lock; }
require_previous_deployment_jobs_stopped() { stage previous-writer; }
bootstrap_completed=false
require_runtime_deploy_lock() {
  [ "$#" = 0 ] || return 1
  if [ "$bootstrap_completed" = true ]; then
    bootstrap_completed=false
    stage lock-before-activation
  fi
}
stop_old_business_workloads() { stage stop; }
helm_upgrade_application_release() {
  if [ "$1" = true ]; then
    [ -n "$2" ] && stage pause
  else
    [ -z "$2" ] && stage activate
  fi
}
run_system_agent_bootstrap() { stage bootstrap && bootstrap_completed=true; }
wait_for_nexent_ready() { stage ready; }
deploy_application_release
''')
    expected = ["validate", "lock", "previous-writer", "stop", "pause", "bootstrap", "lock-before-activation",
                "activate", "ready"]
    if failure:
        expected = expected[:expected.index(failure) + 1]
    assert [line for line in result.stdout.splitlines() if line.startswith("EVENT:")] == [
        "EVENT:" + item for item in expected
    ]
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
    assert result.stdout.splitlines() == ["HELM:false", "Waiting for the application workloads...", "READY"]


@pytest.mark.parametrize(
    "jobs,pods,failing_list,blocked_by",
    [
        ("", "", "", ""),
        ("bootstrap-old:True:\nmaintenance-old::True", "bootstrap-pod:Succeeded\nmaintenance-pod:Failed", "", ""),
        ("bootstrap-old::", "", "", "Job test-ns/bootstrap-old"),
        ("maintenance-old:False:False", "", "", "Job test-ns/maintenance-old"),
        ("maintenance-old::True", "terminating-pod:Running", "", "Pod test-ns/terminating-pod"),
        ("", "orphaned-pod:Pending", "", "Pod test-ns/orphaned-pod"),
        ("", "unscheduled-pod:", "", "Pod test-ns/unscheduled-pod"),
        ("", "", "jobs", "API"),
        ("", "", "pods", "API"),
    ],
)
def test_previous_deployment_jobs_must_be_terminal_before_business_stops(jobs, pods, failing_list, blocked_by):
    result = run(shell_function("k8s", "require_previous_deployment_jobs_stopped") + f"""
NAMESPACE=test-ns
APPLICATION_RELEASE_NAME=target-release
job_rows='{jobs}'
pod_rows='{pods}'
failing_list='{failing_list}'
""" + r'''
kubectl() {
  if [ "$1" != get ] || [ "$3 $4 $5" != '-n test-ns -l' ] ||
      [ "$6" != 'app in (nexent-system-bootstrap,nexent-runtime-maintenance),app.kubernetes.io/instance=target-release' ]; then
    echo 'Unexpected mutation or unscoped lookup' >&2; return 1
  fi
  echo "QUERY:$2" >&2
  if [ "$2" = "$failing_list" ]; then echo 'API error' >&2; return 8; fi
  case "$2" in jobs) printf '%s\n' "$job_rows" ;; pods) printf '%s\n' "$pod_rows" ;; *) return 2 ;; esac
}
require_previous_deployment_jobs_stopped
''')
    assert result.returncode == (1 if blocked_by else 0), result.stderr
    assert "Unexpected" not in result.stderr
    expected = ["QUERY:jobs"] if blocked_by.startswith("Job ") or failing_list == "jobs" else ["QUERY:jobs", "QUERY:pods"]
    assert [line for line in result.stderr.splitlines() if line.startswith("QUERY:")] == expected
    if blocked_by:
        assert blocked_by in result.stderr


@pytest.mark.parametrize(
    "fresh,failure",
    [(True, ""), (True, "pods"), (False, ""), (False, "scale"), (False, "deployment-api"),
     (False, "pods"), (False, "data-process-pod")],
)
def test_shutdown_waits_for_business_pods_and_never_scales_infrastructure(fresh, failure):
    result = run(shell_function("k8s", "stop_old_business_workloads") + r'''
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=0
fresh="''' + str(fresh).lower() + r'''"
failure="''' + failure + r'''"
kubectl() {
  printf 'KUBE:%s\n' "$*" >&2
  if [ "$1 $2" = 'get deployment' ]; then
    if [[ "$*" = *observedGeneration* ]]; then
      if [ "$failure" = deployment-api ]; then return 7; fi
      echo '2:2:0:'
    elif [ "$fresh" = false ]; then
      echo "deployment/$3"
    fi
  elif [ "$1" = scale ]; then
    [ "$failure" != scale ] || return 7
  elif [ "$1 $2" = 'get pods' ]; then
    if [[ "$failure" = pods || ( "$failure" = data-process-pod && "$*" = *"app=nexent-data-process"* ) ]]; then
      echo pod/still-running
    fi
  fi
}
stop_old_business_workloads
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    business = [
        "nexent-gateway", "nexent-web", "nexent-northbound", "nexent-config", "nexent-runtime", "nexent-mcp",
        "nexent-data-process",
    ]
    scales = [line for line in result.stderr.splitlines() if line.startswith("KUBE:scale")]
    scaled = [] if fresh else business[:1] if failure == "scale" else business
    assert scales == [f"KUBE:scale deployment/{deployment} -n test-ns --replicas=0" for deployment in scaled]
    pod_checks = [line for line in result.stderr.splitlines() if line.startswith("KUBE:get pods")]
    checked = [] if failure in ("scale", "deployment-api") else business[:1] if failure == "pods" else business
    assert pod_checks == [f"KUBE:get pods -n test-ns -l app={deployment} -o name" for deployment in checked]
    if failure == "data-process-pod":
        assert "old nexent-data-process Pods did not stop; migration will not run" in result.stderr


@pytest.mark.parametrize("initial_state", ["2:1:0:", "2:2:0:1", "2::0:", "2:2:1:"])
@pytest.mark.parametrize("reconciles", [False, True])
def test_shutdown_requires_reconciled_zero_before_trusting_an_empty_pod_list(initial_state, reconciles):
    result = run(shell_function("k8s", "stop_old_business_workloads") + r'''
NAMESPACE=test-ns
K8S_WAIT_TIMEOUT_SECONDS=2
controller_state="''' + initial_state + r'''"
reconciles="''' + str(reconciles).lower() + r'''"
kubectl() {
  case "$1 $2 $3" in
    "get deployment nexent-runtime")
      if [[ "$*" = *observedGeneration* ]]; then echo "STATE:$controller_state" >&2; printf '%s' "$controller_state";
      else echo deployment/nexent-runtime; fi ;;
    "get pods -n")
      if [[ "$*" = *app=nexent-runtime* ]]; then echo "RUNTIME_PODS:$controller_state" >&2; fi ;;
  esac
  return 0
}
sleep() { if [ "$reconciles" = true ]; then controller_state='2:2:0:'; fi; }
stop_old_business_workloads
''')
    assert result.returncode == (0 if reconciles else 1), result.stderr
    lines = result.stderr.splitlines()
    assert f"STATE:{initial_state}" in lines
    assert f"RUNTIME_PODS:{initial_state}" not in lines
    if reconciles:
        assert lines.index("STATE:2:2:0:") < lines.index("RUNTIME_PODS:2:2:0:")
    else:
        assert "old nexent-runtime Pods did not stop; migration will not run" in result.stderr


@pytest.mark.parametrize("failure", ["", "job", "ready_timeout", "copy", "lock_before_copy", "lock_after_copy",
                                    "start", "complete", "complete_timeout"])
def test_job_gates_sql_on_skill_sync_and_fails_closed(failure):
    result = run(shell_function("k8s", "run_system_agent_bootstrap") + r'''
NAMESPACE=test-ns
APPLICATION_RELEASE_NAME=nexent
K8S_WAIT_TIMEOUT_SECONDS=2
failure="''' + failure + r'''"
sleep() { return 0; }
synced=false
require_runtime_deploy_lock() {
  ! [[ ( "$failure" = lock_before_copy && "$synced" = false ) ||
       ( "$failure" = lock_after_copy && "$synced" = true ) ]]
}
sync_official_skills_to_workspace() { synced=true; echo "SYNC:$1"; [ "$failure" != copy ]; }
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
run_system_agent_bootstrap expected-bootstrap-id
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    if failure.startswith("lock_"):
        assert "FAILED:bootstrap-7" not in result.stdout
        assert ("SYNC:bootstrap-pod" in result.stdout) == (failure == "lock_after_copy")
    elif failure:
        assert "FAILED:bootstrap-7" in result.stdout
    else:
        assert "SYNC:bootstrap-pod" in result.stdout.splitlines()
    assert "nexent.io/bootstrap-run-id=expected-bootstrap-id" in result.stderr
    if failure in ("job", "ready_timeout", "copy", "lock_before_copy", "lock_after_copy"):
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
    assert "Business workloads remain paused" in result.stderr
