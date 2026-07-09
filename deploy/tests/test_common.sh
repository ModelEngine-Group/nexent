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
DEPLOYMENT_ROOT_ENV="$TMP_DIR/root.env"
: > "$DEPLOYMENT_ROOT_ENV"
export DEPLOYMENT_LANG=en

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

assert_eq "en" "$(DEPLOYMENT_LANG="" LC_ALL="" LC_MESSAGES="" LANGUAGE="" LANG="en_US.UTF-8" deployment_detect_language)" "English locale should select English"
assert_eq "zh" "$(DEPLOYMENT_LANG="" LC_ALL="" LC_MESSAGES="" LANGUAGE="" LANG="zh_CN.UTF-8" deployment_detect_language)" "Chinese LANG should select Chinese"
assert_eq "zh" "$(DEPLOYMENT_LANG="" LC_ALL="zh_CN.UTF-8" LC_MESSAGES="" LANGUAGE="" LANG="en_US.UTF-8" deployment_detect_language)" "LC_ALL should take priority over LANG"
assert_eq "en" "$(DEPLOYMENT_LANG="en" LC_ALL="" LC_MESSAGES="" LANGUAGE="" LANG="zh_CN.UTF-8" deployment_detect_language)" "DEPLOYMENT_LANG should force English"
assert_eq "zh" "$(DEPLOYMENT_LANG=zh bash -c 'source deploy/common/common.sh; printf "%s" "$DEPLOYMENT_LANGUAGE"')" "language initialization should cache Chinese"
assert_eq "en" "$(DEPLOYMENT_LANG=en LANG="zh_CN.UTF-8" bash -c 'source deploy/common/common.sh; printf "%s" "$DEPLOYMENT_LANGUAGE"')" "language initialization should cache forced English"
assert_eq "后端 API 服务" "$(DEPLOYMENT_LANGUAGE=zh deployment_i18n image_build.detail.main)" "image build TUI details should support Chinese"
assert_eq "backend API service" "$(DEPLOYMENT_LANGUAGE=en deployment_i18n image_build.detail.main)" "image build TUI details should preserve English"

ZH_DEPLOY_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../deploy.sh" --help)"
assert_contains "$ZH_DEPLOY_HELP" "用法：" "deploy wrapper help should follow Chinese locale"
assert_contains "$ZH_DEPLOY_HELP" "--defaults" "deploy wrapper help should document defaults mode"
EN_DEPLOY_HELP="$(DEPLOYMENT_LANG=en LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../deploy.sh" --help)"
assert_contains "$EN_DEPLOY_HELP" "Usage:" "DEPLOYMENT_LANG should force English deploy wrapper help"
assert_contains "$EN_DEPLOY_HELP" "--defaults" "English deploy wrapper help should document defaults mode"

ZH_ROOT_DEPLOY_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../../deploy.sh" --help)"
assert_contains "$ZH_ROOT_DEPLOY_HELP" "用法：" "root deploy help should follow Chinese locale"
assert_contains "$ZH_ROOT_DEPLOY_HELP" "此根入口只转发到目标专用部署脚本。" "root deploy help should describe forwarding in Chinese"
assert_contains "$ZH_ROOT_DEPLOY_HELP" "--defaults" "root deploy help should document defaults mode"

ZH_UNINSTALL_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../uninstall.sh" --help)"
assert_contains "$ZH_UNINSTALL_HELP" "用法：" "uninstall wrapper help should follow Chinese locale"

ZH_ROOT_UNINSTALL_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../../uninstall.sh" --help)"
assert_contains "$ZH_ROOT_UNINSTALL_HELP" "用法：" "root uninstall help should follow Chinese locale"
assert_contains "$ZH_ROOT_UNINSTALL_HELP" "此根入口只转发到目标专用卸载脚本。" "root uninstall help should describe forwarding in Chinese"

ZH_IMAGE_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../images/build.sh" --help)"
assert_contains "$ZH_IMAGE_HELP" "用法：deploy/images/build.sh" "image build help should follow Chinese locale"

ZH_ROOT_BUILD_HELP="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../../build.sh" --help)"
assert_contains "$ZH_ROOT_BUILD_HELP" "用法：" "root build help should follow Chinese locale"
assert_contains "$ZH_ROOT_BUILD_HELP" "bash build.sh --package" "root build help should document package mode"

ZH_OFFLINE_DRY_RUN="$(DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../offline/build_offline_package.sh" --version v2.2.0 --platform amd64 --components infrastructure,application --image-source general --target docker --dry-run)"
assert_contains "$ZH_OFFLINE_DRY_RUN" "=== DRY RUN 模式 ===" "offline dry-run should follow Chinese locale"
assert_contains "$ZH_OFFLINE_DRY_RUN" "目标：docker" "offline dry-run target label should follow Chinese locale"

