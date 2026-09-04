#!/bin/bash
# Helm Deployment Script for Nexent
# Usage: ./deploy.sh [apply] [options]
#
# Deploy only. Use uninstall.sh for uninstall and cleanup commands.

set -e

# Use absolute path relative to the script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APPLICATION_CHART_DIR="$SCRIPT_DIR/helm/nexent"
INFRASTRUCTURE_CHART_DIR="$SCRIPT_DIR/helm/nexent-infrastructure"
CHART_DIR="$APPLICATION_CHART_DIR"
COMMON_VALUES="$APPLICATION_CHART_DIR/charts/nexent-common/values.yaml"
NAMESPACE="nexent"
APPLICATION_RELEASE_NAME="nexent"
INFRASTRUCTURE_RELEASE_NAME="nexent-infrastructure"
RELEASE_SCOPE="all"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"
VERSION_HELPER="$DEPLOY_ROOT/common/version.sh"

# Constants for deployment options
K8S_ROOT="$SCRIPT_DIR"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
GENERATED_VALUES="$APPLICATION_CHART_DIR/generated-values.yaml"
GENERATED_RUNTIME_VALUES="$APPLICATION_CHART_DIR/generated-runtime-values.yaml"
GENERATED_SECRETS_VALUES="$APPLICATION_CHART_DIR/generated-secrets-values.yaml"
GENERATED_PERSISTENCE_VALUES="$APPLICATION_CHART_DIR/generated-persistence-values.yaml"
INFRASTRUCTURE_GENERATED_VALUES="$INFRASTRUCTURE_CHART_DIR/generated-values.yaml"
INFRASTRUCTURE_GENERATED_RUNTIME_VALUES="$INFRASTRUCTURE_CHART_DIR/generated-runtime-values.yaml"
INFRASTRUCTURE_GENERATED_SECRETS_VALUES="$INFRASTRUCTURE_CHART_DIR/generated-secrets-values.yaml"
INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES="$INFRASTRUCTURE_CHART_DIR/generated-persistence-values.yaml"
ROOT_ENV_FILE="$DEPLOY_ROOT/env/.env"
SQL_INIT_FILE="$DEPLOY_ROOT/sql/init.sql"
SUPABASE_SQL_DIR="$DEPLOY_ROOT/sql/supabase"
OFFICIAL_SKILLS_SOURCE_DIR="$DEPLOY_ROOT/docker/assets/official-skills-zip"
OFFICIAL_SKILLS_TARGET_DIR="/mnt/nexent/official-skills-zip"

if [ -f "$DEPLOYMENT_COMMON" ]; then
    # shellcheck source=/dev/null
    source "$DEPLOYMENT_COMMON"
else
    echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON"
    exit 1
fi

if [ -f "$VERSION_HELPER" ]; then
    # shellcheck source=/dev/null
    source "$VERSION_HELPER"
fi

# Global variables for deployment options
IS_MAINLAND=""
APP_VERSION=""
DEPLOYMENT_VERSION=""
VERSION_CHOICE_SAVED=""
PERSISTENCE_MODE="local"
STORAGE_CLASS_NAME=""
LOCAL_PATH="/var/lib/nexent-data"
LOCAL_NODE_NAME=""
EXISTING_CLAIM_PREFIX=""
K8S_WAIT_TIMEOUT_SECONDS="${NEXENT_K8S_WAIT_TIMEOUT_SECONDS:-600}"

# Parse command line arguments. The optional "apply" command is kept as a deploy alias.
COMMAND="apply"
case "${1:-}" in
  --help|-h)
    COMMAND="help"
    shift
    ;;
  ""|--*)
    ;;
  apply|deploy)
    COMMAND="apply"
    shift
    ;;
  delete|delete-all|clean)
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "K8s 卸载和清理已迁移到 uninstall.sh。"
      echo "请使用：bash uninstall.sh ${1}"
    else
      echo "K8s uninstall and cleanup have moved to uninstall.sh."
      echo "Use: bash uninstall.sh ${1}"
    fi
    exit 1
    ;;
  *)
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "未知命令：$1"
      echo "用法：$0 [apply] [选项]"
      echo "卸载：bash uninstall.sh"
    else
      echo "Unknown command: $1"
      echo "Usage: $0 [apply] [options]"
      echo "Uninstall: bash uninstall.sh"
    fi
    exit 1
    ;;
esac
if [ "$COMMAND" = "apply" ] && { [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; }; then
  COMMAND="help"
  shift
fi
ORIGINAL_ARGS=("$@")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --is-mainland)
      IS_MAINLAND="$2"
      K8S_IS_MAINLAND_EXPLICIT="true"
      shift 2
      ;;
    --version)
      APP_VERSION="$2"
      K8S_APP_VERSION_EXPLICIT="true"
      shift 2
      ;;
    --deployment-version)
      DEPLOYMENT_VERSION="$2"
      K8S_DEPLOYMENT_VERSION_EXPLICIT="true"
      shift 2
      ;;
    --persistence-mode)
      PERSISTENCE_MODE="$2"
      K8S_PERSISTENCE_MODE_EXPLICIT="true"
      shift 2
      ;;
    --storage-class|--storageclass|--storage-class-name|--sc)
      STORAGE_CLASS_NAME="$2"
      K8S_STORAGE_CLASS_NAME_EXPLICIT="true"
      shift 2
      ;;
    --local-path)
      LOCAL_PATH="$2"
      K8S_LOCAL_PATH_EXPLICIT="true"
      shift 2
      ;;
    --local-node-name)
      LOCAL_NODE_NAME="$2"
      shift 2
      ;;
    --existing-claim-prefix)
      EXISTING_CLAIM_PREFIX="$2"
      K8S_EXISTING_CLAIM_PREFIX_EXPLICIT="true"
      shift 2
      ;;
    --wait-timeout)
      K8S_WAIT_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --release-scope)
      RELEASE_SCOPE="$2"
      shift 2
      ;;
    --rotate-secrets|--refresh-es-key)
      shift
      ;;
    *)
      shift
      ;;
  esac
done

case "$RELEASE_SCOPE" in
  all|infrastructure|nexent) ;;
  *)
    echo "Error: --release-scope must be all, infrastructure, or nexent."
    exit 1
    ;;
esac

cd "$SCRIPT_DIR"
if [ "$COMMAND" != "help" ]; then
    deployment_source_root_env "$PROJECT_ROOT" "$PROJECT_ROOT/docker" || exit 1
fi

# Helper function to sanitize input (remove Windows CR)
sanitize_input() {
  local input="$1"
  printf "%s" "$input" | tr -d '\r'
}

apply_deployment_common_config() {
    load_deploy_options

    if [ -z "$APP_VERSION" ]; then
        APP_VERSION=$(get_app_version)
    fi
    if [ -n "$APP_VERSION" ]; then
        export APP_VERSION
    fi

    deployment_prepare_config "${ORIGINAL_ARGS[@]}" || return 1

    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        DEPLOYMENT_VERSION="full"
    else
        DEPLOYMENT_VERSION="speed"
    fi

    APP_VERSION="$DEPLOYMENT_APP_VERSION"
    VERSION_CHOICE_SAVED="$DEPLOYMENT_VERSION"

    case "$DEPLOYMENT_REGISTRY_PROFILE" in
        mainland)
            IS_MAINLAND_SAVED="Y"
            source "$DEPLOY_ROOT/env/image-source.mainland.env"
            ;;
        general|local-latest)
            IS_MAINLAND_SAVED="N"
            source "$DEPLOY_ROOT/env/image-source.general.env"
            ;;
    esac

    validate_persistence_mode || return 1
    deployment_print_summary k8s
    echo "Helm release scope: $RELEASE_SCOPE"
    case "$RELEASE_SCOPE" in
      all) echo "Helm releases: $INFRASTRUCTURE_RELEASE_NAME -> $APPLICATION_RELEASE_NAME" ;;
      infrastructure) echo "Helm release: $INFRASTRUCTURE_RELEASE_NAME" ;;
      nexent) echo "Helm release: $APPLICATION_RELEASE_NAME (requires $INFRASTRUCTURE_RELEASE_NAME)" ;;
    esac
}


persistence_existing_claim() {
  local component="$1"
  if [ -n "$EXISTING_CLAIM_PREFIX" ]; then
    printf '%s-%s' "$EXISTING_CLAIM_PREFIX" "$component"
  fi
}

render_one_persistence_values() {
  local output_file="$1"
  local chart="$2"
  local component="$3"
  local size="$4"
  local storage_class="$STORAGE_CLASS_NAME"
  [ -n "$storage_class" ] || storage_class="nexent-local"
  [ "$PERSISTENCE_MODE" = "dynamic" ] && [ "$STORAGE_CLASS_NAME" = "" ] && storage_class=""

  {
    printf '%s:\n' "$chart"
    printf '  persistence:\n'
    printf '    mode: "%s"\n' "$PERSISTENCE_MODE"
    printf '    storageClassName: "%s"\n' "$storage_class"
    printf '    accessModes:\n'
    printf '      - ReadWriteMany\n'
    printf '    localPath: "%s/%s"\n' "$LOCAL_PATH" "$component"
    printf '    existingClaim: "%s"\n' "$(persistence_existing_claim "$component")"
    printf '  storage:\n'
    printf '    size: "%s"\n' "$size"
  } >> "$output_file"
}

render_monitoring_persistence_values() {
  local output_file="$1"
  local storage_class="$STORAGE_CLASS_NAME"
  [ -n "$storage_class" ] || storage_class="nexent-local"
  [ "$PERSISTENCE_MODE" = "dynamic" ] && [ "$STORAGE_CLASS_NAME" = "" ] && storage_class=""

  {
    printf 'nexent-monitoring:\n'
    printf '  persistence:\n'
    printf '    enabled: true\n'
    printf '    mode: "%s"\n' "$PERSISTENCE_MODE"
    printf '    storageClassName: "%s"\n' "$storage_class"
    printf '    accessModes:\n'
    printf '      - ReadWriteMany\n'
    printf '    localPath: "%s"\n' "$LOCAL_PATH"
    printf '    existingClaimPrefix: "%s"\n' "$EXISTING_CLAIM_PREFIX"
  } >> "$output_file"
}

