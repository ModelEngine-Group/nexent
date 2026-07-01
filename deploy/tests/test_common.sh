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

assert_not_eq() {
  local first="$1"
  local second="$2"
  local message="$3"
  if [ "$first" = "$second" ]; then
    echo "FAIL: $message"
    echo "  both: $first"
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

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "FAIL: $message"
    echo "  unexpected: $needle"
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
deployment_prepare_config --app-version latest
assert_eq "infrastructure,application,data-process,supabase" "$DEPLOYMENT_COMPONENTS" "default components should include data-process and supabase"
assert_contains "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" "nexent-data-process" "default docker services should include data-process"
assert_contains "$DEPLOYMENT_SELECTED_HELM_CHARTS" "nexent-supabase-db" "default helm charts should include supabase db"
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
assert_contains "$DEPLOYMENT_DOCKER_PORTS" "5013" "production should expose northbound"

deployment_apply_image_source
PRODUCTION_HELM_VALUES="$TMP_DIR/production-generated-values.yaml"
deployment_render_helm_values "$PRODUCTION_HELM_VALUES"
PRODUCTION_HELM_CONTENT="$(cat "$PRODUCTION_HELM_VALUES")"
assert_contains "$PRODUCTION_HELM_CONTENT" $'services:\n    northbound:\n      type: "NodePort"\n      nodePort: 30013' "production k8s should expose northbound as NodePort"
assert_contains "$PRODUCTION_HELM_CONTENT" $'services:\n    web:\n      type: "NodePort"\n      nodePort: 30000' "production k8s should expose web as NodePort"

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

FAKE_DOCKER_DIR="$TMP_DIR/fake-docker"
FAKE_DOCKER_LOG="$TMP_DIR/fake-docker.log"
mkdir -p "$FAKE_DOCKER_DIR"
cat > "$FAKE_DOCKER_DIR/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

if [ "${1:-}" = "image" ] && [ "${2:-}" = "inspect" ]; then
  shift 2
  image=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --format)
        shift 2
        ;;
      *)
        image="$1"
        shift
        ;;
    esac
  done
  [ "$image" = "missing/nexent:latest" ] && exit 1
  printf '%s\n' "${FAKE_DOCKER_IMAGE_ID:-sha256:fake-image-id}"
  exit 0
fi

echo "unexpected docker command: $*" >&2
exit 2
SH
chmod +x "$FAKE_DOCKER_DIR/docker"

(
  PATH="$FAKE_DOCKER_DIR:$PATH"
  export PATH FAKE_DOCKER_LOG
  FAKE_DOCKER_IMAGE_ID="sha256:first-local-image"
  export FAKE_DOCKER_IMAGE_ID

  first_image_checksum="$(deployment_image_rollout_checksum "nexent/nexent:latest")"
  first_rollout_checksums="$(
    NEXENT_IMAGE="nexent/nexent:latest" \
    NEXENT_WEB_IMAGE="nexent/nexent-web:latest" \
    NEXENT_DATA_PROCESS_IMAGE="nexent/nexent-data-process:latest" \
    OPENSSH_SERVER_IMAGE="nexent/nexent-ubuntu-terminal:latest" \
      deployment_render_image_rollout_checksums
  )"

  FAKE_DOCKER_IMAGE_ID="sha256:second-local-image"
  export FAKE_DOCKER_IMAGE_ID
  second_image_checksum="$(deployment_image_rollout_checksum "nexent/nexent:latest")"
  second_rollout_checksums="$(
    NEXENT_IMAGE="nexent/nexent:latest" \
    NEXENT_WEB_IMAGE="nexent/nexent-web:latest" \
    NEXENT_DATA_PROCESS_IMAGE="nexent/nexent-data-process:latest" \
    OPENSSH_SERVER_IMAGE="nexent/nexent-ubuntu-terminal:latest" \
      deployment_render_image_rollout_checksums
  )"

  assert_not_eq "$first_image_checksum" "$second_image_checksum" "local image ID changes should change image rollout checksum"
  assert_not_eq "$first_rollout_checksums" "$second_rollout_checksums" "rendered image rollout checksums should change when local image IDs change"
  assert_contains "$first_rollout_checksums" "backendImage:" "image rollout checksums should include backend image"
  assert_contains "$first_rollout_checksums" "webImage:" "image rollout checksums should include web image"
  assert_contains "$first_rollout_checksums" "dataProcessImage:" "image rollout checksums should include data-process image"
  assert_contains "$first_rollout_checksums" "sshImage:" "image rollout checksums should include ssh image"

  missing_checksum_a="$(deployment_image_rollout_checksum "missing/nexent:latest" 2>/dev/null)"
  FAKE_DOCKER_IMAGE_ID="sha256:third-local-image"
  export FAKE_DOCKER_IMAGE_ID
  missing_checksum_b="$(deployment_image_rollout_checksum "missing/nexent:latest" 2>/dev/null)"
  assert_eq "$missing_checksum_a" "$missing_checksum_b" "missing local image should use stable image reference fallback"
)