if DEPLOYMENT_LANG="" LANG="zh_CN.UTF-8" bash "$SCRIPT_DIR/../images/build.sh" --unknown >/tmp/nexent-image-build-zh-invalid.log 2>&1; then
  echo "FAIL: unknown image build option should fail"
  exit 1
fi
assert_contains "$(cat /tmp/nexent-image-build-zh-invalid.log)" "未知选项：--unknown" "invalid image build option should follow Chinese locale"

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
DOCKER_SUMMARY="$(deployment_print_summary docker)"
assert_contains "$DOCKER_SUMMARY" "Deployment components: infrastructure,application" "docker summary should include selected components"
assert_contains "$DOCKER_SUMMARY" "Port policy: production" "docker summary should include selected port policy"
assert_contains "$DOCKER_SUMMARY" "Image source: general" "docker summary should include selected image source"
assert_contains "$DOCKER_SUMMARY" "Docker services: " "docker summary should include selected services"
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

unset NEXENT_IMAGE NEXENT_WEB_IMAGE NEXENT_DATA_PROCESS_IMAGE NEXENT_MCP_DOCKER_IMAGE
unset ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE OPENSSH_SERVER_IMAGE
unset SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB
deployment_prepare_config --components infrastructure,application --port-policy development --image-source local-latest --image-registry-prefix https://registry.local/nexent/ --app-version latest
assert_eq "registry.local/nexent" "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" "image registry prefix should be normalized"
deployment_apply_image_source
assert_eq "registry.local/nexent/nexent/nexent:latest" "$NEXENT_IMAGE" "image registry prefix should be applied to local latest backend image"
PREFIXED_DOCKER_ENV="$TMP_DIR/prefixed-docker.env"
deployment_render_docker_env "$PREFIXED_DOCKER_ENV"
assert_contains "$(cat "$PREFIXED_DOCKER_ENV")" 'NEXENT_IMAGE_REGISTRY_PREFIX="registry.local/nexent/"' "docker env should expose registry prefix for monitoring compose images"
PREFIXED_HELM_VALUES="$TMP_DIR/prefixed-generated-values.yaml"
deployment_render_helm_values "$PREFIXED_HELM_VALUES"
PREFIXED_HELM_CONTENT="$(cat "$PREFIXED_HELM_VALUES")"
assert_contains "$PREFIXED_HELM_CONTENT" 'imageRegistryPrefix: "registry.local/nexent"' "helm values should record registry prefix"
assert_contains "$PREFIXED_HELM_CONTENT" 'repository: "registry.local/nexent/nexent/nexent"' "helm values should use prefixed app image repositories"
assert_contains "$PREFIXED_HELM_CONTENT" $'  initImage:\n    repository: "registry.local/nexent/postgres"\n    tag: "15-alpine"\n    pullPolicy: "IfNotPresent"' "helm values should use prefixed supabase auth init image"
assert_contains "$PREFIXED_HELM_CONTENT" 'pullPolicy: "IfNotPresent"' "prefixed local-latest images should be pulled from the registry"
unset NEXENT_IMAGE NEXENT_WEB_IMAGE NEXENT_DATA_PROCESS_IMAGE NEXENT_MCP_DOCKER_IMAGE
unset ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE OPENSSH_SERVER_IMAGE
unset SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB

deployment_prepare_config --components supabase --port-policy development --app-version latest
assert_eq "infrastructure,supabase" "$DEPLOYMENT_COMPONENTS" "only infrastructure should be required and added"
if [[ "$DEPLOYMENT_SELECTED_DOCKER_SERVICES" == *"nexent-web"* ]]; then
  echo "FAIL: application should not be auto-added"
  exit 1
fi

deployment_prepare_config --components infrastructure,application --port-policy development --registry-profile mainland --app-version latest
assert_eq "mainland" "$DEPLOYMENT_IMAGE_SOURCE" "legacy registry profile should map to mainland image source"

DEPLOYMENT_APP_VERSION="v1.2.3"
assert_eq "nexent/nexent:v1.2.3" "$(deployment_image_source_example_tag general)" "general image source description should list backend image tag"
assert_eq "ccr.ccs.tencentyun.com/nexent-hub/nexent:v1.2.3" "$(deployment_image_source_example_tag mainland)" "mainland image source description should list mirrored backend image tag"
assert_eq "nexent/nexent:latest" "$(deployment_image_source_example_tag local-latest)" "local-latest image source description should list local backend image tag"

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

