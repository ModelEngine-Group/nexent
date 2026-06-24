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
CHART_DIR="$SCRIPT_DIR/helm/nexent"
COMMON_VALUES="$CHART_DIR/charts/nexent-common/values.yaml"
NAMESPACE="nexent"
RELEASE_NAME="nexent"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"
VERSION_HELPER="$DEPLOY_ROOT/common/version.sh"

# Constants for deployment options
K8S_ROOT="$SCRIPT_DIR"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
GENERATED_VALUES="$CHART_DIR/generated-values.yaml"
GENERATED_RUNTIME_VALUES="$CHART_DIR/generated-runtime-values.yaml"
GENERATED_SECRETS_VALUES="$CHART_DIR/generated-secrets-values.yaml"
GENERATED_PERSISTENCE_VALUES="$CHART_DIR/generated-persistence-values.yaml"
ROOT_ENV_FILE="$PROJECT_ROOT/.env"
SQL_INIT_FILE="$DEPLOY_ROOT/sql/init.sql"
SUPABASE_SQL_DIR="$DEPLOY_ROOT/sql/supabase"

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
    echo "K8s uninstall and cleanup have moved to uninstall.sh."
    echo "Use: bash uninstall.sh ${1}"
    exit 1
    ;;
  *)
    echo "Unknown command: $1"
    echo "Usage: $0 [apply] [options]"
    echo "Uninstall: bash uninstall.sh"
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
      shift 2
      ;;
    --version)
      APP_VERSION="$2"
      shift 2
      ;;
    --deployment-version)
      DEPLOYMENT_VERSION="$2"
      shift 2
      ;;
    --persistence-mode)
      PERSISTENCE_MODE="$2"
      shift 2
      ;;
    --storage-class)
      STORAGE_CLASS_NAME="$2"
      shift 2
      ;;
    --local-path)
      LOCAL_PATH="$2"
      shift 2
      ;;
    --local-node-name)
      LOCAL_NODE_NAME="$2"
      shift 2
      ;;
    --existing-claim-prefix)
      EXISTING_CLAIM_PREFIX="$2"
      shift 2
      ;;
    --wait-timeout)
      K8S_WAIT_TIMEOUT_SECONDS="$2"
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

cd "$SCRIPT_DIR"
deployment_source_root_env "$PROJECT_ROOT" "$PROJECT_ROOT/docker" || exit 1

# Helper function to sanitize input (remove Windows CR)
sanitize_input() {
  local input="$1"
  printf "%s" "$input" | tr -d '\r'
}

apply_deployment_common_config() {
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

    deployment_apply_image_source
    deployment_render_helm_values "$GENERATED_VALUES"
    render_k8s_runtime_config_values "$GENERATED_RUNTIME_VALUES"
    render_persistence_values "$GENERATED_PERSISTENCE_VALUES"
    deployment_print_summary k8s
}

detect_local_node_name() {
  if [ -n "$LOCAL_NODE_NAME" ]; then
    return 0
  fi
  if [ "$PERSISTENCE_MODE" != "local" ]; then
    return 0
  fi
  if command -v kubectl >/dev/null 2>&1; then
    LOCAL_NODE_NAME="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  fi
  if [ -z "$LOCAL_NODE_NAME" ]; then
    echo "Error: --persistence-mode local requires a Kubernetes node name for local PV nodeAffinity."
    echo "Provide --local-node-name <node> or ensure kubectl can read the target cluster nodes."
    exit 1
  fi
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
    printf '      - ReadWriteOnce\n'
    printf '    localPath: "%s/%s"\n' "$LOCAL_PATH" "$component"
    printf '    localNodeName: "%s"\n' "$LOCAL_NODE_NAME"
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
    printf '      - ReadWriteOnce\n'
    printf '    localPath: "%s"\n' "$LOCAL_PATH"
    printf '    localNodeName: "%s"\n' "$LOCAL_NODE_NAME"
    printf '    existingClaimPrefix: "%s"\n' "$EXISTING_CLAIM_PREFIX"
  } >> "$output_file"
}