render_shared_storage_persistence_values() {
  local output_file="$1"
  local storage_class="$STORAGE_CLASS_NAME"
  [ -n "$storage_class" ] || storage_class="nexent-local"
  [ "$PERSISTENCE_MODE" = "dynamic" ] && [ "$STORAGE_CLASS_NAME" = "" ] && storage_class=""

  {
    printf 'global:\n'
    printf '  sharedStorage:\n'
    printf '    mode: "%s"\n' "$PERSISTENCE_MODE"
    printf '    storageClassName: "%s"\n' "$storage_class"
    printf '    accessModes:\n'
    printf '      - ReadWriteMany\n'
    printf '    workspace:\n'
    printf '      size: "10Gi"\n'
    printf '      localPath: "/var/lib/nexent"\n'
    printf '      existingClaim: "%s"\n' "$(persistence_existing_claim "nexent-workspace")"
    printf '    skills:\n'
    printf '      size: "5Gi"\n'
    printf '      localPath: "%s/skills"\n' "$LOCAL_PATH"
    printf '      existingClaim: "%s"\n' "$(persistence_existing_claim "nexent-skills")"
    printf '    logs:\n'
    printf '      size: "5Gi"\n'
    printf '      localPath: "%s/logs"\n' "$LOCAL_PATH"
    printf '      existingClaim: "%s"\n' "$(persistence_existing_claim "nexent-logs")"
  } >> "$output_file"
}

validate_persistence_mode() {
  case "$PERSISTENCE_MODE" in
    local|dynamic|existing) ;;
    *)
      echo "Unsupported persistence mode: $PERSISTENCE_MODE"
      echo "Use local, dynamic, or existing."
      return 1
      ;;
  esac
}

render_persistence_values() {
  validate_persistence_mode || exit 1

  echo "# Generated application persistence overrides" > "$GENERATED_PERSISTENCE_VALUES"
  render_shared_storage_persistence_values "$GENERATED_PERSISTENCE_VALUES"
  render_one_persistence_values "$GENERATED_PERSISTENCE_VALUES" "nexent-supabase-db" "nexent-supabase-db" "10Gi"
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    render_monitoring_persistence_values "$GENERATED_PERSISTENCE_VALUES"
  fi

  echo "# Generated infrastructure persistence overrides" > "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES"
  render_one_persistence_values "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES" "nexent-elasticsearch" "nexent-elasticsearch" "20Gi"
  render_one_persistence_values "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES" "nexent-postgresql" "nexent-postgresql" "10Gi"
  render_one_persistence_values "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES" "nexent-redis" "nexent-redis" "5Gi"
  render_one_persistence_values "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES" "nexent-minio" "nexent-minio" "20Gi"
}

yaml_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

env_or_default() {
  local key="$1"
  local default_value="$2"
  if [ "${!key+x}" = "x" ]; then
    printf '%s' "${!key}"
  else
    printf '%s' "$default_value"
  fi
}

render_yaml_literal_file() {
  local key="$1"
  local file="$2"
  local key_indent="$3"
  local content_indent="$4"
  local key_padding
  local content_padding

  if [ ! -f "$file" ]; then
    echo "Error: SQL file not found: $file"
    exit 1
  fi

  key_padding="$(printf '%*s' "$key_indent" '')"
  content_padding="$(printf '%*s' "$content_indent" '')"
  printf '%s%s: |\n' "$key_padding" "$key"
  sed "s/^/${content_padding}/" "$file"
  printf '\n'
}