APP_VERSION="v2.2.2"
NEXENT_DEPLOY_CONFIG_MODE=defaults deployment_prepare_config --local-config "$FULL_CONFIG"
assert_eq "v2.2.2" "$DEPLOYMENT_APP_VERSION" "local config appVersion should not override current VERSION"
assert_contains "$DEPLOYMENT_COMPONENTS" "data-process" "local config should still load saved components while ignoring appVersion"
NEXENT_DEPLOY_CONFIG_MODE=defaults deployment_prepare_config --local-config "$FULL_CONFIG" --version v2.2.3
assert_eq "v2.2.3" "$DEPLOYMENT_APP_VERSION" "explicit --version should override current VERSION"
APP_VERSION="latest"

NEXENT_DEPLOY_CONFIG_MODE=defaults deployment_prepare_config --local-config "$FULL_CONFIG" --app-version latest
deployment_apply_image_source
assert_eq "nexent/nexent:latest" "$NEXENT_IMAGE" "local-latest image should be applied"
assert_contains "$DEPLOYMENT_SELECTED_HELM_CHARTS" "nexent-data-process" "data-process chart should be selected"

NEXENT_DEPLOY_CONFIG_MODE=defaults deployment_prepare_config --local-config "$TMP_DIR/missing.yaml" --app-version latest
assert_eq "infrastructure,application,data-process,supabase" "$DEPLOYMENT_COMPONENTS" "defaults mode should use built-in defaults when local config is absent"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "defaults mode should use built-in image source when local config is absent"

deployment_prepare_config --defaults --local-config "$TMP_DIR/missing.yaml" --app-version latest
assert_eq "infrastructure,application,data-process,supabase" "$DEPLOYMENT_COMPONENTS" "--defaults should use built-in defaults when local config is absent"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "--defaults should use built-in image source when local config is absent"

deployment_prepare_config --local-config "$FULL_CONFIG" --defaults --image-source general --app-version latest
assert_eq "true" "$DEPLOYMENT_CONFIG_FILE_LOADED" "--defaults should load saved local config"
assert_contains "$DEPLOYMENT_COMPONENTS" "data-process" "--defaults should include saved components"
assert_eq "development" "$DEPLOYMENT_PORT_POLICY" "--defaults should include saved port policy"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "explicit CLI image source should override --defaults local config"

if deployment_prepare_config --config "$FULL_CONFIG" --app-version latest 2>"$TMP_DIR/config-tui-error.log"; then
  echo "FAIL: --config should request interactive TUI and fail without a TTY"
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/config-tui-error.log")" "Interactive deployment configuration requires a TTY." "--config should no longer load a config file path"
if deployment_prepare_config --defaults --config --app-version latest 2>"$TMP_DIR/defaults-config-tui-error.log"; then
  echo "FAIL: --config should override earlier --defaults and require a TTY"
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/defaults-config-tui-error.log")" "Interactive deployment configuration requires a TTY." "--config should override earlier --defaults"
deployment_prepare_config --config --defaults --local-config "$FULL_CONFIG" --app-version latest
assert_eq "true" "$DEPLOYMENT_CONFIG_FILE_LOADED" "--defaults should override earlier --config when it appears later"
if NEXENT_DEPLOY_CONFIG_MODE=tui deployment_prepare_config --app-version latest 2>"$TMP_DIR/mode-tui-error.log"; then
  echo "FAIL: NEXENT_DEPLOY_CONFIG_MODE=tui should fail without a TTY"
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/mode-tui-error.log")" "Interactive deployment configuration requires a TTY." "tui mode should require a TTY"

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
LOCAL_HELM_CONTENT="$(cat "$LOCAL_HELM_VALUES")"
assert_contains "$LOCAL_HELM_CONTENT" "repository: \"nexent/nexent\"" "local-latest should render mcp chart with backend image"
assert_contains "$LOCAL_HELM_CONTENT" "pullPolicy: \"Never\"" "local-latest should render mcp chart with local pull policy"
assert_contains "$LOCAL_HELM_CONTENT" "repository: \"nexent/nexent-mcp\"" "local-latest should keep common mcp docker image"

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
assert_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-auth/templates/deployment.yaml")" ".Values.initImage.repository" "supabase auth init container should use configurable image repository"
assert_not_contains "$(cat "$K8S_CHART_DIR/charts/nexent-supabase-auth/templates/deployment.yaml")" "image: postgres:15-alpine" "supabase auth init container should not hardcode postgres image"
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