assert_contains "$(cat "$FAKE_DOCKER_LOG")" "image inspect --format {{.Id}} nexent/nexent:latest" "image fingerprint should inspect local Docker image"
if grep -Eq '(^| )(pull|manifest|buildx|imagetools)( |$)' "$FAKE_DOCKER_LOG"; then
  echo "FAIL: image fingerprint should not use remote Docker commands"
  cat "$FAKE_DOCKER_LOG"
  exit 1
fi

K8S_CHART_DIR="$SCRIPT_DIR/../k8s/helm/nexent"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-config/templates/deployment.yaml")" "checksum/nexent-backend-image" "config deployment should include backend image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-config/templates/deployment.yaml")" "checksum/nexent-env" "config deployment should include env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-config/templates/deployment.yaml")" "checksum/nexent-backend:" "config deployment should not keep removed backend rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-runtime/templates/deployment.yaml")" "checksum/nexent-backend-image" "runtime deployment should include backend image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-runtime/templates/deployment.yaml")" "checksum/nexent-env" "runtime deployment should include env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-runtime/templates/deployment.yaml")" "checksum/nexent-backend:" "runtime deployment should not keep removed backend rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-mcp/templates/deployment.yaml")" "checksum/nexent-backend-image" "mcp deployment should include backend image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-mcp/templates/deployment.yaml")" "checksum/nexent-env" "mcp deployment should include env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-mcp/templates/deployment.yaml")" "checksum/nexent-backend:" "mcp deployment should not keep removed backend rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-northbound/templates/deployment.yaml")" "checksum/nexent-backend-image" "northbound deployment should include backend image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-northbound/templates/deployment.yaml")" "checksum/nexent-env" "northbound deployment should include env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-northbound/templates/deployment.yaml")" "checksum/nexent-backend:" "northbound deployment should not keep removed backend rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-web/templates/deployment.yaml")" "checksum/nexent-web-image" "web deployment should include web image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-web/templates/deployment.yaml")" "checksum/nexent-env" "web deployment should include env rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-data-process/templates/deployment.yaml")" "checksum/nexent-data-process-image" "data-process deployment should include data-process image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-data-process/templates/deployment.yaml")" "checksum/nexent-env" "data-process deployment should include env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-data-process/templates/deployment.yaml")" "checksum/nexent-backend:" "data-process deployment should not keep removed backend rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-openssh/templates/deployment.yaml")" "checksum/nexent-ssh-image" "openssh deployment should include ssh image rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-openssh/templates/deployment.yaml")" "checksum/nexent-env" "openssh deployment should include env rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-minio/templates/deployment.yaml")" "checksum/nexent-env" "minio deployment should include env rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-auth/templates/deployment.yaml")" "checksum/nexent-supabase-secret" "supabase auth deployment should include supabase secret rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-auth/templates/deployment.yaml")" "checksum/nexent-env" "supabase auth deployment should not use full env rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-db/templates/deployment.yaml")" "checksum/nexent-supabase-secret" "supabase db deployment should include supabase secret rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-db/templates/deployment.yaml")" "checksum/nexent-sql" "supabase db deployment should keep SQL rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-db/templates/deployment.yaml")" "checksum/nexent-env" "supabase db deployment should not use full env rollout annotation"
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-kong/templates/deployment.yaml")" "checksum/nexent-supabase-secret" "supabase kong deployment should include supabase secret rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-kong/templates/deployment.yaml")" "checksum/nexent-env" "supabase kong deployment should not use full env rollout annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-web/templates/deployment.yaml")" "checksum/nexent-web:" "web deployment should not keep component-named env checksum annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-openssh/templates/deployment.yaml")" "checksum/nexent-ssh:" "openssh deployment should not keep component-named env checksum annotation"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-minio/templates/deployment.yaml")" "checksum/nexent-minio" "minio deployment should not keep component-named env checksum annotation"