sql_files_checksum() {
  local payload=""
  local file rel checksum
  if [ -d "$DEPLOY_ROOT/sql/migrations" ]; then
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      rel="${file#"$DEPLOY_ROOT/sql/"}"
      checksum="$(deployment_sha256_file "$file")"
      payload="${payload}${rel}:${checksum}"$'\n'
    done < <(find "$DEPLOY_ROOT/sql/migrations" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
  fi
  if [ -d "$SUPABASE_SQL_DIR" ]; then
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      rel="${file#"$DEPLOY_ROOT/sql/"}"
      checksum="$(deployment_sha256_file "$file")"
      payload="${payload}${rel}:${checksum}"$'\n'
    done < <(find "$SUPABASE_SQL_DIR" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
  fi
  deployment_sha256_string "$payload"
}

render_infrastructure_runtime_values() {
  local output_file="$1"
  if [ ! -f "$SQL_INIT_FILE" ]; then
    echo "Error: SQL init file not found: $SQL_INIT_FILE"
    exit 1
  fi

  {
    echo "global:"
    echo "  rolloutChecksums:"
    printf '    sql: %s\n' "$(yaml_quote "$(deployment_sha256_file "$SQL_INIT_FILE")")"
    echo "nexent-infrastructure-common:"
    echo "  sqlFiles:"
    render_yaml_literal_file "init" "$SQL_INIT_FILE" 4 6
  } > "$output_file"
}

render_k8s_runtime_config_values() {
  local output_file="$1"
  local file
  if [ ! -f "$SQL_INIT_FILE" ]; then
    echo "Error: SQL init file not found: $SQL_INIT_FILE"
    exit 1
  fi
  if [ ! -d "$DEPLOY_ROOT/sql/migrations" ]; then
    echo "Error: SQL migrations directory not found: $DEPLOY_ROOT/sql/migrations"
    exit 1
  fi
  if [ ! -d "$SUPABASE_SQL_DIR" ]; then
    echo "Error: Supabase SQL directory not found: $SUPABASE_SQL_DIR"
    exit 1
  fi
  {
    echo "global:"
    echo "  sqlFileNames:"
    echo "    migrations:"
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      printf '      - %s\n' "$(yaml_quote "$(basename "$file")")"
    done < <(find "$DEPLOY_ROOT/sql/migrations" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
    echo "    supabase:"
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      printf '      - %s\n' "$(yaml_quote "$(basename "$file")")"
    done < <(find "$SUPABASE_SQL_DIR" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
    echo "nexent-common:"
    echo "  sqlFiles:"
    echo "    migrations:"
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      render_yaml_literal_file "$(basename "$file")" "$file" 6 8
    done < <(find "$DEPLOY_ROOT/sql/migrations" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
    echo "    supabase:"
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      render_yaml_literal_file "$(basename "$file")" "$file" 6 8
    done < <(find "$SUPABASE_SQL_DIR" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
    echo "  config:"
    echo "    services:"
    printf '      configUrl: %s\n' "$(yaml_quote "$(env_or_default CONFIG_SERVICE_URL "http://nexent-config:5010")")"
    printf '      elasticsearchService: %s\n' "$(yaml_quote "$(env_or_default ELASTICSEARCH_SERVICE "http://nexent-config:5010/api")")"
    printf '      runtimeUrl: %s\n' "$(yaml_quote "$(env_or_default RUNTIME_SERVICE_URL "http://nexent-runtime:5014")")"
    printf '      mcpServer: %s\n' "$(yaml_quote "$(env_or_default NEXENT_MCP_SERVER "http://nexent-mcp:5011")")"
    printf '      mcpManagementServer: %s\n' "$(yaml_quote "$(env_or_default MCP_MANAGEMENT_API "http://nexent-mcp:5015")")"
    printf '      dataProcessService: %s\n' "$(yaml_quote "$(env_or_default DATA_PROCESS_SERVICE "http://nexent-data-process:5012/api")")"
    printf '      northboundServer: %s\n' "$(yaml_quote "$(env_or_default NORTHBOUND_API_SERVER "http://nexent-northbound:5013/api")")"
    printf '      northboundExternalUrl: %s\n' "$(yaml_quote "$(env_or_default NORTHBOUND_EXTERNAL_URL "")")"
    echo "    postgres:"
    printf '      host: %s\n' "$(yaml_quote "$(env_or_default POSTGRES_HOST "nexent-postgresql")")"
    printf '      user: %s\n' "$(yaml_quote "$(env_or_default POSTGRES_USER "root")")"
    printf '      db: %s\n' "$(yaml_quote "$(env_or_default POSTGRES_DB "nexent")")"
    printf '      port: %s\n' "$(yaml_quote "$(env_or_default POSTGRES_PORT "5432")")"
    echo "    redis:"
    printf '      url: %s\n' "$(yaml_quote "$(env_or_default REDIS_URL "redis://nexent-redis:6379/0")")"
    printf '      backendUrl: %s\n' "$(yaml_quote "$(env_or_default REDIS_BACKEND_URL "redis://nexent-redis:6379/1")")"
    printf '      port: %s\n' "$(yaml_quote "$(env_or_default REDIS_PORT "6379")")"
    echo "    minio:"
    printf '      endpoint: %s\n' "$(yaml_quote "$(env_or_default MINIO_ENDPOINT "http://nexent-minio:9000")")"
    printf '      region: %s\n' "$(yaml_quote "$(env_or_default MINIO_REGION "cn-north-1")")"
    printf '      defaultBucket: %s\n' "$(yaml_quote "$(env_or_default MINIO_DEFAULT_BUCKET "nexent")")"
    echo "    elasticsearch:"
    printf '      host: %s\n' "$(yaml_quote "$(env_or_default ELASTICSEARCH_HOST "http://nexent-elasticsearch:9200")")"
    printf '      javaOpts: %s\n' "$(yaml_quote "$(env_or_default ES_JAVA_OPTS "-Xms2g -Xmx2g")")"
    printf '      diskWatermarkLow: %s\n' "$(yaml_quote "$(env_or_default ES_DISK_WATERMARK_LOW "85%")")"
    printf '      diskWatermarkHigh: %s\n' "$(yaml_quote "$(env_or_default ES_DISK_WATERMARK_HIGH "90%")")"
    printf '      diskWatermarkFloodStage: %s\n' "$(yaml_quote "$(env_or_default ES_DISK_WATERMARK_FLOOD_STAGE "95%")")"
    printf '    skipProxy: %s\n' "$(yaml_quote "$(env_or_default skip_proxy "true")")"
    printf '    umask: %s\n' "$(yaml_quote "$(env_or_default UMASK "0022")")"
    printf '    skillsPath: %s\n' "$(yaml_quote "$(env_or_default SKILLS_PATH "/mnt/nexent-data/skills")")"
    printf '    logDir: %s\n' "$(yaml_quote "$(env_or_default LOG_DIR "/mnt/nexent-data/logs")")"
    echo "    modelEngine:"
    printf '      enabled: %s\n' "$(yaml_quote "$(env_or_default MODEL_ENGINE_ENABLED "false")")"
    echo "    voiceService:"
    printf '      appid: %s\n' "$(yaml_quote "$(env_or_default APPID "app_id")")"
    printf '      token: %s\n' "$(yaml_quote "$(env_or_default TOKEN "token")")"
    printf '      cluster: %s\n' "$(yaml_quote "$(env_or_default CLUSTER "volcano_tts")")"
    printf '      voiceType: %s\n' "$(yaml_quote "$(env_or_default VOICE_TYPE "zh_male_jieshuonansheng_mars_bigtts")")"
    printf '      speedRatio: %s\n' "$(yaml_quote "$(env_or_default SPEED_RATIO "1.3")")"
    echo "    modelPath:"
    printf '      clipModelPath: %s\n' "$(yaml_quote "$(env_or_default CLIP_MODEL_PATH "/opt/models/clip-vit-base-patch32")")"
    printf '      nltkData: %s\n' "$(yaml_quote "$(env_or_default NLTK_DATA "/opt/models/nltk_data")")"
    printf '      tableTransformerModelPath: %s\n' "$(yaml_quote "$(env_or_default TABLE_TRANSFORMER_MODEL_PATH "/opt/models/table-transformer-structure-recognition")")"
    printf '      unstructuredDefaultModelInitializeParamsJsonPath: %s\n' "$(yaml_quote "$(env_or_default UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH "/opt/models/yolox")")"
    echo "    terminal:"
    printf '      sshPrivateKeyPath: %s\n' "$(yaml_quote "$(env_or_default SSH_PRIVATE_KEY_PATH "/path/to/openssh-server/ssh-keys/openssh_server_key")")"
    echo "    supabase:"
    printf '      dashboardUsername: %s\n' "$(yaml_quote "$(env_or_default DASHBOARD_USERNAME "supabase")")"
    printf '      dashboardPassword: %s\n' "$(yaml_quote "$(env_or_default DASHBOARD_PASSWORD "Huawei123")")"
    printf '      siteUrl: %s\n' "$(yaml_quote "$(env_or_default SITE_URL "http://localhost:3011")")"
    printf '      supabaseUrl: %s\n' "$(yaml_quote "$(env_or_default SUPABASE_URL "http://nexent-supabase-kong:8000")")"
    printf '      apiExternalUrl: %s\n' "$(yaml_quote "$(env_or_default API_EXTERNAL_URL "http://nexent-supabase-kong:8000")")"
    printf '      disableSignup: %s\n' "$(yaml_quote "$(env_or_default DISABLE_SIGNUP "false")")"
    printf '      jwtExpiry: %s\n' "$(yaml_quote "$(env_or_default JWT_EXPIRY "3600")")"
    printf '      debugJwtExpireSeconds: %s\n' "$(yaml_quote "$(env_or_default DEBUG_JWT_EXPIRE_SECONDS "0")")"
    printf '      enableEmailSignup: %s\n' "$(yaml_quote "$(env_or_default ENABLE_EMAIL_SIGNUP "true")")"
    printf '      enableEmailAutoconfirm: %s\n' "$(yaml_quote "$(env_or_default ENABLE_EMAIL_AUTOCONFIRM "true")")"
    printf '      enableAnonymousUsers: %s\n' "$(yaml_quote "$(env_or_default ENABLE_ANONYMOUS_USERS "false")")"
    printf '      enablePhoneSignup: %s\n' "$(yaml_quote "$(env_or_default ENABLE_PHONE_SIGNUP "false")")"
    printf '      enablePhoneAutoconfirm: %s\n' "$(yaml_quote "$(env_or_default ENABLE_PHONE_AUTOCONFIRM "false")")"
    printf '      inviteCode: %s\n' "$(yaml_quote "$(env_or_default INVITE_CODE "nexent2025")")"
    printf '      mailerUrlpathsConfirmation: %s\n' "$(yaml_quote "$(env_or_default MAILER_URLPATHS_CONFIRMATION "/auth/v1/verify")")"
    printf '      mailerUrlpathsInvite: %s\n' "$(yaml_quote "$(env_or_default MAILER_URLPATHS_INVITE "/auth/v1/verify")")"
    printf '      mailerUrlpathsRecovery: %s\n' "$(yaml_quote "$(env_or_default MAILER_URLPATHS_RECOVERY "/auth/v1/verify")")"
    printf '      mailerUrlpathsEmailChange: %s\n' "$(yaml_quote "$(env_or_default MAILER_URLPATHS_EMAIL_CHANGE "/auth/v1/verify")")"
    printf '      postgresHost: %s\n' "$(yaml_quote "$(env_or_default SUPABASE_POSTGRES_HOST "nexent-supabase-db")")"
    printf '      postgresDb: %s\n' "$(yaml_quote "$(env_or_default SUPABASE_POSTGRES_DB "supabase")")"
    printf '      postgresPort: %s\n' "$(yaml_quote "$(env_or_default SUPABASE_POSTGRES_PORT "5436")")"
    printf '      additionalRedirectUrls: %s\n' "$(yaml_quote "$(env_or_default ADDITIONAL_REDIRECT_URLS "")")"
    echo "    dataProcess:"
    printf '      flowerPort: %s\n' "$(yaml_quote "$(env_or_default FLOWER_PORT "5555")")"
    printf '      rayDashboardPort: %s\n' "$(yaml_quote "$(env_or_default RAY_DASHBOARD_PORT "8265")")"
    printf '      rayDashboardHost: %s\n' "$(yaml_quote "$(env_or_default RAY_DASHBOARD_HOST "0.0.0.0")")"
    printf '      rayActorNumCpus: %s\n' "$(yaml_quote "$(env_or_default RAY_ACTOR_NUM_CPUS "2")")"
    printf '      rayObjectStoreMemoryGb: %s\n' "$(yaml_quote "$(env_or_default RAY_OBJECT_STORE_MEMORY_GB "0.25")")"
    printf '      rayTempDir: %s\n' "$(yaml_quote "$(env_or_default RAY_TEMP_DIR "/tmp/ray")")"
    printf '      rayLogLevel: %s\n' "$(yaml_quote "$(env_or_default RAY_LOG_LEVEL "INFO")")"
    printf '      disableRayDashboard: %s\n' "$(yaml_quote "$(env_or_default DISABLE_RAY_DASHBOARD "true")")"
    printf '      disableCeleryFlower: %s\n' "$(yaml_quote "$(env_or_default DISABLE_CELERY_FLOWER "true")")"
    printf '      dockerEnvironment: %s\n' "$(yaml_quote "$(env_or_default DOCKER_ENVIRONMENT "false")")"
    printf '      enableUploadImage: %s\n' "$(yaml_quote "$(env_or_default ENABLE_UPLOAD_IMAGE "false")")"
    printf '      celeryWorkerPrefetchMultiplier: %s\n' "$(yaml_quote "$(env_or_default CELERY_WORKER_PREFETCH_MULTIPLIER "1")")"
    printf '      celeryTaskTimeLimit: %s\n' "$(yaml_quote "$(env_or_default CELERY_TASK_TIME_LIMIT "3600")")"
    printf '      elasticsearchRequestTimeout: %s\n' "$(yaml_quote "$(env_or_default ELASTICSEARCH_REQUEST_TIMEOUT "30")")"
    printf '      queues: %s\n' "$(yaml_quote "$(env_or_default QUEUES "process_q,process_part_q,forward_q")")"
    printf '      partProcessorCount: %s\n' "$(yaml_quote "$(env_or_default DP_PART_PROCESSOR_COUNT "3")")"
    printf '      fileSplitSizeMb: %s\n' "$(yaml_quote "$(env_or_default DP_FILE_SPLIT_SIZE_MB "5")")"
    printf '      workerName: %s\n' "$(yaml_quote "$(env_or_default WORKER_NAME "")")"
    echo "    oauth:"
    printf '      githubClientId: %s\n' "$(yaml_quote "$(env_or_default GITHUB_OAUTH_CLIENT_ID "")")"
    printf '      githubClientSecret: %s\n' "$(yaml_quote "$(env_or_default GITHUB_OAUTH_CLIENT_SECRET "")")"
    printf '      enableWechat: %s\n' "$(yaml_quote "$(env_or_default ENABLE_WECHAT_OAUTH "false")")"
    printf '      wechatClientId: %s\n' "$(yaml_quote "$(env_or_default WECHAT_OAUTH_APP_ID "")")"
    printf '      wechatClientSecret: %s\n' "$(yaml_quote "$(env_or_default WECHAT_OAUTH_APP_SECRET "")")"
    printf '      gdeUrl: %s\n' "$(yaml_quote "$(env_or_default GDE_URL "")")"
    printf '      gdeClientId: %s\n' "$(yaml_quote "$(env_or_default GDE_OAUTH_CLIENT_ID "")")"
    printf '      gdeClientSecret: %s\n' "$(yaml_quote "$(env_or_default GDE_OAUTH_CLIENT_SECRET "")")"
    printf '      sslVerify: %s\n' "$(yaml_quote "$(env_or_default OAUTH_SSL_VERIFY "true")")"
    printf '      caBundle: %s\n' "$(yaml_quote "$(env_or_default OAUTH_CA_BUNDLE "")")"
    printf '      callbackBaseUrl: %s\n' "$(yaml_quote "$(env_or_default OAUTH_CALLBACK_BASE_URL "http://localhost:30000")")"
    printf '      loginMode: %s\n' "$(yaml_quote "$(env_or_default OAUTH_LOGIN_MODE "button")")"
    echo "    cas:"
    printf '      enabled: %s\n' "$(yaml_quote "$(env_or_default CAS_ENABLED "false")")"
    printf '      serverUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_SERVER_URL "")")"
    printf '      validatePath: %s\n' "$(yaml_quote "$(env_or_default CAS_VALIDATE_PATH "/p3/serviceValidate")")"
    printf '      callbackBaseUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_CALLBACK_BASE_URL "http://localhost:30000")")"
    printf '      loginMode: %s\n' "$(yaml_quote "$(env_or_default CAS_LOGIN_MODE "disabled")")"
    printf '      userAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_USER_ATTRIBUTE "")")"
    printf '      emailAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_EMAIL_ATTRIBUTE "email")")"
    printf '      roleAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_ROLE_ATTRIBUTE "role")")"
    printf '      defaultRole: %s\n' "$(yaml_quote "$(env_or_default CAS_DEFAULT_ROLE "USER")")"
    printf '      tenantAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_TENANT_ATTRIBUTE "tenant_id")")"
    printf '      defaultTenantId: %s\n' "$(yaml_quote "$(env_or_default CAS_DEFAULT_TENANT_ID "tenant_id")")"
    printf '      roleMapJson: %s\n' "$(yaml_quote "$(env_or_default CAS_ROLE_MAP_JSON "")")"
    printf '      sessionMaxAgeSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_SESSION_MAX_AGE_SECONDS "3600")")"
    printf '      localSessionMaxAgeSeconds: %s\n' "$(yaml_quote "$(env_or_default LOCAL_SESSION_MAX_AGE_SECONDS "3600")")"
    printf '      heartbeatUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_HEARTBEAT_URL "")")"
    printf '      heartbeatIntervalSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_HEARTBEAT_INTERVAL_SECONDS "300")")"
    printf '      heartbeatCookieName: %s\n' "$(yaml_quote "$(env_or_default CAS_HEARTBEAT_COOKIE_NAME "")")"
    printf '      renewBeforeSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_RENEW_BEFORE_SECONDS "300")")"
    printf '      renewTimeoutSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_RENEW_TIMEOUT_SECONDS "10")")"
    printf '      syntheticEmailDomain: %s\n' "$(yaml_quote "$(env_or_default CAS_SYNTHETIC_EMAIL_DOMAIN "cas.local")")"
    printf '      logoutUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_LOGOUT_URL "")")"
    printf '      sslVerify: %s\n' "$(yaml_quote "$(env_or_default CAS_SSL_VERIFY "true")")"
    printf '      caBundle: %s\n' "$(yaml_quote "$(env_or_default CAS_CA_BUNDLE "")")"

  } > "$output_file"
}

# Get APP_VERSION from backend/consts/const.py
get_app_version() {
  if declare -F deployment_read_version >/dev/null 2>&1; then
    deployment_read_version ""
    return 0
  fi

  if [ ! -f "$CONST_FILE" ]; then
    echo ""
    return
  fi
  local line
  line=$(grep -E 'APP_VERSION' "$CONST_FILE" | tail -n 1 || true)
  line="${line##*=}"
  line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  local value
  value="$(printf "%s" "$line" | tr -d '"' | tr -d "'")"
  echo "$value"
}

# Persist deployment options to file
persist_deploy_options() {
  deployment_persist_local_config "$DEPLOY_OPTIONS_FILE"
  {
    printf 'k8s:\n'
    printf '  appVersion: %s\n' "$(yaml_quote "$APP_VERSION")"
    printf '  isMainland: %s\n' "$(yaml_quote "$IS_MAINLAND_SAVED")"
    printf '  deploymentVersion: %s\n' "$(yaml_quote "$VERSION_CHOICE_SAVED")"
    printf '  persistenceMode: %s\n' "$(yaml_quote "$PERSISTENCE_MODE")"
    printf '  storageClassName: %s\n' "$(yaml_quote "$STORAGE_CLASS_NAME")"
    printf '  localPath: %s\n' "$(yaml_quote "$LOCAL_PATH")"
    printf '  existingClaimPrefix: %s\n' "$(yaml_quote "$EXISTING_CLAIM_PREFIX")"
  } >> "$DEPLOY_OPTIONS_FILE"
}

deploy_options_unquote() {
  local value
  value="$(deployment_trim "$1")"
  value="${value%$'\r'}"
  value="${value%%#*}"
  value="$(deployment_trim "$value")"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

apply_loaded_deploy_option() {
  local key="$1"
  local value="$2"
  case "$key" in
    APP_VERSION|appVersion)
      [ -n "${K8S_APP_VERSION_EXPLICIT:-}" ] || APP_VERSION="$value"
      ;;
    IS_MAINLAND|isMainland)
      [ -n "${K8S_IS_MAINLAND_EXPLICIT:-}" ] || IS_MAINLAND="$value"
      ;;
    DEPLOYMENT_VERSION|deploymentVersion)
      [ -n "${K8S_DEPLOYMENT_VERSION_EXPLICIT:-}" ] || DEPLOYMENT_VERSION="$value"
      ;;
    PERSISTENCE_MODE|persistenceMode)
      [ -n "${K8S_PERSISTENCE_MODE_EXPLICIT:-}" ] || PERSISTENCE_MODE="$value"
      ;;
    STORAGE_CLASS_NAME|storageClassName)
      [ -n "${K8S_STORAGE_CLASS_NAME_EXPLICIT:-}" ] || STORAGE_CLASS_NAME="$value"
      ;;
    LOCAL_PATH|localPath)
      [ -n "${K8S_LOCAL_PATH_EXPLICIT:-}" ] || LOCAL_PATH="$value"
      ;;
    EXISTING_CLAIM_PREFIX|existingClaimPrefix)
      [ -n "${K8S_EXISTING_CLAIM_PREFIX_EXPLICIT:-}" ] || EXISTING_CLAIM_PREFIX="$value"
      ;;
  esac
}