MONITORING_ROOT_ENV="$TMP_DIR/monitoring-root.env"
MONITORING_EXAMPLE_TMP="$TMP_DIR/monitoring.env.example"
MONITORING_ENV_TMP="$TMP_DIR/monitoring.env"
cp "$SCRIPT_DIR/../env/monitoring.env.example" "$MONITORING_EXAMPLE_TMP"
cat > "$MONITORING_ROOT_ENV" <<'ENV'
LANGSMITH_API_KEY=ls-root-fallback
MONITORING_PROVIDER=root-provider
ENV
DEPLOYMENT_ROOT_ENV="$MONITORING_ROOT_ENV"
deployment_source_env_file "$MONITORING_ROOT_ENV"
deployment_prepare_config --components infrastructure,application,monitoring --monitoring-provider langsmith --app-version latest
deployment_prepare_monitoring_env k8s
assert_eq "true" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "ENABLE_TELEMETRY")" "monitoring.env should record selected monitoring enablement"
assert_eq "langsmith" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "MONITORING_PROVIDER")" "monitoring.env should record selected provider"
assert_eq "https://smith.langchain.com/" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL")" "monitoring.env should record K8s dashboard URL"
assert_eq "http://nexent-otel-collector:4318" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "OTEL_EXPORTER_OTLP_ENDPOINT")" "monitoring.env should record K8s OTLP endpoint"
assert_eq "otel-collector-langsmith-config.yml" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "OTEL_COLLECTOR_CONFIG_FILE")" "monitoring.env should record K8s collector config file"
assert_eq "ls-root-fallback" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "LANGSMITH_API_KEY")" "monitoring.env should migrate LangSmith key from root .env when missing"
MONITORING_PAYLOAD="$(deployment_env_values_payload)"
assert_contains "$MONITORING_PAYLOAD" 'MONITORING_PROVIDER="langsmith"' "monitoring.env should override duplicate root monitoring keys in checksum payload"
assert_not_contains "$MONITORING_PAYLOAD" "MONITORING_PROVIDER=root-provider" "root monitoring provider should not win over monitoring.env"
MONITORING_CHECKSUM_A="$(deployment_env_values_checksum)"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "MONITORING_TRACE_MAX_CHARS" "1234"
MONITORING_CHECKSUM_B="$(deployment_env_values_checksum)"
assert_not_eq "$MONITORING_CHECKSUM_A" "$MONITORING_CHECKSUM_B" "env checksum should change when monitoring.env changes"
MONITORING_HELM_VALUES="$TMP_DIR/monitoring-generated-values.yaml"
deployment_render_helm_values "$MONITORING_HELM_VALUES"
MONITORING_HELM_CONTENT="$(cat "$MONITORING_HELM_VALUES")"
assert_contains "$MONITORING_HELM_CONTENT" 'provider: "langsmith"' "Helm values should render monitoring provider from monitoring.env"
assert_contains "$MONITORING_HELM_CONTENT" 'langsmithApiKey: "ls-root-fallback"' "Helm values should pass LangSmith key to monitoring collector values"
assert_contains "$MONITORING_HELM_CONTENT" 'configFile: "otel-collector-langsmith-config.yml"' "Helm values should pass collector config from monitoring.env"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "pk-test"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "LANGFUSE_INIT_PROJECT_SECRET_KEY" "sk-test"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "LANGFUSE_OTLP_AUTH_HEADER" "Basic stale"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL" ""
deployment_prepare_config --components infrastructure,application,monitoring --monitoring-provider langfuse --app-version latest
deployment_prepare_monitoring_env docker
EXPECTED_LANGFUSE_AUTH_HEADER="Basic $(printf "%s:%s" "pk-test" "sk-test" | base64 | tr -d '\n')"
assert_eq "$EXPECTED_LANGFUSE_AUTH_HEADER" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "LANGFUSE_OTLP_AUTH_HEADER")" "monitoring.env should refresh derived Langfuse OTLP auth header"
assert_eq "../assets/monitoring/otel-collector-langfuse-config.yml" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "OTEL_COLLECTOR_CONFIG_FILE")" "monitoring.env should record Docker collector config file"
assert_eq "http://localhost:3001" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL")" "empty monitoring dashboard URL should use the selected provider default"
deployment_update_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL" "https://monitor.example.com/grafana"
deployment_prepare_config --components infrastructure,application,monitoring --monitoring-provider grafana --app-version latest
deployment_prepare_monitoring_env docker
assert_eq "https://monitor.example.com/grafana" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL")" "explicit monitoring dashboard URL should be preserved"
deployment_prepare_config --components infrastructure,application --monitoring-provider grafana --app-version latest
deployment_prepare_monitoring_env docker
assert_eq "" "$(deployment_get_env_var_file "$MONITORING_ENV_TMP" "MONITORING_DASHBOARD_URL")" "disabled monitoring should clear dashboard URL"
while IFS='=' read -r key _; do
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
  unset "$key"