ENV_CHECKSUM_A="$TMP_DIR/env-checksum-a.env"
cat > "$ENV_CHECKSUM_A" <<'ENV'
# ignored comment

BETA=two
ALPHA=one
export GAMMA="three"
not an assignment
ENV
DEPLOYMENT_ROOT_ENV="$ENV_CHECKSUM_A"
ENV_CHECKSUM_PAYLOAD_A="$(deployment_env_values_payload)"
ENV_CHECKSUM_A_VALUE="$(deployment_env_values_checksum)"
assert_eq $'ALPHA=one\nBETA=two\nGAMMA="three"' "$ENV_CHECKSUM_PAYLOAD_A" "env checksum payload should normalize valid assignments by key"

ENV_CHECKSUM_B="$TMP_DIR/env-checksum-b.env"
cat > "$ENV_CHECKSUM_B" <<'ENV'

export GAMMA="three"
# another ignored comment
ALPHA=one
BETA=two
ENV
DEPLOYMENT_ROOT_ENV="$ENV_CHECKSUM_B"
ENV_CHECKSUM_B_VALUE="$(deployment_env_values_checksum)"
assert_eq "$ENV_CHECKSUM_A_VALUE" "$ENV_CHECKSUM_B_VALUE" "env checksum should ignore comments, blank lines, and assignment order"

ENV_CHECKSUM_C="$TMP_DIR/env-checksum-c.env"
cat > "$ENV_CHECKSUM_C" <<'ENV'
ALPHA=one
BETA=changed
GAMMA="three"
ENV
DEPLOYMENT_ROOT_ENV="$ENV_CHECKSUM_C"
ENV_CHECKSUM_C_VALUE="$(deployment_env_values_checksum)"
assert_not_eq "$ENV_CHECKSUM_A_VALUE" "$ENV_CHECKSUM_C_VALUE" "env checksum should change when any valid env value changes"

DEPLOYMENT_ROOT_ENV="$TMP_DIR/missing-env-file.env"
MISSING_ENV_CHECKSUM_A="$(deployment_env_values_checksum 2>/dev/null)"
MISSING_ENV_CHECKSUM_B="$(deployment_env_values_checksum 2>/dev/null)"
assert_eq "$MISSING_ENV_CHECKSUM_A" "$MISSING_ENV_CHECKSUM_B" "missing env file should use a stable empty checksum fallback"

K8S_DEPLOY_CHECKSUM_BLOCK="$(awk '/render_runtime_secret_values\(\) {/,/deployment_render_image_rollout_checksums/' "$SCRIPT_DIR/../k8s/deploy.sh")"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'env_checksum="$(deployment_env_values_checksum)"' "k8s deploy should compute rollout checksum from full .env"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "printf '    env: %s\\n'" "k8s deploy should render the full .env checksum under the env name"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "supabase_secret_checksum" "k8s deploy should compute a dedicated Supabase secret rollout checksum"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "printf '    supabaseSecret: %s\\n'" "k8s deploy should render the Supabase secret checksum"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'JWT_SECRET:-' "supabase secret checksum should include JWT secret"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'SECRET_KEY_BASE:-' "supabase secret checksum should include secret key base"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'VAULT_ENC_KEY:-' "supabase secret checksum should include vault encryption key"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'SUPABASE_ANON_KEY:-' "supabase secret checksum should include anon key"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'SUPABASE_SERVICE_ROLE_KEY:-' "supabase secret checksum should include service role key"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'supabase_postgres_password' "supabase secret checksum should include Supabase postgres password"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'gotrue_db_url' "supabase secret checksum should include gotrue DB URL"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "printf '    backend:" "k8s deploy should not render the removed backend rollout checksum"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "backend_checksum" "k8s deploy should not compute the removed backend rollout checksum"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'ELASTICSEARCH_API_KEY' "k8s deploy should not enumerate backend env variables in rollout checksum"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'DASHBOARD_USERNAME' "supabase secret checksum should not include direct Supabase env values"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'SITE_URL' "supabase secret checksum should not include direct Supabase env values"
assert_not_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "printf '    web:" "k8s deploy should not render component-named env checksum keys"

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
assert_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "ENABLE_TELEMETRY=" "docker generated env should contain monitoring enablement"
assert_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "MONITORING_PROVIDER=" "docker generated env should contain monitoring provider"
assert_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "MONITORING_DASHBOARD_URL=" "docker generated env should contain monitoring dashboard URL"
if grep -Eq '^DEPLOYMENT_(SCHEMA_VERSION|COMPONENTS|PORT_POLICY|IMAGE_SOURCE|REGISTRY_PROFILE|APP_VERSION|MONITORING_PROVIDER|SELECTED_DOCKER_SERVICES|DOCKER_PORTS)=' "$DOCKER_ENV"; then
  echo "FAIL: docker generated env should not contain persisted deployment decisions"
  exit 1
