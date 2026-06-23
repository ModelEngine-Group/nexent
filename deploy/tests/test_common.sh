#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../common/common.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../common/version.sh"

TMP_DIR="${TMPDIR:-/tmp}/nexent-deployment-test-$$"
mkdir -p "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [ "$expected" != "$actual" ]; then
    echo "FAIL: $message"
    echo "  expected: $expected"
    echo "  actual:   $actual"
    exit 1
  fi
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "FAIL: $message"
    echo "  missing: $needle"
    echo "  in: $haystack"
    exit 1
  fi
}

assert_success() {
  local message="$1"
  shift
  if ! "$@"; then
    echo "FAIL: $message"
    exit 1
  fi
}

write_full_config() {
  local file="$1"
  {
    echo 'schemaVersion: "1"'
    echo 'appVersion: "latest"'
    echo 'components:'
    echo '  - infrastructure'
    echo '  - application'
    echo '  - data-process'
    echo '  - supabase'
    echo '  - terminal'
    echo 'portPolicy: "development"'
    echo 'imageSource: "local-latest"'
  } > "$file"
}

APP_VERSION="latest"
deployment_prepare_config --components infrastructure,application --port-policy production --image-source general --app-version latest
assert_eq "infrastructure,application" "$DEPLOYMENT_COMPONENTS" "components should come from CLI"
assert_eq "production" "$DEPLOYMENT_PORT_POLICY" "port policy should come from CLI"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "image source should come from CLI"
assert_contains "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" "nexent-web" "application services should include web"
if [[ "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" == *"nexent-data-process"* ]]; then
  echo "FAIL: application should not include data-process"
  exit 1
fi
assert_contains "$DEPLOYMENT_DOCKER_PORTS" "3000" "production should expose web"

deployment_prepare_config --components supabase --port-policy development --app-version latest
assert_eq "infrastructure,supabase" "$DEPLOYMENT_COMPONENTS" "only infrastructure should be required and added"
if [[ "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" == *"nexent-web"* ]]; then
  echo "FAIL: application should not be auto-added"
  exit 1
fi

deployment_prepare_config --components infrastructure,application --port-policy development --registry-profile mainland --app-version latest
assert_eq "mainland" "$DEPLOYMENT_IMAGE_SOURCE" "legacy registry profile should map to mainland image source"

if deployment_prepare_config --components infrastructure,application --port-policy development --image-source pinned --app-version latest 2>/dev/null; then
  echo "FAIL: pinned image source should be rejected"
  exit 1
fi

DEPLOYMENT_VERSION="full"
DEPLOYMENT_MODE="development"
IS_MAINLAND="Y"
deployment_prepare_config --app-version latest
assert_contains "$DEPLOYMENT_COMPONENTS" "supabase" "legacy full should include supabase"
assert_eq "mainland" "$DEPLOYMENT_REGISTRY_PROFILE" "legacy mainland flag should map registry profile"
assert_eq "mainland" "$DEPLOYMENT_IMAGE_SOURCE" "legacy mainland flag should map image source"
unset DEPLOYMENT_VERSION DEPLOYMENT_MODE IS_MAINLAND

FULL_CONFIG="$TMP_DIR/full.yaml"
write_full_config "$FULL_CONFIG"
deployment_prepare_config --config "$FULL_CONFIG"
deployment_apply_image_source
assert_eq "nexent/nexent:latest" "$NEXENT_IMAGE" "local-latest image should be applied"
assert_contains "$DEPLOYMENT_SELECTED_HELM_CHARTS" "nexent-data-process" "data-process chart should be selected"

DEPLOYMENT_VERSION="speed"
DEPLOYMENT_MODE="production"
IS_MAINLAND="Y"
deployment_prepare_config --local-config "$FULL_CONFIG" --use-local-config --app-version latest
assert_contains "$DEPLOYMENT_COMPONENTS" "data-process" "use local config should keep saved data-process when legacy env exists"
assert_contains "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" "nexent-data-process" "use local config should select data-process docker service"
assert_eq "development" "$DEPLOYMENT_PORT_POLICY" "use local config should keep saved port policy over legacy mode"
assert_eq "local-latest" "$DEPLOYMENT_IMAGE_SOURCE" "use local config should keep saved image source over legacy mainland flag"
unset DEPLOYMENT_VERSION DEPLOYMENT_MODE IS_MAINLAND

LOCAL_HELM_VALUES="$TMP_DIR/local-generated-values.yaml"
deployment_render_helm_values "$LOCAL_HELM_VALUES"
assert_contains "$(sed -n '1,90p' "$LOCAL_HELM_VALUES")" "repository: \"nexent/nexent\"" "local-latest should render mcp chart with backend image"
assert_contains "$(sed -n '1,90p' "$LOCAL_HELM_VALUES")" "pullPolicy: \"Never\"" "local-latest should render mcp chart with local pull policy"
assert_contains "$(sed -n '140,180p' "$LOCAL_HELM_VALUES")" "repository: \"nexent/nexent-mcp\"" "local-latest should keep common mcp docker image"

DEPLOYMENT_VERSION="speed"
deployment_prepare_config --local-config "$FULL_CONFIG" --reconfigure --image-source general --app-version latest
assert_eq "false" "$DEPLOYMENT_CONFIG_FILE_LOADED" "reconfigure should use local config as defaults without skipping configuration"
assert_contains "$DEPLOYMENT_COMPONENTS" "data-process" "reconfigure defaults should include saved components"
assert_eq "development" "$DEPLOYMENT_PORT_POLICY" "reconfigure defaults should include saved port policy"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "explicit image source should override reconfigure defaults"
unset DEPLOYMENT_VERSION