done < "$MONITORING_EXAMPLE_TMP"
unset DEPLOYMENT_MONITORING_PROVIDER

DEPLOYMENT_ROOT_ENV="$TMP_DIR/missing-env-file.env"
MISSING_ENV_CHECKSUM_A="$(deployment_env_values_checksum 2>/dev/null)"
MISSING_ENV_CHECKSUM_B="$(deployment_env_values_checksum 2>/dev/null)"
assert_eq "$MISSING_ENV_CHECKSUM_A" "$MISSING_ENV_CHECKSUM_B" "missing env file should use a stable empty checksum fallback"

K8S_DEPLOY_CHECKSUM_BLOCK="$(awk '/render_runtime_secret_values\(\) {/,/deployment_render_image_rollout_checksums/' "$SCRIPT_DIR/../k8s/deploy.sh")"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" 'env_checksum="$(deployment_env_values_checksum)"' "k8s deploy should compute rollout checksum from root and monitoring env files"
assert_contains "$K8S_DEPLOY_CHECKSUM_BLOCK" "printf '    env: %s\\n'" "k8s deploy should render the combined env checksum under the env name"
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
if deployment_prepare_config --local-config "$FULL_CONFIG" --reconfigure --image-source general --app-version latest 2>"$TMP_DIR/reconfigure-tui-error.log"; then
  echo "FAIL: --reconfigure should request interactive TUI and fail without a TTY"
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/reconfigure-tui-error.log")" "Interactive deployment configuration requires a TTY." "--reconfigure should require a TTY"
NEXENT_DEPLOY_CONFIG_MODE=defaults deployment_prepare_config --local-config "$FULL_CONFIG" --image-source general --app-version latest
assert_eq "true" "$DEPLOYMENT_CONFIG_FILE_LOADED" "defaults mode should load local config without entering TUI"
assert_contains "$DEPLOYMENT_COMPONENTS" "data-process" "defaults mode should include saved components"
assert_eq "development" "$DEPLOYMENT_PORT_POLICY" "defaults mode should include saved port policy"
assert_eq "general" "$DEPLOYMENT_IMAGE_SOURCE" "explicit image source should override defaults mode local config"
unset DEPLOYMENT_VERSION

HELM_VALUES="$TMP_DIR/generated-values.yaml"
deployment_render_helm_values "$HELM_VALUES"
assert_contains "$(sed -n '1,220p' "$HELM_VALUES")" "data-process: true" "component table should include data-process"
assert_contains "$(sed -n '1,260p' "$HELM_VALUES")" "type: \"NodePort\"" "development policy should render NodePort values"
assert_contains "$(sed -n '1,260p' "$HELM_VALUES")" "enabled: true" "selected charts should be enabled"

DOCKER_ENV="$TMP_DIR/.env.generated"
deployment_render_docker_env "$DOCKER_ENV"
assert_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "NEXENT_IMAGE=" "docker generated env should contain image variables"
assert_not_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "ENABLE_TELEMETRY=" "docker generated env should not contain monitoring enablement"
assert_not_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "MONITORING_PROVIDER=" "docker generated env should not contain monitoring provider"
assert_not_contains "$(sed -n '1,120p' "$DOCKER_ENV")" "MONITORING_DASHBOARD_URL=" "docker generated env should not contain monitoring dashboard URL"
if grep -Eq '^DEPLOYMENT_(SCHEMA_VERSION|COMPONENTS|PORT_POLICY|IMAGE_SOURCE|REGISTRY_PROFILE|APP_VERSION|MONITORING_PROVIDER|SELECTED_DOCKER_SERVICES|DOCKER_PORTS)=' "$DOCKER_ENV"; then
  echo "FAIL: docker generated env should not contain persisted deployment decisions"
  exit 1
fi

