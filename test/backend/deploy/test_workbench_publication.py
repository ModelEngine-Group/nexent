# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment hook regression tests with isolated container/cluster commands."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash") if os.name != "nt" else "C:/Program Files/Git/bin/bash.exe"


def shell_function(platform, name):
    source = (REPO / f"deploy/{platform}/deploy.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.MULTILINE | re.DOTALL)
    assert match, f"Missing deployment function: {platform}/{name}"
    return match.group()


def run_shell(script, env=None):
    return subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("failure", [False, True])
def test_docker_publication_uses_sql_entrypoint_and_stops_on_failure(failure):
    result = run_shell(shell_function("docker", "publish_shared_workbench") + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES="nexent-config nexent-runtime"
docker_compose_command=container_command
ROOT_ENV_FILE="/deployment with spaces/.env"
COMPOSE_DIR="/deployment with spaces/compose"
COMPOSE_FILE_SUFFIX=".yml"
container_command() { printf '<%s>\n' "$@"; return ''' + str(17 if failure else 0) + r'''; }
publish_shared_workbench
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    assert "<run>\n<--rm>\n<--no-deps>\n<--workdir>\n</opt/backend>" in result.stdout
    assert "<--entrypoint>\n</opt/nexent/scripts/start-backend.sh>\n<nexent-config>" in result.stdout
    assert "</deployment with spaces/.env>" in result.stdout
    assert "system_initialize && python -m management.services.agent.system_release" in result.stdout


@pytest.mark.parametrize("services", ["nexent-web", "nexent-runtime nexent-mcp", ""])
def test_docker_non_config_selection_does_not_publish(services):
    result = run_shell(shell_function("docker", "publish_shared_workbench") + f'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES="{services}"
docker_compose_command=container_command
container_command() {{ echo UNEXPECTED; return 9; }}
publish_shared_workbench
''')
    assert result.returncode == 0, result.stderr
    assert "UNEXPECTED" not in result.stdout


@pytest.mark.parametrize("failure", [False, True])
def test_docker_core_start_waits_for_publication(failure):
    result = run_shell(shell_function("docker", "deploy_core_services") + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES="nexent-config nexent-runtime"
docker_compose_command=container_command
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
prepare_core_service_deployment() { return 0; }
stop_old_business_services() { return 0; }
publish_shared_workbench() { echo PUBLISH; return ''' + str(1 if failure else 0) + r'''; }
container_command() { echo START_CORE; }
deploy_core_services
''')
    assert result.returncode == (1 if failure else 0), result.stderr
    assert "PUBLISH" in result.stdout
    if failure:
        assert "START_CORE" not in result.stdout
    else:
        assert result.stdout.index("PUBLISH") < result.stdout.index("START_CORE")


@pytest.mark.parametrize("pod,lookup_status,exec_status", [
    ("config-new", 0, 0), ("config-new", 0, 19), ("", 0, 0), ("", 1, 0),
])
def test_k8s_publication_uses_ready_config_environment(pod, lookup_status, exec_status):
    result = run_shell(shell_function("k8s", "publish_shared_workbench") + f'''
NAMESPACE="test-namespace"
find_ready_config_pod() {{ printf '%s' '{pod}'; return {lookup_status}; }}
kubectl() {{ printf '<%s>\\n' "$@"; return {exec_status}; }}
publish_shared_workbench
''')
    assert result.returncode == (1 if not pod or lookup_status or exec_status else 0), result.stderr
    if not pod or lookup_status:
        assert "<exec>" not in result.stdout
    else:
        assert "<exec>\n<-n>\n<test-namespace>\n<config-new>\n<-c>\n<nexent-config>" in result.stdout
        assert "cd /opt/backend && python -m management.services.agent.system_initialize" in result.stdout
        assert "system_initialize && python -m management.services.agent.system_release" in result.stdout


def test_k8s_application_hook_runs_after_skills_and_before_success():
    source = (REPO / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")
    application = source[source.index("    # Step 8:"):source.index("    # Step 9:")]
    assert "if ! deploy_application_release;" in application
    flow = shell_function("k8s", "deploy_application_release")
    stages = ["validate_application_release", "stop_old_business_workloads", "helm_upgrade_application_release true",
              "run_system_agent_bootstrap", "helm_upgrade_application_release false", "wait_for_nexent_ready"]
    assert [flow.index(stage) for stage in stages] == sorted(flow.index(stage) for stage in stages)
    bootstrap = shell_function("k8s", "run_system_agent_bootstrap")
    assert bootstrap.index("sync_official_skills_to_workspace") < bootstrap.index("nexent-bootstrap-start")
    assert 'deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"' in flow


@pytest.mark.parametrize("platform", ["docker", "k8s"])
@pytest.mark.parametrize("initialize_fails", [False, True])
def test_release_command_only_runs_after_successful_initialization(platform, initialize_fails):
    result = run_shell(shell_function(platform, "publish_shared_workbench") + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES=nexent-config
docker_compose_command=execute_hook
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
NAMESPACE=test-namespace
find_ready_config_pod() { echo config-new; }
execute_hook() {
    local command="${!#}"
    (
        cd() { return 0; }
        python() {
            echo "PYTHON $*"
            if [[ "$*" == *system_initialize ]]; then
                return ''' + str(21 if initialize_fails else 0) + r'''
            fi
            return 0
        }
        eval "$command"
    )
}
kubectl() { execute_hook "$@"; }
publish_shared_workbench
''')
    assert result.returncode == (1 if initialize_fails else 0), result.stderr
    assert "PYTHON -m management.services.agent.system_initialize" in result.stdout
    release = "PYTHON -m management.services.agent.system_release"
    if initialize_fails:
        assert release not in result.stdout
    else:
        assert result.stdout.index("system_initialize") < result.stdout.index(release)


@pytest.mark.skipif(os.name != "nt", reason="Native MSYS argument conversion requires Windows Git Bash")
@pytest.mark.parametrize("compose_suffix", ["", " compose"])
@pytest.mark.parametrize("existing_exclusion", ["", "/existing/"])
@pytest.mark.parametrize("hook", ["publish_shared_workbench", "prepare_core_service_deployment"])
def test_git_bash_preserves_container_paths_and_converts_host_paths(tmp_path, compose_suffix, existing_exclusion, hook):
    env = os.environ.copy()
    env.pop("MSYS_NO_PATHCONV", None)
    env["MSYS2_ARG_CONV_EXCL"] = existing_exclusion
    env["NATIVE_PROBE"] = sys.executable
    env["HOST_DIRECTORY"] = str(tmp_path / "deployment with spaces")
    result = run_shell(shell_function("docker", hook) + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES=nexent-config
NEXENT_IMAGE=backend:test
docker() { return 0; }
ROOT_ENV_FILE="$(cygpath -u "$HOST_DIRECTORY")/.env"
COMPOSE_DIR="$(cygpath -u "$HOST_DIRECTORY")/compose"
COMPOSE_FILE_SUFFIX=.yml
container_command() {
    printf 'DURING_EXCLUDE=%s\n' "$MSYS2_ARG_CONV_EXCL"
    "$NATIVE_PROBE" -c 'import json, sys; print(json.dumps({"args": sys.argv[1:]}))' "$@"
}
docker_compose_command="container_command''' + compose_suffix + r'''"
''' + hook + r''' nexent-config
printf 'AFTER_EXCLUDE=%s\n' "$MSYS2_ARG_CONV_EXCL"
''', env=env)
    assert result.returncode == 0, result.stderr
    received = next(item for line in result.stdout.splitlines() if line.startswith("{")
                    and "--workdir" in (item := json.loads(line))["args"])
    args = received["args"]
    assert args[args.index("--workdir") + 1] == "/opt/backend"
    expected_entrypoint = "/opt/nexent/scripts/start-backend.sh" if hook == "publish_shared_workbench" else "sh"
    assert args[args.index("--entrypoint") + 1] == expected_entrypoint
    assert Path(args[args.index("--env-file") + 1]) == Path(env["HOST_DIRECTORY"]) / ".env"
    assert Path(args[args.index("-f") + 1]) == Path(env["HOST_DIRECTORY"]) / "compose/docker-compose.yml"
    expected_exclusion = (existing_exclusion + ";" if existing_exclusion else "") + "/opt/"
    assert f"DURING_EXCLUDE={expected_exclusion}\n" in result.stdout
    assert f"AFTER_EXCLUDE={existing_exclusion}\n" in result.stdout


@pytest.mark.parametrize("failed_stage", ["", "prepare", "stop", "publish"])
def test_docker_upgrade_stops_old_writers_before_migrating(failed_stage):
    result = run_shell(shell_function("docker", "deploy_core_services") + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES="nexent-config nexent-runtime"
docker_compose_command=container_command
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
failed_stage="''' + failed_stage + r'''"
prepare_core_service_deployment() { echo EVENT:PREPARE; [ "$failed_stage" != prepare ]; }
stop_old_business_services() { echo "EVENT:STOP:$*"; [ "$failed_stage" != stop ]; }
publish_shared_workbench() { echo EVENT:PUBLISH; [ "$failed_stage" != publish ]; }
container_command() { echo EVENT:START; }
deploy_core_services
''')
    events = [line for line in result.stdout.splitlines() if line.startswith("EVENT:")]
    expected = ["EVENT:PREPARE", "EVENT:STOP:", "EVENT:PUBLISH", "EVENT:START"]
    if failed_stage:
        expected = expected[:{"prepare": 1, "stop": 2, "publish": 3}[failed_stage]]
    assert events == expected
    assert result.returncode == (1 if failed_stage else 0), result.stderr


@pytest.mark.parametrize("failure", ["", "query", "stop"])
@pytest.mark.parametrize("fresh", [False, True])
def test_stop_targets_only_existing_project_business_containers(failure, fresh):
    result = run_shell(shell_function("docker", "stop_old_business_services") + r'''
failure="''' + failure + r'''"
fresh="''' + str(fresh).lower() + r'''"
docker() {
  if [ "$1" = ps ]; then
    printf 'QUERY:%s\n' "$*" >&2
    [ "$failure" != query ] || return 12
    [ "$fresh" != true ] || return 0
    case "${!#}" in
      *service=nexent-config) printf 'config-a\nconfig-b\n' ;;
      *service=nexent-runtime) printf 'runtime-a\n' ;;
    esac
  elif [ "$1" = stop ]; then
    printf 'STOP:%s\n' "$*"
    [ "$failure" != stop ] || return 13
  else
    echo UNEXPECTED_COMMAND >&2
    return 14
  fi
}
stop_old_business_services
''')
    failed = failure == "query" or (failure == "stop" and not fresh)
    assert result.returncode == (1 if failed else 0), result.stderr
    queries = [line for line in result.stderr.splitlines() if line.startswith("QUERY:")]
    assert queries
    assert all("label=com.docker.compose.project=nexent" in line for line in queries)
    if failure != "query":
        services = [line.split("service=")[-1] for line in queries]
        assert services == ["nexent-config", "nexent-runtime", "nexent-mcp", "nexent-northbound", "nexent-web", "nexent-data-process"]
    if fresh or failure == "query":
        assert "STOP:" not in result.stdout
    else:
        assert "STOP:stop --time 60 config-a config-b runtime-a" in result.stdout
    assert "UNEXPECTED_COMMAND" not in result.stderr


@pytest.mark.parametrize("failed_stage", ["", "config", "pull", "modules", "local_missing"])
def test_preflight_prepares_images_and_checks_modules_without_migrating(failed_stage):
    result = run_shell(shell_function("docker", "prepare_core_service_deployment") + r'''
docker_compose_command=container_command
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
NEXENT_IMAGE=backend:test
NEXENT_WEB_IMAGE=web:test
failed_stage="''' + failed_stage + r'''"
DEPLOYMENT_IMAGE_SOURCE=general
[ "$failed_stage" != local_missing ] || DEPLOYMENT_IMAGE_SOURCE=local-latest
container_command() {
  printf 'COMPOSE:%s\n' "$*"
  if [[ "$*" == *'config --quiet' ]]; then
    [ "$failed_stage" != config ]
  else
    [ "$failed_stage" != modules ]
  fi
}
docker() {
  if [ "$1 $2" = 'image inspect' ]; then
    [ "$failed_stage" != pull ] && [ "$failed_stage" != local_missing ]
  elif [ "$1" = pull ]; then
    echo "PULL:$2"
    return 15
  else
    echo UNEXPECTED_COMMAND
    return 16
  fi
}
prepare_core_service_deployment nexent-config nexent-runtime nexent-web
''')
    assert result.returncode == (1 if failed_stage else 0), result.stderr
    assert "config --quiet" in result.stdout
    if failed_stage not in ("config", "pull", "local_missing"):
        assert "--entrypoint sh nexent-config -c test -r management/services/agent/system_initialize.py" in result.stdout
        assert "system_release.py" in result.stdout
    else:
        assert "--entrypoint" not in result.stdout
    assert "start-backend.sh" not in result.stdout
    if failed_stage == "pull":
        assert "PULL:backend:test" in result.stdout
    else:
        assert "PULL:" not in result.stdout


def test_missing_release_image_is_pulled_before_preflight():
    result = run_shell(shell_function("docker", "prepare_core_service_deployment") + r'''
docker_compose_command=container_command
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
NEXENT_IMAGE=backend:test
docker() {
  if [ "$1" = image ]; then return 1; fi
  printf 'PULL:%s\n' "$2"
}
container_command() { printf 'COMPOSE:%s\n' "$*"; }
prepare_core_service_deployment nexent-config nexent-runtime
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("PULL:backend:test") == 1
    assert result.stdout.index("PULL:") < result.stdout.index("run --rm")


def test_web_only_deployment_stops_only_selected_service_without_migration():
    result = run_shell(shell_function("docker", "deploy_core_services") + r'''
DEPLOYMENT_SELECTED_DOCKER_SERVICES=nexent-web
docker_compose_command=container_command
ROOT_ENV_FILE=/deployment/.env
COMPOSE_DIR=/deployment/compose
COMPOSE_FILE_SUFFIX=.yml
prepare_core_service_deployment() { echo PREPARE; }
stop_old_business_services() { echo "STOP:$*"; }
publish_shared_workbench() { case " $DEPLOYMENT_SELECTED_DOCKER_SERVICES " in *" nexent-config "*) echo MIGRATE ;; esac; }
container_command() { echo START; }
deploy_core_services
''')
    assert result.returncode == 0, result.stderr
    assert "STOP:nexent-web" in result.stdout
    assert "MIGRATE" not in result.stdout
    assert result.stdout.index("STOP:") < result.stdout.index("START")