HELM_VALUES="$TMP_DIR/generated-values.yaml"
deployment_render_helm_values "$HELM_VALUES"
assert_contains "$(sed -n '1,220p' "$HELM_VALUES")" "data-process: true" "component table should include data-process"
assert_contains "$(sed -n '1,260p' "$HELM_VALUES")" "type: \"NodePort\"" "development policy should render NodePort values"
assert_contains "$(sed -n '1,260p' "$HELM_VALUES")" "enabled: true" "selected charts should be enabled"

DOCKER_ENV="$TMP_DIR/.env.generated"
deployment_render_docker_env "$DOCKER_ENV"
assert_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "NEXENT_IMAGE=" "docker generated env should contain image variables"
if grep -Eq '^DEPLOYMENT_(SCHEMA_VERSION|COMPONENTS|PORT_POLICY|IMAGE_SOURCE|REGISTRY_PROFILE|APP_VERSION|MONITORING_PROVIDER|SELECTED_DOCKER_SERVICES|DOCKER_PORTS)=' "$DOCKER_ENV"; then
  echo "FAIL: docker generated env should not contain persisted deployment decisions"
  exit 1
fi

LOCAL_CONFIG="$TMP_DIR/local-config.yaml"
deployment_persist_local_config "$LOCAL_CONFIG"
if grep -Eq 'PASSWORD|TOKEN|JWT|SECRET|KEY' "$LOCAL_CONFIG"; then
  echo "FAIL: persisted local config should not contain secret-looking fields"
  exit 1
fi
if grep -q 'registryProfile' "$LOCAL_CONFIG"; then
  echo "FAIL: persisted local config should not contain registryProfile"
  exit 1
fi

assert_success "b should be treated as TUI back key" deployment_tui_is_back_key "b"
assert_success "Backspace should be treated as TUI back key" deployment_tui_is_back_key $'\177'
if deployment_tui_is_back_key "q"; then
  echo "FAIL: q should remain the TUI quit key"
  exit 1
fi

deployment_tui_step_should_run() {
  case "$1" in
    0|1|2)
      return 0
      ;;
    3)
      return 1
      ;;
  esac
  return 1
}
assert_eq "1" "$(deployment_tui_next_step 0)" "TUI next step should advance to the next runnable step"
assert_eq "4" "$(deployment_tui_next_step 2)" "TUI next step should skip non-runnable monitoring provider"
assert_eq "2" "$(deployment_tui_previous_step 3)" "TUI previous step should skip non-runnable steps"

assert_eq "$(sed -n '1p' "$SCRIPT_DIR/../../VERSION")" "$(deployment_read_version "")" "deployment version should come from root VERSION"
assert_eq "v-test" "$(deployment_read_version "v-test")" "explicit deployment version should win"

assert_success "password validation should accept frontend-compatible passwords" deployment_validate_password "Nexent123"
if deployment_validate_password "nexent123"; then
  echo "FAIL: password without uppercase letters should be rejected"
  exit 1
fi
if deployment_validate_password "NEXENT123"; then
  echo "FAIL: password without lowercase letters should be rejected"
  exit 1
fi
if deployment_validate_password "NexentPwd"; then
  echo "FAIL: password without numbers should be rejected"
  exit 1
fi
if deployment_validate_password "Nex123"; then
  echo "FAIL: password shorter than 8 characters should be rejected"
  exit 1
fi

ENV_TEST_ROOT="$TMP_DIR/env-root"
mkdir -p "$ENV_TEST_ROOT/docker"
printf 'FROM_DOCKER=yes\n' > "$ENV_TEST_ROOT/docker/.env"
printf 'FROM_EXAMPLE=yes\n' > "$ENV_TEST_ROOT/.env.example"
deployment_ensure_root_env "$ENV_TEST_ROOT" "$ENV_TEST_ROOT/docker"
assert_contains "$(cat "$ENV_TEST_ROOT/.env")" "FROM_DOCKER=yes" "root .env should migrate from docker/.env first"

printf 'ROOT_ONLY=yes\n' > "$ENV_TEST_ROOT/.env"
deployment_ensure_root_env "$ENV_TEST_ROOT" "$ENV_TEST_ROOT/docker"
assert_contains "$(cat "$ENV_TEST_ROOT/.env")" "ROOT_ONLY=yes" "existing root .env should not be overwritten"

deployment_update_env_var_file "$ENV_TEST_ROOT/.env" "ROOT_ONLY" "updated"
assert_contains "$(cat "$ENV_TEST_ROOT/.env")" 'ROOT_ONLY="updated"' "env updater should update root env values"
assert_eq "true" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should mark changed writes"

ENV_CONTENT_BEFORE="$(cat "$ENV_TEST_ROOT/.env")"
deployment_update_env_var_file "$ENV_TEST_ROOT/.env" "ROOT_ONLY" "updated"
assert_eq "false" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should mark identical writes unchanged"
assert_eq "$ENV_CONTENT_BEFORE" "$(cat "$ENV_TEST_ROOT/.env")" "env updater should not rewrite identical quoted values"

printf 'UNQUOTED=value\nSINGLE_QUOTED='\''value2'\''\n' >> "$ENV_TEST_ROOT/.env"
assert_eq "value" "$(deployment_get_env_var_file "$ENV_TEST_ROOT/.env" "UNQUOTED")" "env getter should read unquoted values"
assert_eq "value2" "$(deployment_get_env_var_file "$ENV_TEST_ROOT/.env" "SINGLE_QUOTED")" "env getter should read single-quoted values"
deployment_update_env_var_file "$ENV_TEST_ROOT/.env" "UNQUOTED" "value"
assert_eq "false" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should normalize unquoted identical values"

echo "All deployment common tests passed."