COMMON_MONITORING_CONFIG_BLOCK="$(awk '/deployment_monitoring_env_example_file\(\)/,/^deployment_sha256_string\(\)/' "$SCRIPT_DIR/../common/common.sh")"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'deployment_prepare_monitoring_env()' "common deploy should prepare monitoring.env"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'deployment_sync_env_defaults "$example_file" "$env_file"' "common deploy should sync monitoring.env defaults"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'deployment_source_env_file "$env_file"' "common deploy should source generated monitoring.env"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'deployment_update_monitoring_env_var "OTEL_EXPORTER_OTLP_ENDPOINT" "$otlp_endpoint"' "common deploy should persist target OTLP endpoint in monitoring.env"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'deployment_update_monitoring_env_var "OTEL_COLLECTOR_CONFIG_FILE" "$collector_config_file"' "common deploy should persist monitoring collector config in monitoring.env"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'otel-collector-phoenix-config.yml' "common deploy should map phoenix to its collector config"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'otel-collector-langfuse-config.yml' "common deploy should map langfuse to its collector config"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'otel-collector-langsmith-config.yml' "common deploy should map langsmith to its collector config"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'otel-collector-grafana-config.yml' "common deploy should map grafana to its collector config"
assert_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'otel-collector-zipkin-config.yml' "common deploy should map zipkin to its collector config"
assert_not_contains "$COMMON_MONITORING_CONFIG_BLOCK" 'update_env_var "OTEL_EXPORTER_OTLP_ENDPOINT"' "common monitoring prep should not write monitoring keys to deploy/env/.env"

DOCKER_MONITORING_CONFIG_BLOCK="$(awk '/docker_monitoring_active_services\(\)/,/^pull_mcp_image\(\)/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'deployment_prepare_monitoring_env docker' "docker deploy should use shared monitoring.env preparation"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'docker_monitoring_active_services()' "docker deploy should define active monitoring services"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'docker_monitoring_profile_services()' "docker deploy should enumerate monitoring profile services"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'docker_monitoring_container_names()' "docker deploy should enumerate monitoring containers for cleanup"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'stop_monitoring_services()' "docker deploy should define full monitoring stop cleanup"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'cleanup_stale_monitoring_services()' "docker deploy should define stale monitoring cleanup"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'langfuse-worker langfuse-web langfuse-clickhouse langfuse-minio langfuse-redis langfuse-postgres' "docker deploy should treat Langfuse services as one provider bundle"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'down --remove-orphans' "docker deploy should stop monitoring services when monitoring is disabled"
assert_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'rm -f "${stale_services[@]}"' "docker deploy should remove stale monitoring containers without deleting volumes"
assert_not_contains "$DOCKER_MONITORING_CONFIG_BLOCK" 'update_env_var "OTEL_EXPORTER_OTLP_ENDPOINT"' "docker deploy should not write monitoring keys to deploy/env/.env"
assert_not_contains "$DOCKER_MONITORING_CONFIG_BLOCK" "LANGFUSE_OLTP_AUTH_HEADER" "docker deploy should not use the misspelled Langfuse OLTP auth header alias"

if [ -e "$SCRIPT_DIR/../docker/start-monitoring.sh" ]; then
  echo "FAIL: standalone monitoring script should be removed"
  exit 1
fi
DOCKER_COMPOSE_FILE="$SCRIPT_DIR/../docker/compose/docker-compose.yml"
DOCKER_PROD_COMPOSE_FILE="$SCRIPT_DIR/../docker/compose/docker-compose.prod.yml"
DOCKER_DEV_COMPOSE_FILE="$SCRIPT_DIR/../docker/compose/docker-compose.dev.yml"
for compose_file in "$DOCKER_COMPOSE_FILE" "$DOCKER_PROD_COMPOSE_FILE"; do
  assert_contains "$(awk '/^  nexent-config:/,/^  nexent-runtime:/' "$compose_file")" $'env_file:\n      - ../../env/.env\n      - ../../env/monitoring.env' "docker config service should load monitoring.env after root .env"
  assert_contains "$(awk '/^  nexent-runtime:/,/^  nexent-mcp:/' "$compose_file")" $'env_file:\n      - ../../env/.env\n      - ../../env/monitoring.env' "docker runtime service should load monitoring.env after root .env"
  assert_not_contains "$(awk '/^  nexent-mcp:/,/^  nexent-northbound:/' "$compose_file")" "monitoring.env" "docker mcp service should not receive monitoring.env"
  assert_not_contains "$(awk '/^  nexent-northbound:/,/^  nexent-web:/' "$compose_file")" "monitoring.env" "docker northbound service should not receive monitoring.env"
  assert_not_contains "$(awk '/^  nexent-data-process:/,/^  redis:/' "$compose_file")" "monitoring.env" "docker data-process service should not receive monitoring.env"
done
assert_not_contains "$(cat "$DOCKER_DEV_COMPOSE_FILE")" "monitoring.env" "docker dev data-process compose should not receive monitoring.env"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'LANGFUSE_OTLP_AUTH_HEADER: ${LANGFUSE_OTLP_AUTH_HEADER:-}' "docker monitoring compose should pass Langfuse OTLP auth header to the collector"
assert_not_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" "LANGFUSE_OLTP_AUTH_HEADER" "docker monitoring compose should not pass the misspelled Langfuse auth header alias"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/templates/otel-collector.yaml")" "LANGFUSE_OTLP_AUTH_HEADER" "k8s collector should pass Langfuse OTLP auth header"
assert_not_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/templates/otel-collector.yaml")" "LANGFUSE_OLTP_AUTH_HEADER" "k8s collector should not pass the misspelled Langfuse auth header alias"