render_persistence_values() {
  local output_file="$1"
  case "$PERSISTENCE_MODE" in
    local|dynamic|existing) ;;
    *)
      echo "Unsupported persistence mode: $PERSISTENCE_MODE"
      echo "Use local, dynamic, or existing."
      exit 1
      ;;
  esac

  detect_local_node_name
  {
    echo "# Generated persistence overrides"
  } > "$output_file"

  render_one_persistence_values "$output_file" "nexent-elasticsearch" "nexent-elasticsearch" "20Gi"
  render_one_persistence_values "$output_file" "nexent-postgresql" "nexent-postgresql" "10Gi"
  render_one_persistence_values "$output_file" "nexent-redis" "nexent-redis" "5Gi"
  render_one_persistence_values "$output_file" "nexent-minio" "nexent-minio" "20Gi"
  render_one_persistence_values "$output_file" "nexent-supabase-db" "nexent-supabase-db" "10Gi"
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    render_monitoring_persistence_values "$output_file"
  fi
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

render_k8s_runtime_config_values() {
  local output_file="$1"
  if [ ! -f "$SQL_INIT_FILE" ]; then
    echo "Error: SQL init file not found: $SQL_INIT_FILE"
    exit 1
  fi
  {
    echo "nexent-common:"
    echo "  initSql: |"
    sed 's/^/    /' "$SQL_INIT_FILE"
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
    printf '    skillsPath: %s\n' "$(yaml_quote "$(env_or_default SKILLS_PATH "/mnt/nexent/skills")")"
    printf '    marketBackend: %s\n' "$(yaml_quote "$(env_or_default MARKET_BACKEND "http://60.204.251.153:8010")")"
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
    printf '      rayNumCpus: %s\n' "$(yaml_quote "$(env_or_default RAY_NUM_CPUS "4")")"
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
    printf '      queues: %s\n' "$(yaml_quote "$(env_or_default QUEUES "process_q,forward_q")")"
    printf '      workerName: %s\n' "$(yaml_quote "$(env_or_default WORKER_NAME "")")"
    printf '      workerConcurrency: %s\n' "$(yaml_quote "$(env_or_default WORKER_CONCURRENCY "4")")"
    echo "    telemetry:"
    printf '      enabled: %s\n' "$(yaml_quote "$(env_or_default ENABLE_TELEMETRY "false")")"
    printf '      provider: %s\n' "$(yaml_quote "$(env_or_default MONITORING_PROVIDER "otlp")")"
    printf '      projectName: %s\n' "$(yaml_quote "$(env_or_default MONITORING_PROJECT_NAME "")")"
    printf '      serviceName: %s\n' "$(yaml_quote "$(env_or_default OTEL_SERVICE_NAME "nexent-backend")")"
    printf '      otlpEndpoint: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_ENDPOINT "http://nexent-otel-collector:4318")")"
    printf '      otlpTracesEndpoint: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_TRACES_ENDPOINT "")")"
    printf '      otlpMetricsEndpoint: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_METRICS_ENDPOINT "")")"
    printf '      otlpProtocol: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_PROTOCOL "http")")"
    printf '      otlpHeaders: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_HEADERS "")")"
    printf '      otlpAuthorization: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_AUTHORIZATION "")")"
    printf '      otlpApiKey: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_X_API_KEY "")")"
    printf '      otlpLangfuseIngestionVersion: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION "")")"
    printf '      langsmithApiKey: %s\n' "$(yaml_quote "$(env_or_default LANGSMITH_API_KEY "")")"
    printf '      langsmithProject: %s\n' "$(yaml_quote "$(env_or_default LANGSMITH_PROJECT "")")"
    printf '      otlpMetricsEnabled: %s\n' "$(yaml_quote "$(env_or_default OTEL_EXPORTER_OTLP_METRICS_ENABLED "true")")"
    printf '      instrumentRequests: %s\n' "$(yaml_quote "$(env_or_default MONITORING_INSTRUMENT_REQUESTS "false")")"
    printf '      fastapiIncludedUrls: %s\n' "$(yaml_quote "$(env_or_default MONITORING_FASTAPI_INCLUDED_URLS "")")"
    printf '      fastapiExcludedUrls: %s\n' "$(yaml_quote "$(env_or_default MONITORING_FASTAPI_EXCLUDED_URLS "")")"
    printf '      fastapiExcludeSpans: %s\n' "$(yaml_quote "$(env_or_default MONITORING_FASTAPI_EXCLUDE_SPANS "receive,send")")"
    printf '      dashboardUrl: %s\n' "$(yaml_quote "$(env_or_default MONITORING_DASHBOARD_URL "")")"
    printf '      telemetrySampleRate: %s\n' "$(yaml_quote "$(env_or_default TELEMETRY_SAMPLE_RATE "1.0")")"
    printf '      traceContentMode: %s\n' "$(yaml_quote "$(env_or_default MONITORING_TRACE_CONTENT_MODE "full")")"
    printf '      traceMaxChars: %s\n' "$(yaml_quote "$(env_or_default MONITORING_TRACE_MAX_CHARS "4000")")"
    printf '      traceMaxItems: %s\n' "$(yaml_quote "$(env_or_default MONITORING_TRACE_MAX_ITEMS "20")")"
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
    echo "    cas:"
    printf '      enabled: %s\n' "$(yaml_quote "$(env_or_default CAS_ENABLED "false")")"
    printf '      serverUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_SERVER_URL "")")"
    printf '      validatePath: %s\n' "$(yaml_quote "$(env_or_default CAS_VALIDATE_PATH "/p3/serviceValidate")")"
    printf '      callbackBaseUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_CALLBACK_BASE_URL "http://localhost:30000")")"
    printf '      loginMode: %s\n' "$(yaml_quote "$(env_or_default CAS_LOGIN_MODE "disabled")")"
    printf '      userAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_USER_ATTRIBUTE "")")"
    printf '      emailAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_EMAIL_ATTRIBUTE "email")")"
    printf '      roleAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_ROLE_ATTRIBUTE "role")")"
    printf '      tenantAttribute: %s\n' "$(yaml_quote "$(env_or_default CAS_TENANT_ATTRIBUTE "tenant_id")")"
    printf '      roleMapJson: %s\n' "$(yaml_quote "$(env_or_default CAS_ROLE_MAP_JSON "")")"
    printf '      sessionMaxAgeSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_SESSION_MAX_AGE_SECONDS "3600")")"
    printf '      localSessionMaxAgeSeconds: %s\n' "$(yaml_quote "$(env_or_default LOCAL_SESSION_MAX_AGE_SECONDS "3600")")"
    printf '      renewBeforeSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_RENEW_BEFORE_SECONDS "300")")"
    printf '      renewTimeoutSeconds: %s\n' "$(yaml_quote "$(env_or_default CAS_RENEW_TIMEOUT_SECONDS "10")")"
    printf '      syntheticEmailDomain: %s\n' "$(yaml_quote "$(env_or_default CAS_SYNTHETIC_EMAIL_DOMAIN "cas.local")")"
    printf '      logoutUrl: %s\n' "$(yaml_quote "$(env_or_default CAS_LOGOUT_URL "")")"
    printf '      sslVerify: %s\n' "$(yaml_quote "$(env_or_default CAS_SSL_VERIFY "true")")"
    printf '      caBundle: %s\n' "$(yaml_quote "$(env_or_default CAS_CA_BUNDLE "")")"
    echo "nexent-supabase-db:"
    echo "  initScripts:"
    render_yaml_literal_file "jwt" "$SUPABASE_SQL_DIR/jwt.sql" 4 6
    render_yaml_literal_file "pooler" "$SUPABASE_SQL_DIR/pooler.sql" 4 6
    render_yaml_literal_file "logs" "$SUPABASE_SQL_DIR/logs.sql" 4 6
    render_yaml_literal_file "realtime" "$SUPABASE_SQL_DIR/realtime.sql" 4 6
    render_yaml_literal_file "roles" "$SUPABASE_SQL_DIR/roles.sql" 4 6
    render_yaml_literal_file "supabase" "$SUPABASE_SQL_DIR/_supabase.sql" 4 6
    render_yaml_literal_file "webhooks" "$SUPABASE_SQL_DIR/webhooks.sql" 4 6
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
  {
    echo "APP_VERSION=\"${APP_VERSION}\""
    echo "IS_MAINLAND=\"${IS_MAINLAND_SAVED}\""
    echo "DEPLOYMENT_VERSION=\"${VERSION_CHOICE_SAVED}\""
  } > "$DEPLOY_OPTIONS_FILE"
}

# Load deployment options from file if exists
load_deploy_options() {
  if [ -f "$DEPLOY_OPTIONS_FILE" ]; then
    source "$DEPLOY_OPTIONS_FILE"
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
  deployment_render_helm_values "$GENERATED_VALUES"
  render_k8s_runtime_config_values "$GENERATED_RUNTIME_VALUES"
  render_persistence_values "$GENERATED_PERSISTENCE_VALUES"
  echo "Generated Helm values: $GENERATED_VALUES"
  echo "Generated Helm runtime values: $GENERATED_RUNTIME_VALUES"
  echo "Generated Helm persistence values: $GENERATED_PERSISTENCE_VALUES"
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

helm_upgrade_release() {
    helm upgrade --install nexent "$CHART_DIR" \
        --namespace "$NAMESPACE" \
        -f "$GENERATED_VALUES" \
        -f "$GENERATED_RUNTIME_VALUES" \
        -f "$GENERATED_PERSISTENCE_VALUES" \
        -f "$GENERATED_SECRETS_VALUES" \
        --set nexent-openssh.enabled="$ENABLE_OPENSSH" \
        --set nexent-common.secrets.ssh.username="$SSH_USERNAME" \
        --set nexent-common.secrets.ssh.password="$SSH_PASSWORD"
}

wait_for_deployment_ready() {
    local deployment="$1"
    kubectl rollout status "deployment/${deployment}" -n "$NAMESPACE" --timeout="${K8S_WAIT_TIMEOUT_SECONDS}s"
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
    local encoded_value
    encoded_value=$(kubectl get secret nexent-secrets -n "$NAMESPACE" -o jsonpath="{.data.${key}}" 2>/dev/null || true)
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

    existing_access_key="$(get_existing_secret_value "MINIO_ACCESS_KEY")" || return 1
    existing_secret_key="$(get_existing_secret_value "MINIO_SECRET_KEY")" || return 1

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
        echo "Using Supabase secrets from root .env."
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

render_runtime_secret_values() {
    local gotrue_db_url
    local runtime_config_hash
    local backend_checksum
    local minio_checksum
    local supabase_checksum
    local web_checksum
    local ssh_checksum

    gotrue_db_url="$(env_or_default GOTRUE_DB_DATABASE_URL "postgres://supabase_auth_admin:$(env_or_default SUPABASE_POSTGRES_PASSWORD "Huawei123")@$(env_or_default SUPABASE_POSTGRES_HOST "nexent-supabase-db"):$(env_or_default SUPABASE_POSTGRES_PORT "5436")/$(env_or_default SUPABASE_POSTGRES_DB "supabase")?search_path=auth&sslmode=disable")"
    runtime_config_hash="$(deployment_sha256_file "$GENERATED_RUNTIME_VALUES")"
    backend_checksum="$(deployment_sha256_string "runtime=${runtime_config_hash}|elastic=$(env_or_default ELASTICSEARCH_API_KEY "")|postgres=$(env_or_default NEXENT_POSTGRES_PASSWORD "nexent@4321")|minio=${MINIO_ACCESS_KEY}:${MINIO_SECRET_KEY}")"
    minio_checksum="$(deployment_sha256_string "root=$(env_or_default MINIO_ROOT_USER "nexent"):$(env_or_default MINIO_ROOT_PASSWORD "nexent@4321")|client=${MINIO_ACCESS_KEY}:${MINIO_SECRET_KEY}")"
    supabase_checksum="$(deployment_sha256_string "jwt=${JWT_SECRET:-}|base=${SECRET_KEY_BASE:-}|vault=${VAULT_ENC_KEY:-}|anon=${SUPABASE_ANON_KEY:-}|service=${SUPABASE_SERVICE_ROLE_KEY:-}|pg=$(env_or_default SUPABASE_POSTGRES_PASSWORD "Huawei123")|db=${gotrue_db_url}")"
    web_checksum="$(deployment_sha256_string "market=$(env_or_default MARKET_BACKEND "http://60.204.251.153:8010")|model=$(env_or_default MODEL_ENGINE_ENABLED "false")")"
    ssh_checksum="$(deployment_sha256_string "ssh=$(env_or_default SSH_USERNAME "nexent"):$(env_or_default SSH_PASSWORD "nexent@2025")")"

    {
        echo "global:"
        echo "  rolloutChecksums:"
        printf '    backend: %s\n' "$(yaml_quote "$backend_checksum")"
        printf '    minio: %s\n' "$(yaml_quote "$minio_checksum")"
        printf '    supabase: %s\n' "$(yaml_quote "$supabase_checksum")"
        printf '    web: %s\n' "$(yaml_quote "$web_checksum")"
        printf '    ssh: %s\n' "$(yaml_quote "$ssh_checksum")"
        echo "nexent-common:"
        echo "  secrets:"
        printf '    elasticPassword: %s\n' "$(yaml_quote "$(env_or_default ELASTIC_PASSWORD "nexent@2025")")"
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
            printf '      postgresPassword: %s\n' "$(yaml_quote "$(env_or_default SUPABASE_POSTGRES_PASSWORD "Huawei123")")"
            printf '      gotrueDbUrl: %s\n' "$(yaml_quote "$gotrue_db_url")"
        fi
    } > "$GENERATED_SECRETS_VALUES"
}

apply() {
    echo "Deploying Nexent using Helm..."

    # Step 1: Select deployment components, port policy and image source.
    apply_deployment_common_config
    deployment_persist_local_config

    # Step 2: Render generated values with image tags from selected environment
    update_values_yaml

    # Step 3: Generate MinIO Access Key and Secret Key
    echo "=========================================="
    echo "  MinIO Access Key/Secret Key Setup"
    echo "=========================================="
    if [ -n "${MINIO_ACCESS_KEY:-}" ] && [ -n "${MINIO_SECRET_KEY:-}" ]; then
        echo "Using MinIO credentials from root .env."
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
        echo "MinIO credentials already exist in chart defaults"
        echo "Access Key: $MINIO_ACCESS_KEY"
    fi
    echo ""

    # Step 4: Generate Supabase secrets (only for full version)
    generate_supabase_secrets

    if [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" != "true" ] && [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ]; then
        if [ -n "${ELASTICSEARCH_API_KEY:-}" ]; then
            echo "Using ELASTICSEARCH_API_KEY from root .env."
        elif load_existing_elasticsearch_api_key; then
            echo "Reusing existing ELASTICSEARCH_API_KEY from Kubernetes secret."
        fi
    fi

    render_runtime_secret_values

    # Step 5: Configure Terminal tool (OpenSSH) only when selected.
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
        ENABLE_OPENSSH="true"
        echo "Terminal tool will be enabled."

        # Ask for SSH credentials
        echo ""
        echo "SSH credentials configuration:"
        read -p "SSH Username (default: nexent): " ssh_username
        SSH_USERNAME="${ssh_username:-nexent}"
        read -s -p "SSH Password (default: nexent@2025): " ssh_password
        echo ""
        SSH_PASSWORD="${ssh_password:-nexent@2025}"
    else
        ENABLE_OPENSSH="false"
        echo "Terminal tool disabled."
    fi
    echo ""

    # Step 6: Clean up stale PVs
    echo "Checking for stale PersistentVolumes..."
    for pv in nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv; do
        pv_status=$(kubectl get pv $pv -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        if [ "$pv_status" = "Released" ]; then
            echo "  Cleaning up stale PV: $pv"
            kubectl delete pv $pv --ignore-not-found=true || true
        fi
    done

    # Clean up supabase PV if exists
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        for pv in nexent-supabase-db-pv; do
            pv_status=$(kubectl get pv $pv -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
            if [ "$pv_status" = "Released" ]; then
                echo "  Cleaning up stale PV: $pv"
                kubectl delete pv $pv --ignore-not-found=true || true
            fi
        done
    fi

    # Step 7: Deploy using Helm
    ensure_namespace
    recreate_legacy_nexent_secret_for_helm_management
    echo "Deploying Helm chart..."
    helm_upgrade_release

    # Step 9: Wait for Elasticsearch to be ready and initialize API key
    echo ""
    echo "=========================================="
    echo "  Elasticsearch Initialization"
    echo "=========================================="
    local deploy_success=true

    echo "Waiting for Elasticsearch deployment to be ready..."
    sleep 5
    if wait_for_deployment_ready "nexent-elasticsearch"; then
        echo "Elasticsearch deployment is ready."

        # Initialize Elasticsearch API key only when it is missing, invalid, or explicitly refreshed.
        INIT_ES_SCRIPT="$SCRIPT_DIR/init-elasticsearch.sh"
        if [ -f "$INIT_ES_SCRIPT" ]; then
            echo "Running Elasticsearch initialization script..."
            local es_key_before
            local es_key_after
            local es_key_output_file
            es_key_before="$(get_existing_secret_value "ELASTICSEARCH_API_KEY" || true)"
            es_key_output_file="$(mktemp "${TMPDIR:-/tmp}/nexent-es-key.XXXXXX")"
            if ELASTICSEARCH_API_KEY_OUTPUT_FILE="$es_key_output_file" DEPLOYMENT_REFRESH_ES_KEY="${DEPLOYMENT_REFRESH_ES_KEY:-false}" DEPLOYMENT_ROTATE_SECRETS="${DEPLOYMENT_ROTATE_SECRETS:-false}" bash "$INIT_ES_SCRIPT"; then
                if [ -s "$es_key_output_file" ]; then
                    es_key_after="$(cat "$es_key_output_file")"
                else
                    es_key_after="$es_key_before"
                fi
                rm -f "$es_key_output_file"
                echo "Elasticsearch API key initialized successfully."

                if [ "$es_key_before" != "$es_key_after" ]; then
                    echo ""
                    echo "ELASTICSEARCH_API_KEY updated; refreshing Helm values and rolling affected backend services..."
                    ELASTICSEARCH_API_KEY="$es_key_after"
                    render_runtime_secret_values
                    helm_upgrade_release

                    local backend_services="config runtime mcp northbound"
                    deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process" && backend_services="$backend_services data-process"

                    echo ""
                    echo "Waiting for backend services to be ready..."
                    sleep 5
                    for svc in $backend_services; do
                        echo "  Waiting for nexent-$svc..."
                        if wait_for_deployment_ready "nexent-$svc"; then
                            echo "  nexent-$svc is ready."
                        else
                            echo "  Error: nexent-$svc did not become ready within ${K8S_WAIT_TIMEOUT_SECONDS}s."
                            deploy_success=false
                        fi
                    done
                else
                    echo "ELASTICSEARCH_API_KEY unchanged; backend rollout is not needed."
                fi
            else
                rm -f "$es_key_output_file"
                echo "Error: Elasticsearch initialization script failed."
                deploy_success=false
            fi
        else
            echo "Error: init-elasticsearch.sh not found at $INIT_ES_SCRIPT"
            deploy_success=false
        fi
    else
        echo "Error: nexent-elasticsearch did not become ready within ${K8S_WAIT_TIMEOUT_SECONDS}s."
        deploy_success=false
    fi

    if [ "$deploy_success" = false ]; then
        echo ""
        echo "=========================================="
        echo "  Deployment Failed!"
        echo "=========================================="
        exit 1
    fi

    # Step 10: Create super admin user (only for full deployment)
    CREATE_SUADMIN_SCRIPT="$SCRIPT_DIR/create-suadmin.sh"
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        if [ -f "$CREATE_SUADMIN_SCRIPT" ]; then
            echo ""
            echo "=========================================="
            echo "  Super Admin User Creation"
            echo "=========================================="
            if bash "$CREATE_SUADMIN_SCRIPT"; then
                echo "Super admin user creation completed."
            else
                echo "Warning: Super admin user creation failed, but continuing deployment."
            fi
        else
            echo "Warning: create-suadmin.sh not found at $CREATE_SUADMIN_SCRIPT"
        fi
    fi

    # Save deployment options for future use
    persist_deploy_options
    deployment_persist_local_config

    # Step 11: Pull MCP image after persisting deployment options
    pull_mcp_image

    echo "Deployment completed successfully!"
    echo "Access the application at: http://localhost:30000"
    if [ "$ENABLE_OPENSSH" = "true" ]; then
        echo "SSH Terminal at: localhost:30022"
    fi
}

print_usage() {
    echo "Usage: $0 [apply] [options]"
    echo ""
    echo "Deploy Nexent K8s resources using Helm."
    echo ""
    echo "Options:"
    echo "  --components LIST          Components to deploy"
    echo "  --port-policy POLICY       development or production"
    echo "  --image-source SOURCE      general, mainland, or local-latest"
    echo "  --is-mainland Y|N          Legacy alias for image source mainland/general"
    echo "  --version VERSION          Specify app version (auto-detected from const.py if not set)"
    echo "  --deployment-version VER   Legacy deployment version: speed or full"
    echo "  --persistence-mode MODE    local, dynamic, or existing"
    echo "  --storage-class NAME       StorageClass for PVCs"
    echo "  --local-path PATH          Base path for local PVs"
    echo "  --local-node-name NAME     Node name for local PV nodeAffinity"
    echo "  --existing-claim-prefix P  Existing PVC prefix, rendered as P-<component>"
    echo "  --wait-timeout SECONDS    Kubernetes deployment wait timeout (default: 600)"
    echo "  --rotate-secrets           Force rotation of deployment secrets"
    echo "  --refresh-es-key           Force recreation of ELASTICSEARCH_API_KEY"
    echo "  --help, -h                 Show this help message"
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