# Load deployment options from file if exists
load_deploy_options() {
  local line trimmed key value in_k8s_section
  if [ -f "$DEPLOY_OPTIONS_FILE" ]; then
    in_k8s_section="false"
    while IFS= read -r line || [ -n "$line" ]; do
      trimmed="$(deployment_trim "${line%%#*}")"
      [ -z "$trimmed" ] && continue

      if [[ "$trimmed" =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="$(deploy_options_unquote "${BASH_REMATCH[2]}")"
        apply_loaded_deploy_option "$key" "$value"
        continue
      fi

      if [[ "$trimmed" =~ ^k8s:[[:space:]]*$ ]]; then
        in_k8s_section="true"
        continue
      fi

      if [[ "$line" =~ ^[A-Za-z][A-Za-z0-9_]*:[[:space:]]* ]]; then
        in_k8s_section="false"
        continue
      fi

      if [ "$in_k8s_section" = "true" ] && [[ "$line" =~ ^[[:space:]]+([A-Za-z][A-Za-z0-9_]*):[[:space:]]*(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="$(deploy_options_unquote "${BASH_REMATCH[2]}")"
        apply_loaded_deploy_option "$key" "$value"
      fi
    done < "$DEPLOY_OPTIONS_FILE"
  fi
}

# Choose image environment (mainland China or general)
choose_image_env() {
  echo "=========================================="
  echo "  Image Source Selection"
  echo "=========================================="

  if [ -n "$IS_MAINLAND" ]; then
    is_mainland="$IS_MAINLAND"
    echo "Using is_mainland from argument: $is_mainland"
  else
    load_deploy_options
    if [ -n "$IS_MAINLAND" ]; then
      is_mainland="$IS_MAINLAND"
      echo "Using saved is_mainland: $is_mainland"
    else
      read -p "Is your server network located in mainland China? [Y/N] (default N): " is_mainland
    fi
  fi

  is_mainland=$(sanitize_input "$is_mainland")
  if [[ "$is_mainland" =~ ^[Yy]$ ]]; then
    IS_MAINLAND_SAVED="Y"
    echo "Detected mainland China network, using image-source.mainland.env for image sources."
    source "$DEPLOY_ROOT/env/image-source.mainland.env"
  else
    IS_MAINLAND_SAVED="N"
    echo "Using general image sources from image-source.general.env."
    source "$DEPLOY_ROOT/env/image-source.general.env"
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

# Render image tags into generated Helm values based on loaded environment variables
update_values_yaml() {
  echo "=========================================="
  echo "  Rendering generated image values"
  echo "=========================================="

  # Get APP_VERSION if not already set
  if [ -z "$APP_VERSION" ]; then
    APP_VERSION=$(get_app_version)
  fi

  if [ -z "$APP_VERSION" ]; then
    echo "Failed to determine APP_VERSION from const.py, using 'latest'"
    APP_VERSION="latest"
  fi
  echo "Using APP_VERSION: $APP_VERSION"
  echo ""

  deployment_apply_image_source
  deployment_prepare_monitoring_env k8s || exit 1
  deployment_render_helm_values "$GENERATED_VALUES"
  deployment_render_helm_values "$INFRASTRUCTURE_GENERATED_VALUES"
  render_k8s_runtime_config_values "$GENERATED_RUNTIME_VALUES"
  render_infrastructure_runtime_values "$INFRASTRUCTURE_GENERATED_RUNTIME_VALUES"
  render_persistence_values
  echo "Generated application Helm values: $GENERATED_VALUES"
  echo "Generated infrastructure Helm values: $INFRASTRUCTURE_GENERATED_VALUES"
  echo "Generated application runtime values: $GENERATED_RUNTIME_VALUES"
  echo "Generated infrastructure runtime values: $INFRASTRUCTURE_GENERATED_RUNTIME_VALUES"
  echo "Generated application persistence values: $GENERATED_PERSISTENCE_VALUES"
  echo "Generated infrastructure persistence values: $INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES"
  echo ""
  echo "--------------------------------"
  echo ""
}

ensure_namespace() {
    if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        echo "Namespace '$NAMESPACE' already exists."
    else
        echo "Creating namespace '$NAMESPACE'..."
        kubectl create namespace "$NAMESPACE"
    fi
}

helm_upgrade_application_release() {
    helm upgrade --install "$APPLICATION_RELEASE_NAME" "$APPLICATION_CHART_DIR" \
        --namespace "$NAMESPACE" \
        -f "$GENERATED_VALUES" \
        -f "$GENERATED_RUNTIME_VALUES" \
        -f "$GENERATED_PERSISTENCE_VALUES" \
        -f "$GENERATED_SECRETS_VALUES" \
        --set nexent-openssh.enabled="$ENABLE_OPENSSH" \
        --set nexent-common.secrets.ssh.username="$SSH_USERNAME" \
        --set nexent-common.secrets.ssh.password="$SSH_PASSWORD"
}

helm_upgrade_infrastructure_release() {
    helm upgrade --install "$INFRASTRUCTURE_RELEASE_NAME" "$INFRASTRUCTURE_CHART_DIR" \
        --namespace "$NAMESPACE" \
        -f "$INFRASTRUCTURE_GENERATED_VALUES" \
        -f "$INFRASTRUCTURE_GENERATED_RUNTIME_VALUES" \
        -f "$INFRASTRUCTURE_GENERATED_PERSISTENCE_VALUES" \
        -f "$INFRASTRUCTURE_GENERATED_SECRETS_VALUES"
}

wait_for_deployment_ready() {
    local deployment="$1"
    kubectl rollout status "deployment/${deployment}" -n "$NAMESPACE" --timeout="${K8S_WAIT_TIMEOUT_SECONDS}s"
}

release_scope_includes_infrastructure() {
    [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "infrastructure" ]
}

release_scope_includes_nexent() {
    [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "nexent" ]
}

validate_official_skills_source() {
    local archive
    local archive_count=0

    if [ ! -d "$OFFICIAL_SKILLS_SOURCE_DIR" ]; then
        echo "Error: official skills directory not found: $OFFICIAL_SKILLS_SOURCE_DIR"
        return 1
    fi

    for archive in "$OFFICIAL_SKILLS_SOURCE_DIR"/*.zip; do
        [ -f "$archive" ] || continue
        if [ ! -r "$archive" ]; then
            echo "Error: official skill archive is not readable: $archive"
            return 1
        fi
        archive_count=$((archive_count + 1))
    done

    if [ "$archive_count" -eq 0 ]; then
        echo "Error: no official skill archives found in $OFFICIAL_SKILLS_SOURCE_DIR"
        return 1
    fi
}

official_skills_source_manifest() {
    (
        cd "$OFFICIAL_SKILLS_SOURCE_DIR" || exit 1
        sha256sum ./*.zip | LC_ALL=C sort
    )
}

find_ready_config_pod() {
    local ready_pods

    ready_pods=$(kubectl get pods -n "$NAMESPACE" \
        -l app=nexent-config \
        --field-selector=status.phase=Running \
        --sort-by=.metadata.creationTimestamp \
        -o 'jsonpath={range .items[?(@.status.containerStatuses[0].ready==true)]}{.metadata.name}{"\n"}{end}' \
        2>/dev/null) || return 1
    printf '%s\n' "$ready_pods" | sed -n '$p'
}

sync_official_skills_to_workspace() {
    local config_pod
    local expected_manifest
    local actual_manifest
    local staging_dir="/mnt/nexent/.official-skills-zip.staging"
    local backup_dir="/mnt/nexent/.official-skills-zip.backup"

    config_pod=$(find_ready_config_pod)
    if [ -z "$config_pod" ]; then
        echo "Error: no Ready nexent-config pod is available for official skills synchronization."
        return 1
    fi

    expected_manifest=$(official_skills_source_manifest) || {
        echo "Error: failed to calculate the official skills source manifest."
        return 1
    }

    if ! kubectl exec -n "$NAMESPACE" "$config_pod" -- sh -c '
        set -e
        staging_dir="$1"
        target_dir="$2"
        backup_dir="$3"
        rm -rf "$staging_dir"
        if [ -e "$backup_dir" ] || [ -L "$backup_dir" ]; then
            if [ -e "$target_dir" ] || [ -L "$target_dir" ]; then
                rm -rf "$backup_dir"
            else
                mv "$backup_dir" "$target_dir"
            fi
        fi
        mkdir -p "$staging_dir"
    ' _ "$staging_dir" "$OFFICIAL_SKILLS_TARGET_DIR" "$backup_dir"; then
        echo "Error: failed to prepare the official skills staging directory."
        return 1
    fi

    if ! kubectl cp "$OFFICIAL_SKILLS_SOURCE_DIR/." \
        "$NAMESPACE/$config_pod:$staging_dir"; then
        kubectl exec -n "$NAMESPACE" "$config_pod" -- rm -rf "$staging_dir" "$backup_dir" >/dev/null 2>&1 || true
        echo "Error: failed to copy official skills to the workspace PVC."
        return 1
    fi

    if ! kubectl exec -n "$NAMESPACE" "$config_pod" -- sh -c '
        find "$1" -mindepth 1 -maxdepth 1 \( ! -type f -o ! -name "*.zip" \) -exec rm -rf {} +
        chmod 0755 "$1"
        chmod 0644 "$1"/*.zip
    ' _ "$staging_dir"; then
        kubectl exec -n "$NAMESPACE" "$config_pod" -- rm -rf "$staging_dir" "$backup_dir" >/dev/null 2>&1 || true
        echo "Error: failed to set permissions on the copied official skills."
        return 1
    fi

    actual_manifest=$(kubectl exec -n "$NAMESPACE" "$config_pod" -- sh -c \
        'cd "$1" && sha256sum ./*.zip | LC_ALL=C sort' \
        _ "$staging_dir") || {
        kubectl exec -n "$NAMESPACE" "$config_pod" -- rm -rf "$staging_dir" "$backup_dir" >/dev/null 2>&1 || true
        echo "Error: failed to calculate the copied official skills manifest."
        return 1
    }

    if [ "$actual_manifest" != "$expected_manifest" ]; then
        kubectl exec -n "$NAMESPACE" "$config_pod" -- rm -rf "$staging_dir" "$backup_dir" >/dev/null 2>&1 || true
        echo "Error: copied official skills failed SHA-256 verification."
        return 1
    fi

    if ! kubectl exec -n "$NAMESPACE" "$config_pod" -- sh -c '
        set -e
        staging_dir="$1"
        target_dir="$2"
        backup_dir="$3"
        rm -rf "$backup_dir"
        if [ -e "$target_dir" ] || [ -L "$target_dir" ]; then
            mv "$target_dir" "$backup_dir"
        fi
        if mv "$staging_dir" "$target_dir"; then
            rm -rf "$backup_dir" || true
        else
            if [ -e "$backup_dir" ] || [ -L "$backup_dir" ]; then
                mv "$backup_dir" "$target_dir"
            fi
            exit 1
        fi
    ' _ "$staging_dir" "$OFFICIAL_SKILLS_TARGET_DIR" "$backup_dir"; then
        kubectl exec -n "$NAMESPACE" "$config_pod" -- rm -rf "$staging_dir" >/dev/null 2>&1 || true
        echo "Error: failed to activate the copied official skills; the previous version was preserved."
        return 1
    fi

    echo "Official skills synchronized to $OFFICIAL_SKILLS_TARGET_DIR ($config_pod)."
}

helm_release_exists() {
    local release_name="$1"
    helm status "$release_name" --namespace "$NAMESPACE" >/dev/null 2>&1
}

reject_legacy_single_release() {
    local manifest
    if ! helm_release_exists "$APPLICATION_RELEASE_NAME"; then
        return 0
    fi

    if ! manifest="$(helm get manifest "$APPLICATION_RELEASE_NAME" --namespace "$NAMESPACE" 2>/dev/null)"; then
        echo "Error: unable to inspect the existing '$APPLICATION_RELEASE_NAME' release for legacy infrastructure ownership."
        return 1
    fi
    if printf '%s\n' "$manifest" | grep -Eq '^[[:space:]]*name:[[:space:]]+nexent-elasticsearch[[:space:]]*$'; then
        echo "Error: the existing '$APPLICATION_RELEASE_NAME' release still manages infrastructure resources."
        echo "Automatic migration from the legacy single release is not supported; use a fresh deployment."
        return 1
    fi
}

require_infrastructure_release() {
    if helm_release_exists "$INFRASTRUCTURE_RELEASE_NAME"; then
        return 0
    fi
    echo "Error: infrastructure release '$INFRASTRUCTURE_RELEASE_NAME' does not exist in namespace '$NAMESPACE'."
    echo "Deploy it first with --release-scope infrastructure or --release-scope all."
    return 1
}

wait_for_infrastructure_ready() {
    local deployment
    for deployment in nexent-elasticsearch nexent-postgresql nexent-redis nexent-minio; do
        echo "  Waiting for $deployment..."
        if ! wait_for_deployment_ready "$deployment"; then
            echo "Error: $deployment did not become ready within ${K8S_WAIT_TIMEOUT_SECONDS}s."
            return 1
        fi
        echo "  $deployment is ready."
    done
}

wait_for_nexent_ready() {
    local deployments=""
    local deployment

    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"; then
        deployments="nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-web"
    fi
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process"; then
        deployments="$deployments nexent-data-process"
    fi
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        deployments="$deployments nexent-supabase-kong nexent-supabase-auth nexent-supabase-db"
    fi
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
        deployments="$deployments nexent-openssh"
    fi
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
        deployments="$deployments nexent-otel-collector"
        case "$DEPLOYMENT_MONITORING_PROVIDER" in
            phoenix) deployments="$deployments nexent-phoenix" ;;
            grafana) deployments="$deployments nexent-tempo nexent-grafana" ;;
            zipkin) deployments="$deployments nexent-zipkin" ;;
            langfuse) deployments="$deployments nexent-langfuse-postgres nexent-langfuse-clickhouse nexent-langfuse-minio nexent-langfuse-redis nexent-langfuse-web nexent-langfuse-worker" ;;
        esac
    fi

    for deployment in $deployments; do
        echo "  Waiting for $deployment..."
        if ! wait_for_deployment_ready "$deployment"; then
            echo "Error: $deployment did not become ready within ${K8S_WAIT_TIMEOUT_SECONDS}s."
            return 1
        fi
        echo "  $deployment is ready."
    done
}

recreate_legacy_nexent_secret_for_helm_management() {
    local managers
    if ! kubectl get secret nexent-secrets -n "$NAMESPACE" >/dev/null 2>&1; then
        return 0
    fi

    managers=$(kubectl get secret nexent-secrets -n "$NAMESPACE" -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\n"}{end}' 2>/dev/null || true)
    if printf '%s\n' "$managers" | grep -qx 'kubectl-patch'; then
        echo "Recreating legacy nexent-secrets so Helm owns all Secret fields..."
        kubectl delete secret nexent-secrets -n "$NAMESPACE"
    fi
}

# Select deployment version (speed or full)
select_deployment_version() {
    echo "=========================================="
    echo "  Deployment Version Selection"
    echo "=========================================="
    echo "Please select deployment version:"
    echo "   1) Speed version - Lightweight deployment with essential features (no Supabase)"
    echo "   2) Full version - Full-featured deployment with all capabilities (includes Supabase)"

    if [ -n "$DEPLOYMENT_VERSION" ]; then
        version_choice="$DEPLOYMENT_VERSION"
        echo "Using deployment-version from argument: $version_choice"
    else
        load_deploy_options
        if [ -n "$DEPLOYMENT_VERSION" ]; then
            version_choice="$DEPLOYMENT_VERSION"
            echo "Using saved deployment-version: $version_choice"
        else
            read -p "Enter your choice [1/2] (default: 1): " version_choice
        fi
    fi

    version_choice=$(sanitize_input "$version_choice")
    VERSION_CHOICE_SAVED="${version_choice}"

    case $version_choice in
        2|"full")
            export DEPLOYMENT_VERSION="full"
            echo "Selected complete version"
            ;;
        1|"speed"|*)
            export DEPLOYMENT_VERSION="speed"
            echo "Selected speed version"
            ;;
    esac

    # Legacy helper retained for compatibility; generated values carry the effective version.

    echo ""
    echo "--------------------------------"
    echo ""
}

# Generate JWT token for Supabase
generate_jwt() {
    local role=$1
    local secret=$JWT_SECRET
    local now=$(date +%s)
    local exp=$((now + 157680000))

    local header='{"alg":"HS256","typ":"JWT"}'
    local header_base64=$(echo -n "$header" | base64 | tr -d '\n=' | tr '/+' '_-')

    local payload="{\"role\":\"$role\",\"iss\":\"supabase\",\"iat\":$now,\"exp\":$exp}"
    local payload_base64=$(echo -n "$payload" | base64 | tr -d '\n=' | tr '/+' '_-')

    local signature=$(echo -n "$header_base64.$payload_base64" | openssl dgst -sha256 -hmac "$secret" -binary | base64 | tr -d '\n=' | tr '/+' '_-')

    echo "$header_base64.$payload_base64.$signature"
}

decode_base64() {
    if base64 --help 2>&1 | grep -q -- '--decode'; then
        base64 --decode
    else
        base64 -D
    fi
}

get_existing_secret_value() {
    local key="$1"
    local secret_name="${2:-nexent-secrets}"
    local encoded_value
    encoded_value=$(kubectl get secret "$secret_name" -n "$NAMESPACE" -o jsonpath="{.data.${key}}" 2>/dev/null || true)
    if [ -z "$encoded_value" ]; then
        return 1
    fi

    printf '%s' "$encoded_value" | decode_base64
}

load_existing_supabase_secrets() {
    local existing_jwt_secret
    local existing_secret_key_base
    local existing_vault_enc_key
    local existing_anon_key
    local existing_service_role_key

    existing_jwt_secret="$(get_existing_secret_value "JWT_SECRET")" || return 1
    existing_secret_key_base="$(get_existing_secret_value "SECRET_KEY_BASE")" || return 1
    existing_vault_enc_key="$(get_existing_secret_value "VAULT_ENC_KEY")" || return 1
    existing_anon_key="$(get_existing_secret_value "SUPABASE_KEY")" || return 1
    existing_service_role_key="$(get_existing_secret_value "SERVICE_ROLE_KEY")" || return 1

    JWT_SECRET="$existing_jwt_secret"
    SECRET_KEY_BASE="$existing_secret_key_base"
    VAULT_ENC_KEY="$existing_vault_enc_key"
    SUPABASE_ANON_KEY="$existing_anon_key"
    SUPABASE_SERVICE_ROLE_KEY="$existing_service_role_key"
    return 0
}

load_existing_minio_secrets() {
    local existing_access_key
    local existing_secret_key

    existing_access_key="$(get_existing_secret_value "MINIO_ACCESS_KEY" "nexent-infrastructure-secrets")" || return 1
    existing_secret_key="$(get_existing_secret_value "MINIO_SECRET_KEY" "nexent-infrastructure-secrets")" || return 1

    if [ -z "$existing_access_key" ] || [ -z "$existing_secret_key" ]; then
        return 1
    fi

    MINIO_ACCESS_KEY="$existing_access_key"
    MINIO_SECRET_KEY="$existing_secret_key"
    return 0
}

load_existing_elasticsearch_api_key() {
    local existing_api_key
    existing_api_key="$(get_existing_secret_value "ELASTICSEARCH_API_KEY")" || return 1
    [ -n "$existing_api_key" ] || return 1
    ELASTICSEARCH_API_KEY="$existing_api_key"
    return 0
}

# Generate Supabase secrets (only for full version)
generate_supabase_secrets() {
    if [ "$DEPLOYMENT_VERSION" != "full" ]; then
        echo "Skipping Supabase secrets generation (deployment version is speed)"
        return 0
    fi

    echo "=========================================="
    echo "  Supabase Secrets Generation"
    echo "=========================================="

    if [ -n "${JWT_SECRET:-}" ] && [ -n "${SECRET_KEY_BASE:-}" ] && [ -n "${VAULT_ENC_KEY:-}" ] && [ -n "${SUPABASE_KEY:-}" ] && [ -n "${SERVICE_ROLE_KEY:-}" ]; then
        SUPABASE_ANON_KEY="$SUPABASE_KEY"
        SUPABASE_SERVICE_ROLE_KEY="$SERVICE_ROLE_KEY"
        echo "Using Supabase secrets from deploy/env/.env."
        echo ""
        echo "--------------------------------"
        echo ""
        return 0
    fi

    if load_existing_supabase_secrets; then
        echo "Reusing existing Supabase secrets from Kubernetes secret."
        echo ""
        echo "--------------------------------"
        echo ""
        return 0
    fi

    # Generate fresh keys for security
    JWT_SECRET=$(openssl rand -base64 32 | tr -d '[:space:]')
    SECRET_KEY_BASE=$(openssl rand -base64 64 | tr -d '[:space:]')
    VAULT_ENC_KEY=$(openssl rand -base64 32 | tr -d '[:space:]')

    # Generate JWT-dependent keys
    local anon_key=$(generate_jwt "anon")
    local service_role_key=$(generate_jwt "service_role")

    SUPABASE_ANON_KEY="$anon_key"
    SUPABASE_SERVICE_ROLE_KEY="$service_role_key"
    echo "Supabase secrets generated for generated Helm values"
    echo ""
    echo "--------------------------------"
    echo ""
}

# Pull MCP Docker image to local host (best-effort)
pull_mcp_image() {
    echo "=========================================="
    echo "  MCP Image Pull"
    echo "=========================================="

    # Use image from environment, fallback to default image
    local image="${NEXENT_MCP_DOCKER_IMAGE:-nexent/nexent-mcp}"
    local image_tail="${image##*/}"
    local mcp_image_name="$image"
    if [[ "$image_tail" != *:* ]]; then
        mcp_image_name="${image}:${APP_VERSION:-latest}"
    fi
    echo "Checking MCP image: ${mcp_image_name}"

    if ! command -v docker >/dev/null 2>&1; then
        echo "Warning: Docker is not installed or not in PATH, skipping MCP image pull."
        echo ""
        echo "--------------------------------"
        echo ""
        return 0
    fi

    # Pull image only when not present locally
    if docker image inspect "${mcp_image_name}" >/dev/null 2>&1; then
        echo "MCP image already exists locally, skipping pull."
    elif [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ]; then
        echo "Warning: MCP local image not found: ${mcp_image_name}"
        echo "Build or load it locally before using --image-source local-latest."
    else
        echo "MCP image not found locally, pulling..."
        if docker pull "${mcp_image_name}"; then
            echo "MCP image pulled successfully."
        else
            echo "Warning: Failed to pull MCP image, but deployment will continue."
            echo "You can pull it manually later: docker pull ${mcp_image_name}"
        fi
    fi

    echo ""
    echo "--------------------------------"
    echo ""
}

# Pull sandbox Docker image to local host (best-effort)
pull_sandbox_image() {
    echo "=========================================="
    echo "  Sandbox Image Pull"
    echo "=========================================="

    local image="${NEXENT_SANDBOX_IMAGE:-nexent/nexent-sandbox}"
    local image_tail="${image##*/}"
    local sandbox_image_name="$image"
    if [[ "$image_tail" != *:* ]]; then
        sandbox_image_name="${image}:${APP_VERSION:-latest}"
    fi
    echo "Checking sandbox image: ${sandbox_image_name}"

    if ! command -v docker >/dev/null 2>&1; then
        echo "Warning: Docker is not installed or not in PATH, skipping sandbox image pull."
        echo ""
        echo "--------------------------------"
        echo ""
        return 0
    fi

    if docker image inspect "${sandbox_image_name}" >/dev/null 2>&1; then
        echo "Sandbox image already exists locally, skipping pull."
    elif [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ]; then
        echo "Warning: Sandbox local image not found: ${sandbox_image_name}"
        echo "Build or load it locally before using --image-source local-latest."
    else
        echo "Sandbox image not found locally, pulling..."
        if docker pull "${sandbox_image_name}"; then
            echo "Sandbox image pulled successfully."
        else
            echo "Warning: Failed to pull sandbox image, but deployment will continue."
            echo "You can pull it manually later: docker pull ${sandbox_image_name}"
        fi
    fi

    echo ""
    echo "--------------------------------"
    echo ""
}

render_runtime_secret_values() {
    local gotrue_db_url
    local env_checksum
    local sql_checksum
    local supabase_postgres_password
    local supabase_secret_checksum

    supabase_postgres_password="$(env_or_default SUPABASE_POSTGRES_PASSWORD "Huawei123")"
    gotrue_db_url="$(env_or_default GOTRUE_DB_DATABASE_URL "postgres://supabase_auth_admin:${supabase_postgres_password}@$(env_or_default SUPABASE_POSTGRES_HOST "nexent-supabase-db"):$(env_or_default SUPABASE_POSTGRES_PORT "5436")/$(env_or_default SUPABASE_POSTGRES_DB "supabase")?search_path=auth&sslmode=disable")"
    env_checksum="$(deployment_env_values_checksum)"
    sql_checksum="$(sql_files_checksum)"
    supabase_secret_checksum="$(deployment_sha256_string "jwt=${JWT_SECRET:-}|secretKeyBase=${SECRET_KEY_BASE:-}|vault=${VAULT_ENC_KEY:-}|anon=${SUPABASE_ANON_KEY:-}|service=${SUPABASE_SERVICE_ROLE_KEY:-}|postgres=${supabase_postgres_password}|gotrue=${gotrue_db_url}")"

    {
        echo "global:"
        echo "  rolloutChecksums:"
        printf '    env: %s\n' "$(yaml_quote "$env_checksum")"
        printf '    sql: %s\n' "$(yaml_quote "$sql_checksum")"
        printf '    supabaseSecret: %s\n' "$(yaml_quote "$supabase_secret_checksum")"
        deployment_render_image_rollout_checksums
        echo "nexent-common:"
        echo "  secrets:"
        printf '    elasticsearchApiKey: %s\n' "$(yaml_quote "$(env_or_default ELASTICSEARCH_API_KEY "")")"
        printf '    postgresPassword: %s\n' "$(yaml_quote "$(env_or_default NEXENT_POSTGRES_PASSWORD "nexent@4321")")"
        echo "    minio:"
        printf '      rootUser: %s\n' "$(yaml_quote "$(env_or_default MINIO_ROOT_USER "nexent")")"
        printf '      rootPassword: %s\n' "$(yaml_quote "$(env_or_default MINIO_ROOT_PASSWORD "nexent@4321")")"
        printf '      accessKey: %s\n' "$(yaml_quote "$MINIO_ACCESS_KEY")"
        printf '      secretKey: %s\n' "$(yaml_quote "$MINIO_SECRET_KEY")"
        echo "    ssh:"
        printf '      username: %s\n' "$(yaml_quote "$(env_or_default SSH_USERNAME "nexent")")"
        printf '      password: %s\n' "$(yaml_quote "$(env_or_default SSH_PASSWORD "nexent@2025")")"
        if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
            echo "    supabase:"
            printf '      jwtSecret: %s\n' "$(yaml_quote "$JWT_SECRET")"
            printf '      secretKeyBase: %s\n' "$(yaml_quote "$SECRET_KEY_BASE")"
            printf '      vaultEncKey: %s\n' "$(yaml_quote "$VAULT_ENC_KEY")"
            printf '      anonKey: %s\n' "$(yaml_quote "$SUPABASE_ANON_KEY")"
            printf '      serviceRoleKey: %s\n' "$(yaml_quote "$SUPABASE_SERVICE_ROLE_KEY")"
            printf '      postgresPassword: %s\n' "$(yaml_quote "$supabase_postgres_password")"
            printf '      gotrueDbUrl: %s\n' "$(yaml_quote "$gotrue_db_url")"
        fi
    } > "$GENERATED_SECRETS_VALUES"
}

render_infrastructure_secret_values() {
    local infrastructure_secret_checksum
    infrastructure_secret_checksum="$(deployment_sha256_string "elastic=$(env_or_default ELASTIC_PASSWORD "nexent@2025")|postgres=$(env_or_default NEXENT_POSTGRES_PASSWORD "nexent@4321")|minioRoot=$(env_or_default MINIO_ROOT_PASSWORD "nexent@4321")|minioAccess=${MINIO_ACCESS_KEY}|minioSecret=${MINIO_SECRET_KEY}")"

    {
        echo "global:"
        echo "  rolloutChecksums:"
        printf '    env: %s\n' "$(yaml_quote "$infrastructure_secret_checksum")"
        echo "nexent-infrastructure-common:"
        echo "  secrets:"
        printf '    elasticPassword: %s\n' "$(yaml_quote "$(env_or_default ELASTIC_PASSWORD "nexent@2025")")"
        printf '    postgresPassword: %s\n' "$(yaml_quote "$(env_or_default NEXENT_POSTGRES_PASSWORD "nexent@4321")")"
        echo "    minio:"
        printf '      rootUser: %s\n' "$(yaml_quote "$(env_or_default MINIO_ROOT_USER "nexent")")"
        printf '      rootPassword: %s\n' "$(yaml_quote "$(env_or_default MINIO_ROOT_PASSWORD "nexent@4321")")"
        printf '      accessKey: %s\n' "$(yaml_quote "$MINIO_ACCESS_KEY")"
        printf '      secretKey: %s\n' "$(yaml_quote "$MINIO_SECRET_KEY")"
    } > "$INFRASTRUCTURE_GENERATED_SECRETS_VALUES"
}

apply() {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "正在使用 Helm 部署 Nexent..."
    else
        echo "Deploying Nexent using Helm..."
    fi

    # Step 1: Select deployment components, port policy and image source.
    apply_deployment_common_config

    # Step 2: Render release-specific values with image tags and persistence settings.
    update_values_yaml
    if release_scope_includes_nexent && deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"; then
        validate_official_skills_source || exit 1
    fi
    persist_deploy_options

    reject_legacy_single_release || exit 1

    if [ "$RELEASE_SCOPE" = "infrastructure" ] && [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" = "true" ]; then
        echo "Error: --refresh-es-key requires --release-scope all or --release-scope nexent."
        exit 1
    fi
    if [ "$RELEASE_SCOPE" = "infrastructure" ] && [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] && helm_release_exists "$APPLICATION_RELEASE_NAME"; then
        echo "Error: rotating infrastructure credentials while the Nexent release exists is unsafe."
        echo "Use --release-scope all so application credentials are updated in the same deployment."
        exit 1
    fi

    # Step 3: Generate or reuse stable MinIO credentials for both releases.
    echo "=========================================="
    echo "  MinIO Access Key/Secret Key Setup"
    echo "=========================================="
    if [ -n "${MINIO_ACCESS_KEY:-}" ] && [ -n "${MINIO_SECRET_KEY:-}" ]; then
        echo "Using MinIO credentials from deploy/env/.env."
        echo "Access Key: $MINIO_ACCESS_KEY"
    elif load_existing_minio_secrets; then
        echo "Reusing existing MinIO credentials from Kubernetes secret."
        echo "Access Key: $MINIO_ACCESS_KEY"
    elif grep -q "minio:" "$COMMON_VALUES" && grep -q "accessKey:" "$COMMON_VALUES"; then
        MINIO_ACCESS_KEY=$(grep "accessKey:" "$COMMON_VALUES" | head -1 | sed 's/.*accessKey: *//' | tr -d '"' | tr -d "'" | xargs)
        MINIO_SECRET_KEY=$(grep "secretKey:" "$COMMON_VALUES" | head -1 | sed 's/.*secretKey: *//' | tr -d '"' | tr -d "'" | xargs)
    fi

    if [ -z "$MINIO_ACCESS_KEY" ] || [ "$MINIO_ACCESS_KEY" = "" ]; then
        echo "Generating new MinIO Access Key and Secret Key..."
        MINIO_ACCESS_KEY="nexent-$(head -c 8 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 12)"
        MINIO_SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)

        echo "MinIO credentials generated for generated Helm values"
        echo "Access Key: $MINIO_ACCESS_KEY"
        echo "Secret Key: $MINIO_SECRET_KEY (saved in generated Helm values)"
    else
        echo "MinIO credentials already exist"
        echo "Access Key: $MINIO_ACCESS_KEY"
    fi
    echo ""

    # Step 4: Clean up stale PVs owned by the selected release scope.
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "正在检查残留 PersistentVolumes..."
    else
        echo "Checking for stale PersistentVolumes..."
    fi
    local stale_pvs=""
    if release_scope_includes_infrastructure; then
        stale_pvs="nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv"
    fi
    if release_scope_includes_nexent; then
        stale_pvs="$stale_pvs nexent-workspace-pv nexent-skills-pv"
        if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
            stale_pvs="$stale_pvs nexent-supabase-db-pv"
        fi
    fi
    for pv in $stale_pvs; do
        pv_status=$(kubectl get pv "$pv" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        if [ "$pv_status" = "Released" ]; then
            echo "  Cleaning up stale PV: $pv"
            kubectl delete pv "$pv" --ignore-not-found=true || true
        fi
    done

    ensure_namespace

    # Step 5: Install or upgrade infrastructure and wait for all four dependencies.
    if release_scope_includes_infrastructure; then
        render_infrastructure_secret_values
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "正在部署基础设施 Helm release '$INFRASTRUCTURE_RELEASE_NAME'..."
        else
            echo "Deploying infrastructure Helm release '$INFRASTRUCTURE_RELEASE_NAME'..."
        fi
        helm_upgrade_infrastructure_release
    else
        require_infrastructure_release || exit 1
    fi

    if release_scope_includes_infrastructure || [ "$RELEASE_SCOPE" = "nexent" ]; then
        echo "Waiting for Elasticsearch, PostgreSQL, Redis, and MinIO..."
        if ! wait_for_infrastructure_ready; then
            echo "Infrastructure is not ready; the Nexent release was not installed or upgraded."
            exit 1
        fi
    fi

    if [ "$RELEASE_SCOPE" = "infrastructure" ]; then
        persist_deploy_options
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "基础设施 release 部署完成。"
        else
            echo "Infrastructure release deployed successfully."
        fi
        return 0
    fi

    # Step 6: Prepare application-only secrets after infrastructure is healthy.
    generate_supabase_secrets
    if [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" != "true" ] && [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ]; then
        if [ -n "${ELASTICSEARCH_API_KEY:-}" ]; then
            echo "Using ELASTICSEARCH_API_KEY from deploy/env/.env."
        elif load_existing_elasticsearch_api_key; then
            echo "Reusing existing ELASTICSEARCH_API_KEY from Kubernetes secret."
        fi
    fi

    echo ""
    echo "=========================================="
    echo "  Elasticsearch Initialization"
    echo "=========================================="
    local es_key_output_file
    es_key_output_file="$(mktemp "${TMPDIR:-/tmp}/nexent-es-key.XXXXXX")"
    if ! ROOT_ENV_FILE="$ROOT_ENV_FILE" \
        ELASTICSEARCH_API_KEY_OUTPUT_FILE="$es_key_output_file" \
        ELASTICSEARCH_API_KEY="${ELASTICSEARCH_API_KEY:-}" \
        NEXENT_ES_INIT_TIMEOUT_SECONDS="$K8S_WAIT_TIMEOUT_SECONDS" \
        DEPLOYMENT_REFRESH_ES_KEY="${DEPLOYMENT_REFRESH_ES_KEY:-false}" \
        DEPLOYMENT_ROTATE_SECRETS="${DEPLOYMENT_ROTATE_SECRETS:-false}" \
        bash "$SCRIPT_DIR/init-elasticsearch.sh"; then
        rm -f "$es_key_output_file"
        echo "Error: Elasticsearch API key initialization failed; the Nexent release was not installed or upgraded."
        exit 1
    fi
    if [ ! -s "$es_key_output_file" ]; then
        rm -f "$es_key_output_file"
        echo "Error: Elasticsearch API key initialization returned an empty key."
        exit 1
    fi
    ELASTICSEARCH_API_KEY="$(cat "$es_key_output_file")"
    rm -f "$es_key_output_file"

    # Step 7: Configure the optional terminal before rendering the application Secret.
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
        ENABLE_OPENSSH="true"
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "将启用终端工具。"
            read -p "SSH 用户名（默认：nexent）：" ssh_username
        else
            echo "Terminal tool will be enabled."
            read -p "SSH Username (default: nexent): " ssh_username
        fi
        SSH_USERNAME="${ssh_username:-nexent}"
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            read -s -p "SSH 密码（默认：nexent@2025）：" ssh_password
        else
            read -s -p "SSH Password (default: nexent@2025): " ssh_password
        fi
        echo ""
        SSH_PASSWORD="${ssh_password:-nexent@2025}"
    else
        ENABLE_OPENSSH="false"
        SSH_USERNAME="${SSH_USERNAME:-nexent}"
        SSH_PASSWORD="${SSH_PASSWORD:-nexent@2025}"
    fi

    render_runtime_secret_values
    recreate_legacy_nexent_secret_for_helm_management

    # Step 8: Install or upgrade the application release exactly once.
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "正在部署应用 Helm release '$APPLICATION_RELEASE_NAME'..."
    else
        echo "Deploying application Helm release '$APPLICATION_RELEASE_NAME'..."
    fi
    helm_upgrade_application_release

    echo "Waiting for selected Nexent workloads..."
    if ! wait_for_nexent_ready; then
        echo "Error: one or more Nexent workloads failed to become ready."
        exit 1
    fi

    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"; then
        echo "Synchronizing official skills to the workspace PVC..."
        if ! sync_official_skills_to_workspace; then
            echo "Error: official skills synchronization failed."
            exit 1
        fi
    fi

    # Step 9: Create the super admin user when Supabase is selected.
    CREATE_SUADMIN_SCRIPT="$SCRIPT_DIR/create-suadmin.sh"
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        if [ -f "$CREATE_SUADMIN_SCRIPT" ]; then
            echo ""
            echo "=========================================="
            echo "  Super Admin User Creation"
            echo "=========================================="
            if ! bash "$CREATE_SUADMIN_SCRIPT"; then
                echo "Error: Super admin user creation failed. Deployment aborted."
                exit 1
            fi
        else
            echo "Error: create-suadmin.sh not found at $CREATE_SUADMIN_SCRIPT"
            exit 1
        fi
    fi

    # Save deployment options and prepare local helper images.
    persist_deploy_options
    pull_mcp_image
    pull_sandbox_image

    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "部署完成！"
        echo "应用访问地址：http://localhost:30000"
    else
        echo "Deployment completed successfully!"
        echo "Access the application at: http://localhost:30000"
    fi
    if [ "$ENABLE_OPENSSH" = "true" ]; then
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "SSH Terminal 地址：localhost:30022"
        else
            echo "SSH Terminal at: localhost:30022"
        fi
    fi
}

print_usage() {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "用法：$0 [apply] [选项]"
        echo ""
        echo "使用 Helm 部署 Nexent K8s 资源。"
        echo ""
        echo "选项："
        echo "  --release-scope SCOPE     all、infrastructure 或 nexent（默认：all）"
        echo "  --components LIST          要部署的组件"
        echo "  --port-policy POLICY       development 或 production"
        echo "  --image-source SOURCE      general、mainland 或 local-latest"
        echo "  --image-registry-prefix P  镜像仓库前缀，例如 registry.example.com/nexent"
        echo "  --is-mainland Y|N          兼容旧参数，映射为 mainland/general 镜像源"
        echo "  --version VERSION          指定应用版本（未设置时自动从 const.py 检测）"
        echo "  --defaults                 复用保存配置或内置默认值并跳过交互界面"
        echo "  --deployment-version VER   兼容旧部署版本：speed 或 full"
        echo "  --persistence-mode MODE    local、dynamic 或 existing"
        echo "  --storage-class NAME       用于 PV/PVC 绑定的 StorageClass（别名：--storageclass、--storage-class-name、--sc）"
        echo "  --local-path PATH          本地 PV 基础路径"
        echo "  --local-node-name NAME     已废弃；local 模式使用 hostPath，不需要 nodeAffinity"
        echo "  --existing-claim-prefix P  现有 PVC 前缀，渲染为 P-<component>"
        echo "  --wait-timeout SECONDS     Kubernetes 部署等待超时（默认：600）"
        echo "  --rotate-secrets           强制轮换部署密钥"
        echo "  --refresh-es-key           强制重新创建 ELASTICSEARCH_API_KEY"
        echo "  --config                   进入交互式部署配置界面"
        echo "  --help, -h                 显示帮助信息"
        echo ""
        echo "示例："
        echo "  bash deploy.sh --release-scope all"
        echo "  bash deploy.sh --release-scope infrastructure"
        echo "  bash deploy.sh --release-scope nexent"
        echo ""
        echo "卸载：bash uninstall.sh"
        return
    fi

    echo "Usage: $0 [apply] [options]"
    echo ""
    echo "Deploy Nexent K8s resources using Helm."
    echo ""
    echo "Options:"
    echo "  --release-scope SCOPE     all, infrastructure, or nexent (default: all)"
    echo "  --components LIST          Components to deploy"
    echo "  --port-policy POLICY       development or production"
    echo "  --image-source SOURCE      general, mainland, or local-latest"
    echo "  --image-registry-prefix P  Image registry prefix, e.g. registry.example.com/nexent"
    echo "  --is-mainland Y|N          Legacy alias for image source mainland/general"
    echo "  --version VERSION          Specify app version (auto-detected from const.py if not set)"
    echo "  --defaults                 Use saved config or built-in defaults and skip TUI"
    echo "  --deployment-version VER   Legacy deployment version: speed or full"
    echo "  --persistence-mode MODE    local, dynamic, or existing"
    echo "  --storage-class NAME       StorageClass for PV/PVC binding (aliases: --storageclass, --storage-class-name, --sc)"
    echo "  --local-path PATH          Base path for local PVs"
    echo "  --local-node-name NAME     Deprecated; local mode uses hostPath and does not require nodeAffinity"
    echo "  --existing-claim-prefix P  Existing PVC prefix, rendered as P-<component>"
    echo "  --wait-timeout SECONDS    Kubernetes deployment wait timeout (default: 600)"
    echo "  --rotate-secrets           Force rotation of deployment secrets"
    echo "  --refresh-es-key           Force recreation of ELASTICSEARCH_API_KEY"
    echo "  --config                   Open the interactive deployment configuration"
    echo "  --help, -h                 Show this help message"
    echo ""
    echo "Examples:"
    echo "  bash deploy.sh --release-scope all"
    echo "  bash deploy.sh --release-scope infrastructure"
    echo "  bash deploy.sh --release-scope nexent"
    echo ""
    echo "Uninstall: bash uninstall.sh"
}

case "$COMMAND" in
help)
    print_usage
    ;;
apply)
    apply
    ;;
esac