DOCKER_DEPLOY_MONITORING_BLOCK="$(awk '/deploy_monitoring\(\)/,/^configure_root_dir_from_env\(\)/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'stop_monitoring_services || return 1' "docker deploy should stop monitoring services when the component is disabled"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'LANGSMITH_API_KEY is required' "docker deploy should fail fast when LangSmith API key is missing"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'profile_args+=(--profile "$DEPLOYMENT_MONITORING_PROVIDER")' "docker deploy should keep provider-specific compose profiles"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" 'cleanup_stale_monitoring_services || return 1' "docker deploy should remove stale monitoring provider services before starting selected provider"
assert_contains "$DOCKER_DEPLOY_MONITORING_BLOCK" '--env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE"' "docker deploy should load generated monitoring.env for monitoring compose"

DOCKER_UNINSTALL_CONTENT="$(cat "$SCRIPT_DIR/../docker/uninstall.sh")"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'MONITORING_ENV_FILE="$PROJECT_ROOT/deploy/env/monitoring.env"' "docker uninstall should know the generated monitoring env file"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'env_file_args+=(--env-file "$MONITORING_ENV_FILE")' "docker uninstall should load generated monitoring.env when downing monitoring compose"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'docker_compose_down_file "$COMPOSE_DIR/docker-compose-monitoring.yml" false "$remove_volumes"' "docker uninstall should down the monitoring compose file"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'remove_docker_containers_by_name < <(monitoring_container_names)' "docker uninstall should remove monitoring containers by name as a fallback"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'nexent-otel-collector' "docker uninstall should include the collector container in fallback cleanup"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'nexent-langfuse-web' "docker uninstall should include Langfuse containers in fallback cleanup"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'nexent-grafana' "docker uninstall should include Grafana containers in fallback cleanup"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'nexent-zipkin' "docker uninstall should include Zipkin containers in fallback cleanup"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'monitor_langfuse-postgres-data' "docker uninstall should include monitoring volumes in delete-all cleanup"
assert_contains "$DOCKER_UNINSTALL_CONTENT" 'remove_docker_volumes_by_name < <(monitoring_volume_names)' "docker uninstall should remove monitoring volumes when delete-volumes is enabled"

K8S_UNINSTALL_CONTENT="$(cat "$SCRIPT_DIR/../k8s/uninstall.sh")"
assert_contains "$K8S_UNINSTALL_CONTENT" "cleanup_leftover_monitoring_resources()" "k8s uninstall should define monitoring fallback cleanup"
assert_contains "$K8S_UNINSTALL_CONTENT" "deployment,service,configmap,rs,pod" "k8s monitoring fallback should remove workloads and service resources"
assert_contains "$K8S_UNINSTALL_CONTENT" "nexent-otel-collector" "k8s monitoring fallback should include the collector"
assert_contains "$K8S_UNINSTALL_CONTENT" "nexent-langfuse-web" "k8s monitoring fallback should include Langfuse"
assert_contains "$K8S_UNINSTALL_CONTENT" "nexent-grafana" "k8s monitoring fallback should include Grafana"
assert_contains "$K8S_UNINSTALL_CONTENT" "nexent-zipkin" "k8s monitoring fallback should include Zipkin"
assert_contains "$K8S_UNINSTALL_CONTENT" "cleanup_leftover_nexent_resources" "k8s uninstall should use shared leftover cleanup"

MONITORING_EXAMPLE_FILE="$SCRIPT_DIR/../env/monitoring.env.example"
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

if [ -f "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env.example" ]; then
  echo "FAIL: monitoring.env.example should live under deploy/env"
  exit 1
fi
if [ -f "$SCRIPT_DIR/../docker/assets/monitoring/monitoring.env" ]; then
  echo "FAIL: monitoring.env should live under deploy/env"
  exit 1