fi

DOCKER_MONITORING_CONFIG_BLOCK="$(awk '/docker_monitoring_collector_config_file\(\)/,/^pull_mcp_image\(\)/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'update_env_var "OTEL_EXPORTER_OTLP_ENDPOINT" "$OTEL_EXPORTER_OTLP_ENDPOINT"' "docker deploy should persist backend OTLP endpoint for monitoring"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'export OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"' "docker deploy should point backend telemetry at Docker collector service"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'MONITORING_ENV_EXAMPLE' "docker deploy should use monitoring.env.example defaults"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'source "$MONITORING_ENV_FILE"' "docker deploy should source generated monitoring.env"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'update_monitoring_env_var "OTEL_COLLECTOR_CONFIG_FILE" "$collector_config_file"' "docker deploy should persist monitoring collector config in monitoring.env"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'otel-collector-phoenix-config.yml' "docker deploy should map phoenix to its collector config"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'otel-collector-langfuse-config.yml' "docker deploy should map langfuse to its collector config"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'otel-collector-langsmith-config.yml' "docker deploy should map langsmith to its collector config"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'otel-collector-grafana-config.yml' "docker deploy should map grafana to its collector config"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'otel-collector-zipkin-config.yml' "docker deploy should map zipkin to its collector config"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'LANGFUSE_OTLP_AUTH_HEADER="Basic $(' "docker deploy should derive Langfuse OTLP auth header"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'update_monitoring_env_var "LANGFUSE_OTLP_AUTH_HEADER" "$LANGFUSE_OTLP_AUTH_HEADER"' "docker deploy should persist Langfuse OTLP auth header in monitoring.env"

DOCKER_DEPLOY_MONITORING_BLOCK="$(awk '/deploy_monitoring\(\)/,/^configure_root_dir_from_env\(\)/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'LANGSMITH_API_KEY is required' "docker deploy should fail fast when LangSmith API key is missing"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'profile_args+=(--profile "$DEPLOYMENT_MONITORING_PROVIDER")' "docker deploy should keep provider-specific compose profiles"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" '--env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE"' "docker deploy should load generated monitoring.env for monitoring compose"

MONITORING_EXAMPLE_FILE="$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example"
MONITORING_COMPOSE_FILE="$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml"
MONITORING_COMPOSE_DEFAULTS="$TMP_DIR/docker-compose-monitoring-defaults.txt"
awk '
  {
    line = $0
    while (match(line, /\$\{[A-Za-z_][A-Za-z0-9_]*:-[^}]*\}/)) {
      expr = substr(line, RSTART + 2, RLENGTH - 3)
      key = expr
      sub(/:-.*/, "", key)
      value = expr
      sub(/^[^:]*:-/, "", value)
      print key "=" value
      line = substr(line, RSTART + RLENGTH)
    }
  }
' "$MONITORING_COMPOSE_FILE" | sort -u > "$MONITORING_COMPOSE_DEFAULTS"
while IFS='=' read -r key compose_default; do
  [ -n "$key" ] || continue
  case "$key" in
    OTEL_COLLECTOR_CONFIG_FILE)
      continue
      ;;
  esac
  if example_default="$(deployment_get_env_var_file "$MONITORING_EXAMPLE_FILE" "$key" 2>/dev/null)"; then
    assert_eq "$example_default" "$compose_default" "docker compose fallback for $key should match monitoring.env.example"
  fi
