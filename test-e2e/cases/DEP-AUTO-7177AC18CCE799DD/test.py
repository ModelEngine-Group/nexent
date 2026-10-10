from __future__ import annotations

import subprocess
import tempfile

import pytest

from d5.assets import bash_path, require_command
from shared.config import repo_root

CASE_ID = "DEP-AUTO-7177AC18CCE799DD"

_BASH = r'''
set -euo pipefail
COMMON="$1"
DOCKER_DEPLOY="$2"
TMP="$3"

DEPLOYMENT_LANG=en
DEPLOYMENT_LANGUAGE=en
export DEPLOYMENT_LANG DEPLOYMENT_LANGUAGE

# shellcheck source=/dev/null
source "$COMMON"

DEPLOYMENT_ROOT_ENV="$TMP/root.env"
: > "$DEPLOYMENT_ROOT_ENV"
export DEPLOYMENT_ROOT_ENV

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [ "$expected" != "$actual" ]; then
    echo "FAIL: $message" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "FAIL: $message" >&2
    echo "  missing: $needle" >&2
    echo "  in: $haystack" >&2
    exit 1
  fi
}

APP_VERSION="latest"
deployment_prepare_config --app-version latest
assert_eq "lightweight" "$DEPLOYMENT_SANDBOX_MODE" "sandbox mode should default to lightweight"

deployment_prepare_config --sandbox-mode disabled --app-version latest
assert_eq "disabled" "$DEPLOYMENT_SANDBOX_MODE" "--sandbox-mode disabled should be parsed"
deployment_prepare_config --sandbox-mode lightweight --app-version latest
assert_eq "lightweight" "$DEPLOYMENT_SANDBOX_MODE" "--sandbox-mode lightweight should be parsed"
deployment_prepare_config --sandbox-mode full --app-version latest
assert_eq "full" "$DEPLOYMENT_SANDBOX_MODE" "--sandbox-mode full should be parsed"

if deployment_prepare_config --sandbox-mode unsupported --app-version latest 2>"$TMP/invalid-sandbox-mode.log"; then
  echo "FAIL: unsupported sandbox mode should fail validation" >&2
  exit 1
fi
assert_contains "$(cat "$TMP/invalid-sandbox-mode.log")" "Unsupported sandbox mode: unsupported" "invalid sandbox mode should name the rejected value"

unset NEXENT_SANDBOX_IMAGE NEXENT_SANDBOX_DEFAULT_LEVEL
deployment_prepare_config --components infrastructure,application --image-source general --sandbox-mode full --app-version v2.2.0
deployment_apply_image_source
assert_eq "docker" "$NEXENT_SANDBOX_DEFAULT_LEVEL" "full sandbox mode should enable Docker isolation"
assert_eq "nexent/nexent-sandbox-full:v2.2.0" "$NEXENT_SANDBOX_IMAGE" "full sandbox mode should select the full image"

unset NEXENT_SANDBOX_IMAGE NEXENT_SANDBOX_DEFAULT_LEVEL
deployment_prepare_config --components infrastructure,application --image-source general --sandbox-mode lightweight --app-version v2.2.0
deployment_apply_image_source
assert_eq "docker" "$NEXENT_SANDBOX_DEFAULT_LEVEL" "lightweight sandbox mode should enable Docker isolation"
assert_eq "nexent/nexent-sandbox:v2.2.0" "$NEXENT_SANDBOX_IMAGE" "lightweight sandbox mode should keep the lightweight image"

unset NEXENT_SANDBOX_IMAGE NEXENT_SANDBOX_DEFAULT_LEVEL
deployment_prepare_config --components infrastructure,application --image-source general --sandbox-mode disabled --app-version v2.2.0
deployment_apply_image_source
assert_eq "local" "$NEXENT_SANDBOX_DEFAULT_LEVEL" "disabled sandbox mode should use local execution"
assert_eq "nexent/nexent-sandbox:v2.2.0" "$NEXENT_SANDBOX_IMAGE" "disabled sandbox mode should keep the lightweight image"

LOCAL_CFG="$TMP/local-config.yaml"
deployment_prepare_config --sandbox-mode full --app-version latest
deployment_persist_local_config "$LOCAL_CFG"
assert_contains "$(cat "$LOCAL_CFG")" 'sandboxMode: "full"' "persisted local config should write sandboxMode"

HELM_VALUES="$TMP/helm-values.yaml"
deployment_render_helm_values "$HELM_VALUES"
assert_contains "$(cat "$HELM_VALUES")" 'sandboxMode: "full"' "helm values should render sandboxMode"

deployment_prepare_config --local-config "$LOCAL_CFG" --defaults --app-version latest
assert_eq "full" "$DEPLOYMENT_SANDBOX_MODE" "reloading persisted local config should restore sandbox mode"

DOCKER_CONTENT="$(cat "$DOCKER_DEPLOY")"
assert_contains "$DOCKER_CONTENT" 'if [ "$DEPLOYMENT_SANDBOX_MODE" = "disabled" ]' "disabled sandbox mode should skip image pulling"
assert_contains "$DOCKER_CONTENT" 'docker rm -f "$container_name"' "stale fixed sandbox container should be removed"
assert_contains "$DOCKER_CONTENT" 'current_image" = "$NEXENT_SANDBOX_IMAGE"' "matching fixed sandbox container should be retained"
assert_contains "$DOCKER_CONTENT" 'update_env_var "NEXENT_SANDBOX_DEFAULT_LEVEL"' "execution level should be persisted to env"

echo "SAND_BOX_CONTRACT_OK"
'''


@pytest.mark.stage("D5")
@pytest.mark.case_id(CASE_ID)
@pytest.mark.special_id(CASE_ID)
def test_dep_auto_7177ac18cce799dd():
    repo = repo_root()
    common = repo / "deploy" / "common" / "common.sh"
    docker_deploy = repo / "deploy" / "docker" / "deploy.sh"
    assert common.is_file(), "missing deploy script: " + str(common)
    assert docker_deploy.is_file(), "missing deploy script: " + str(docker_deploy)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [require_command("bash"), "-c", _BASH, "nexent-sandbox-test",
             bash_path(common), bash_path(docker_deploy), bash_path(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    assert proc.returncode == 0, (
        "deployment sandbox-mode contract failed (rc="
        + str(proc.returncode)
        + ") stdout=["
        + proc.stdout
        + "] stderr=["
        + proc.stderr
        + "]"
    )