fi
ROOT_ENV_EXAMPLE_CONTENT="$(cat "$SCRIPT_DIR/../env/.env.example")"
assert_not_contains "$ROOT_ENV_EXAMPLE_CONTENT" "ENABLE_TELEMETRY=" "root .env.example should not contain monitoring enablement"
assert_not_contains "$ROOT_ENV_EXAMPLE_CONTENT" "MONITORING_PROVIDER=" "root .env.example should not contain monitoring provider"
assert_not_contains "$ROOT_ENV_EXAMPLE_CONTENT" "OTEL_EXPORTER_OTLP_ENDPOINT=" "root .env.example should not contain OTLP endpoint"
assert_not_contains "$ROOT_ENV_EXAMPLE_CONTENT" "TELEMETRY_SAMPLE_RATE=" "root .env.example should not contain telemetry sampling"
assert_contains "$(cat "$MONITORING_EXAMPLE_FILE")" "GRAFANA_ADMIN_PASSWORD=nexent@4321" "docker monitoring defaults should define Grafana admin password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-nexent@4321}' "docker compose Grafana password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "adminPassword: nexent@4321" "k8s monitoring Grafana password should match docker monitoring default"
assert_contains "$(cat "$MONITORING_EXAMPLE_FILE")" "LANGFUSE_POSTGRES_PASSWORD=nexent@4321" "docker monitoring defaults should define Langfuse postgres password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'LANGFUSE_POSTGRES_PASSWORD:-nexent@4321' "docker compose Langfuse postgres password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "password: nexent@4321" "k8s monitoring Langfuse postgres password should match docker monitoring default"
assert_contains "$(cat "$MONITORING_EXAMPLE_FILE")" "LANGFUSE_INIT_USER_PASSWORD=nexent@4321" "docker monitoring defaults should define Langfuse init user password"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD:-nexent@4321}' "docker compose Langfuse init user password fallback should match monitoring.env.example"
assert_contains "$(cat "$SCRIPT_DIR/../k8s/helm/nexent/charts/nexent-monitoring/values.yaml")" "userPassword: nexent@4321" "k8s monitoring Langfuse init user password should match docker monitoring default"
assert_contains "$(cat "$MONITORING_EXAMPLE_FILE")" "LANGFUSE_CLICKHOUSE_CLUSTER_ENABLED=false" "docker monitoring defaults should include all compose Langfuse clickhouse settings"
assert_contains "$(cat "$SCRIPT_DIR/../docker/compose/docker-compose-monitoring.yml")" 'CLICKHOUSE_CLUSTER_ENABLED: ${LANGFUSE_CLICKHOUSE_CLUSTER_ENABLED:-false}' "docker compose Langfuse clickhouse cluster fallback should match monitoring.env.example"

LOCAL_CONFIG="$TMP_DIR/local-config.yaml"
DEPLOYMENT_IMAGE_REGISTRY_PREFIX="registry.local/nexent"
deployment_persist_local_config "$LOCAL_CONFIG"
if grep -Eq 'PASSWORD|TOKEN|JWT|SECRET|KEY' "$LOCAL_CONFIG"; then
  echo "FAIL: persisted local config should not contain secret-looking fields"
  exit 1
fi
if grep -q 'registryProfile' "$LOCAL_CONFIG"; then
  echo "FAIL: persisted local config should not contain registryProfile"
  exit 1
fi
if grep -q 'appVersion' "$LOCAL_CONFIG"; then
  echo "FAIL: persisted local config should not contain appVersion"
  exit 1
fi
assert_contains "$(cat "$LOCAL_CONFIG")" 'imageRegistryPrefix: "registry.local/nexent"' "persisted local config should include image registry prefix"

K8S_DEPLOY_OPTIONS_BLOCK="$(awk '/persist_deploy_options\(\) {/,/^}/' "$SCRIPT_DIR/../k8s/deploy.sh")"
assert_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'echo "PERSISTENCE_MODE=\"${PERSISTENCE_MODE}\""' "k8s deploy options should persist persistence mode"
assert_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'echo "STORAGE_CLASS_NAME=\"${STORAGE_CLASS_NAME}\""' "k8s deploy options should persist storage class"
assert_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'echo "LOCAL_PATH=\"${LOCAL_PATH}\""' "k8s deploy options should persist local path"
assert_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'echo "EXISTING_CLAIM_PREFIX=\"${EXISTING_CLAIM_PREFIX}\""' "k8s deploy options should persist existing claim prefix"
assert_not_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'LOCAL_NODE_NAME=' "k8s deploy options should not persist deprecated local node name"
assert_not_contains "$K8S_DEPLOY_OPTIONS_BLOCK" 'K8S_WAIT_TIMEOUT_SECONDS=' "k8s deploy options should not persist one-time wait timeout"
if echo "$K8S_DEPLOY_OPTIONS_BLOCK" | grep -Eq 'PASSWORD|TOKEN|JWT|SECRET|KEY'; then
  echo "FAIL: k8s deploy options should not persist secret-looking fields"
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