done < "$MONITORING_COMPOSE_DEFAULTS"

assert_contains "$(cat "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example")" "GRAFANA_ADMIN_PASSWORD=nexent@4321" "docker monitoring defaults should define Grafana admin password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-nexent@4321}' "docker compose Grafana password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "adminPassword: nexent@4321" "k8s monitoring Grafana password should match docker monitoring default"
assert_contains "$(cat "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example")" "LANGFUSE_POSTGRES_PASSWORD=nexent@4321" "docker monitoring defaults should define Langfuse postgres password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'LANGFUSE_POSTGRES_PASSWORD:-nexent@4321' "docker compose Langfuse postgres password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "password: nexent@4321" "k8s monitoring Langfuse postgres password should match docker monitoring default"
assert_contains "$(cat "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example")" "LANGFUSE_INIT_USER_PASSWORD=nexent@4321" "docker monitoring defaults should define Langfuse init user password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD:-nexent@4321}' "docker compose Langfuse init user password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "userPassword: nexent@4321" "k8s monitoring Langfuse init user password should match docker monitoring default"
assert_contains "$(cat "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example")" "LANGFUSE_CLICKHOUSE_CLUSTER_ENABLED=false" "docker monitoring defaults should include all compose Langfuse clickhouse settings"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'CLICKHOUSE_CLUSTER_ENABLED: ${LANGFUSE_CLICKHOUSE_CLUSTER_ENABLED:-false}' "docker compose Langfuse clickhouse cluster fallback should match monitoring.env.example"

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
mkdir -p "$ENV_TEST_ROOT/docker" "$ENV_TEST_ROOT/deploy/env"
printf 'FROM_ROOT_SHOULD_NOT_COPY=yes\n' > "$ENV_TEST_ROOT/.env"
printf 'FROM_ROOT_EXAMPLE_SHOULD_NOT_COPY=yes\n' > "$ENV_TEST_ROOT/.env.example"
printf 'FROM_DOCKER=yes\n' > "$ENV_TEST_ROOT/docker/.env"
printf 'FROM_EXAMPLE=yes\n' > "$ENV_TEST_ROOT/deploy/env/.env.example"
deployment_ensure_root_env "$ENV_TEST_ROOT" "$ENV_TEST_ROOT/docker"
assert_contains "$(cat "$ENV_TEST_ROOT/deploy/env/.env")" "FROM_DOCKER=yes" "deploy/env/.env should migrate from docker/.env first"
if grep -q "FROM_ROOT_SHOULD_NOT_COPY" "$ENV_TEST_ROOT/deploy/env/.env"; then
  echo "FAIL: deploy/env/.env should not migrate from root .env"
  exit 1
fi

DOCKER_EXAMPLE_ONLY_ROOT="$TMP_DIR/docker-example-only-root"
mkdir -p "$DOCKER_EXAMPLE_ONLY_ROOT/docker" "$DOCKER_EXAMPLE_ONLY_ROOT/deploy/env"
printf 'FROM_DOCKER_EXAMPLE_SHOULD_NOT_COPY=yes\n' > "$DOCKER_EXAMPLE_ONLY_ROOT/docker/.env.example"
if deployment_ensure_root_env "$DOCKER_EXAMPLE_ONLY_ROOT" "$DOCKER_EXAMPLE_ONLY_ROOT/docker" 2>/dev/null; then
  echo "FAIL: deploy/env/.env should not migrate from docker/.env.example"
  exit 1
fi
if [ -f "$DOCKER_EXAMPLE_ONLY_ROOT/deploy/env/.env" ]; then
  echo "FAIL: docker/.env.example should not create deploy/env/.env"
  exit 1
fi

printf 'ROOT_ONLY=yes\n' > "$ENV_TEST_ROOT/deploy/env/.env"
deployment_ensure_root_env "$ENV_TEST_ROOT" "$ENV_TEST_ROOT/docker"
assert_contains "$(cat "$ENV_TEST_ROOT/deploy/env/.env")" "ROOT_ONLY=yes" "existing deploy/env/.env should not be overwritten"

deployment_update_env_var_file "$ENV_TEST_ROOT/deploy/env/.env" "ROOT_ONLY" "updated"
assert_contains "$(cat "$ENV_TEST_ROOT/deploy/env/.env")" 'ROOT_ONLY="updated"' "env updater should update deploy env values"
assert_eq "true" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should mark changed writes"

ENV_CONTENT_BEFORE="$(cat "$ENV_TEST_ROOT/deploy/env/.env")"
deployment_update_env_var_file "$ENV_TEST_ROOT/deploy/env/.env" "ROOT_ONLY" "updated"
assert_eq "false" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should mark identical writes unchanged"
assert_eq "$ENV_CONTENT_BEFORE" "$(cat "$ENV_TEST_ROOT/deploy/env/.env")" "env updater should not rewrite identical quoted values"

printf 'UNQUOTED=value\nSINGLE_QUOTED='\''value2'\''\n' >> "$ENV_TEST_ROOT/deploy/env/.env"
assert_eq "value" "$(deployment_get_env_var_file "$ENV_TEST_ROOT/deploy/env/.env" "UNQUOTED")" "env getter should read unquoted values"
assert_eq "value2" "$(deployment_get_env_var_file "$ENV_TEST_ROOT/deploy/env/.env" "SINGLE_QUOTED")" "env getter should read single-quoted values"
deployment_update_env_var_file "$ENV_TEST_ROOT/deploy/env/.env" "UNQUOTED" "value"
assert_eq "false" "$DEPLOYMENT_LAST_ENV_WRITE_CHANGED" "env updater should normalize unquoted identical values"

GENERATE_ENV_TEST_ROOT="$TMP_DIR/generate-env-root"
mkdir -p "$GENERATE_ENV_TEST_ROOT/docker" "$GENERATE_ENV_TEST_ROOT/deploy/env"
printf 'FROM_GENERATE_ROOT_SHOULD_NOT_COPY=yes\n' > "$GENERATE_ENV_TEST_ROOT/.env"
printf 'FROM_GENERATE_ROOT_EXAMPLE_SHOULD_NOT_COPY=yes\n' > "$GENERATE_ENV_TEST_ROOT/.env.example"
printf 'FROM_GENERATE_DOCKER=yes\n' > "$GENERATE_ENV_TEST_ROOT/docker/.env"
printf 'FROM_GENERATE_EXAMPLE=yes\n' > "$GENERATE_ENV_TEST_ROOT/deploy/env/.env.example"
(
  NEXENT_GENERATE_ENV_SKIP_MAIN=true
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/../docker/generate_env.sh"
  ENV_FILE="$GENERATE_ENV_TEST_ROOT/deploy/env/.env"
  ENV_EXAMPLE="$GENERATE_ENV_TEST_ROOT/deploy/env/.env.example"
  DOCKER_ENV="$GENERATE_ENV_TEST_ROOT/docker/.env"
  prepare_env_file >/dev/null
)
assert_contains "$(cat "$GENERATE_ENV_TEST_ROOT/deploy/env/.env")" "FROM_GENERATE_DOCKER=yes" "generate_env should migrate docker/.env before deploy/env/.env.example"
if grep -q "FROM_GENERATE_ROOT_SHOULD_NOT_COPY" "$GENERATE_ENV_TEST_ROOT/deploy/env/.env"; then
  echo "FAIL: generate_env should not migrate from root .env"
  exit 1
fi

GENERATE_DOCKER_EXAMPLE_ONLY_ROOT="$TMP_DIR/generate-docker-example-only-root"
mkdir -p "$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/docker" "$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/deploy/env"
printf 'FROM_GENERATE_DOCKER_EXAMPLE_SHOULD_NOT_COPY=yes\n' > "$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/docker/.env.example"
if (
  NEXENT_GENERATE_ENV_SKIP_MAIN=true
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/../docker/generate_env.sh"
  ENV_FILE="$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/deploy/env/.env"
  ENV_EXAMPLE="$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/deploy/env/.env.example"
  DOCKER_ENV="$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/docker/.env"
  prepare_env_file >/dev/null 2>&1
); then
  echo "FAIL: generate_env should not migrate from docker/.env.example"
  exit 1
fi
if [ -f "$GENERATE_DOCKER_EXAMPLE_ONLY_ROOT/deploy/env/.env" ]; then
  echo "FAIL: generate_env should not create deploy/env/.env from docker/.env.example"
  exit 1
fi
echo "All deployment common tests passed."
