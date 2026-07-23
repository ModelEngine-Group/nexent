#!/bin/bash

# Ensure the script is executed with bash (required for arrays and [[ ]])
if [ -z "$BASH_VERSION" ]; then
  echo "❌ This script must be run with bash. Please use: bash deploy.sh or ./deploy.sh"
  exit 1
fi

# Exit immediately if a command exits with a non-zero status
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"
VERSION_HELPER="$DEPLOY_ROOT/common/version.sh"
ORIGINAL_ARGS=("$@")
ROOT_ENV_FILE="$DEPLOY_ROOT/env/.env"
COMPOSE_DIR="$SCRIPT_DIR/compose"
DOCKER_ASSETS_DIR="$SCRIPT_DIR/assets"
MONITORING_ENV_FILE="$DEPLOY_ROOT/env/monitoring.env"
SQL_DIR="$DEPLOY_ROOT/sql"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
else
  echo "❌ Shared deployment helper not found: $DEPLOYMENT_COMMON"
  exit 1
fi

if [ -f "$VERSION_HELPER" ]; then
  # shellcheck source=/dev/null
  source "$VERSION_HELPER"
fi

MODE_CHOICE_SAVED=""
VERSION_CHOICE_SAVED=""
IS_MAINLAND_SAVED=""
ENABLE_SKILLS_SAVED="Y"
ENABLE_TERMINAL_SAVED="N"
TERMINAL_MOUNT_DIR_SAVED="${TERMINAL_MOUNT_DIR:-}"
APP_VERSION=""

cd "$SCRIPT_DIR"

deployment_source_root_env "$PROJECT_ROOT" "$PROJECT_ROOT/docker" || exit 1

# Parse arg
MODE_CHOICE=""
IS_MAINLAND=""
ENABLE_TERMINAL=""
VERSION_CHOICE=""
ROOT_DIR_PARAM=""

# Suppress the orphan warning
export COMPOSE_IGNORE_ORPHANS=True

print_docker_deploy_usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "用法：$0 [选项]"
    echo ""
    echo "部署选项："
    echo "  --components LIST          要部署的组件列表"
    echo "  --port-policy POLICY       development 或 production"
    echo "  --image-source SOURCE      general、mainland 或 local-latest"
    echo "  --registry-profile NAME    兼容旧参数，映射为 general/mainland 镜像源"
    echo "  --image-registry-prefix P  镜像仓库前缀，例如 registry.example.com/nexent"
    echo "  --monitoring-provider NAME 选中 monitoring 组件时使用的监控 provider"
    echo "  --version VERSION          指定应用版本（未设置时自动检测）"
    echo "  --defaults                 复用保存配置或内置默认值并跳过交互界面"
    echo "  --use-local-config         复用保存的本地部署配置并跳过交互界面"
    echo "  --reconfigure              使用保存配置作为默认值并进入交互式配置界面"
    echo "  --rotate-secrets           强制轮换部署密钥"
    echo "  --refresh-es-key           强制重新创建 ELASTICSEARCH_API_KEY"
    echo "  --config                   进入交互式部署配置界面"
    echo "  --root-dir PATH            Docker 数据和运行文件根目录"
    echo "  --help, -h                 显示帮助信息"
    echo ""
    echo "卸载：bash uninstall.sh"
    return
  fi

  echo "Usage: $0 [options]"
  echo ""
  echo "Deploy options:"
  echo "  --components LIST          Components to deploy"
  echo "  --port-policy POLICY       development or production"
  echo "  --image-source SOURCE      general, mainland, or local-latest"
  echo "  --registry-profile NAME    Legacy alias for image source general/mainland"
  echo "  --image-registry-prefix P  Image registry prefix, e.g. registry.example.com/nexent"
  echo "  --monitoring-provider NAME Monitoring provider when monitoring is selected"
  echo "  --version VERSION          Specify app version (auto-detected if not set)"
  echo "  --defaults                 Use saved config or built-in defaults and skip TUI"
  echo "  --use-local-config         Reuse saved local deployment config and skip TUI"
  echo "  --reconfigure              Open TUI using saved local config as defaults"
  echo "  --rotate-secrets           Force rotation of deployment secrets"
  echo "  --refresh-es-key           Force recreation of ELASTICSEARCH_API_KEY"
  echo "  --config                   Open the interactive deployment configuration"
  echo "  --root-dir PATH            Root directory for Docker data and runtime files"
  echo "  --help, -h                 Show this help message"
  echo ""
  echo "Uninstall: bash uninstall.sh"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    delete|delete-all|--delete-volumes|--remove-volumes|--keep-volumes)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "❌ Docker 卸载已迁移到 uninstall.sh。请使用：bash uninstall.sh"
      else
        echo "❌ Docker uninstall has moved to uninstall.sh. Use: bash uninstall.sh"
      fi
      exit 1
      ;;
    --help|-h)
      print_docker_deploy_usage
      exit 0
      ;;
    --mode)
      MODE_CHOICE="$2"
      shift 2
      ;;
    --is-mainland)
      IS_MAINLAND="$2"
      shift 2
      ;;
    --enable-terminal)
      ENABLE_TERMINAL="$2"
      shift 2
      ;;
    --version)
      VERSION_CHOICE="$2"
      shift 2
      ;;
    --root-dir)
      ROOT_DIR_PARAM="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

sanitize_input() {
  local input="$1"
  printf "%s" "$input" | tr -d '\r'
}

is_windows_env() {
  # Detect Windows Git Bash / MSYS / MINGW environment
  local os_name
  os_name=$(uname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')
  if [[ "$os_name" == mingw* || "$os_name" == msys* ]]; then
    return 0
  fi
  return 1
}

is_port_in_use() {
  # Check if a TCP port is already in use (Linux/macOS/Windows Git Bash)
  local port="$1"

  # Prefer lsof when available (typically on Linux/macOS)
  if command -v lsof >/dev/null 2>&1 && ! is_windows_env; then
    if lsof -iTCP:"$port" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
      return 0
    fi
    return 1
  fi

  # Fallback to ss if available
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:\.]${port}$"; then
      return 0
    fi
    return 1
  fi

  # Fallback to netstat (works on Windows and many Linux distributions)
  if command -v netstat >/dev/null 2>&1; then
    if netstat -an 2>/dev/null | grep -qE "[:\.]${port}[[:space:]]"; then
      return 0
    fi
    return 1
  fi

  # If no inspection tool is available, assume the port is free
  return 1
}

is_nexent_container_name() {
  local container_name="$1"

  case "$container_name" in
    nexent-*|nexent_*|supabase-*-mini)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

docker_containers_using_host_port() {
  local port="$1"

  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi

  while IFS=$'\t' read -r container_name published_ports; do
    if [ -n "$container_name" ] && [[ "$published_ports" == *":${port}->"* ]]; then
      echo "$container_name"
    fi
  done < <(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null)
}

is_port_used_by_nexent_only() {
  local port="$1"
  local container_name
  local found="false"

  while IFS= read -r container_name; do
    [ -n "$container_name" ] || continue
    found="true"
    if ! is_nexent_container_name "$container_name"; then
      return 1
    fi
  done < <(docker_containers_using_host_port "$port")

  [ "$found" = "true" ]
}

add_port_if_new() {
  # Helper to add a port to global arrays only if not already present
  local port="$1"
  local source="$2"
  local existing_port

  for existing_port in "${PORTS_TO_CHECK[@]}"; do
    if [ "$existing_port" = "$port" ]; then
      return 0
    fi
  done

  PORTS_TO_CHECK+=("$port")
  PORT_SOURCES+=("$source")
}

collect_ports_from_env_file() {
  # Collect ports from a single env file, based on addresses and *_PORT style variables
  local env_file="$1"

  if [ ! -f "$env_file" ]; then
    return 0
  fi

  # 1) Address-style values containing :PORT (for example http://host:3000)
  #    We only care about the numeric port part.
  while IFS= read -r match; do
    local port="${match#:}"
    port=$(echo "$port" | tr -d '[:space:]')
    if [[ "$port" =~ ^[0-9]{2,5}$ ]]; then
      add_port_if_new "$port" "$env_file (address)"
    fi
  done < <(grep -Eo ':[0-9]{2,5}' "$env_file" 2>/dev/null | sort -u)

  # 2) Variables that explicitly define a port, for example FOO_PORT=3000
  while IFS= read -r line; do
    # Strip inline comments
    line="${line%%#*}"
    # Extract value part after '='
    local value="${line#*=}"
    value=$(echo "$value" | tr -d '[:space:]"'\''')
    if [[ "$value" =~ ^[0-9]{2,5}$ ]]; then
      add_port_if_new "$value" "$env_file (PORT variable)"
    fi
  done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*_PORT *= *[0-9]{2,5}' "$env_file" 2>/dev/null)
}

check_ports_in_env_files() {
  # Preflight check: ensure all ports referenced in env files are free
  PORTS_TO_CHECK=()
  PORT_SOURCES=()

  # Always include the deploy/env/.env if present, plus image-source env variants.
  local env_files=()
  if [ -f "$ROOT_ENV_FILE" ]; then
    env_files+=("$ROOT_ENV_FILE")
  fi

  # Include image-source env variants.
  local f
  for f in "$DEPLOY_ROOT"/env/image-source.*.env; do
    if [ -f "$f" ]; then
      env_files+=("$f")
    fi
  done

  # Collect ports from all discovered env files
  for f in "${env_files[@]}"; do
    collect_ports_from_env_file "$f"
  done

  if [ ${#PORTS_TO_CHECK[@]} -eq 0 ]; then
    echo "🔍 No port definitions found in environment files, skipping port availability check."
    echo ""
    echo "--------------------------------"
    echo ""
    return 0
  fi

  echo "🔍 Checking port availability defined in environment files..."
  local occupied_ports=()
  local occupied_sources=()
  local ignored_nexent_ports=0
  local free_ports=0

  local idx
  for idx in "${!PORTS_TO_CHECK[@]}"; do
    local port="${PORTS_TO_CHECK[$idx]}"
    local source="${PORT_SOURCES[$idx]}"

    if is_port_in_use "$port"; then
      if is_port_used_by_nexent_only "$port"; then
        ignored_nexent_ports=$((ignored_nexent_ports + 1))
        continue
      fi
      occupied_ports+=("$port")
      occupied_sources+=("$source")
      echo "   ❌ Port $port is already in use."
    else
      free_ports=$((free_ports + 1))
    fi
  done

  if [ "$free_ports" -gt 0 ]; then
    echo "   ✅ $free_ports port(s) available."
  fi

  if [ "$ignored_nexent_ports" -gt 0 ]; then
    echo "   ↺ Ignored $ignored_nexent_ports port(s) already used by Nexent containers."
  fi

  if [ ${#occupied_ports[@]} -gt 0 ]; then
    echo ""
    echo "❌ Port conflict detected. The following ports required by Nexent are already in use:"
    local i
    for i in "${!occupied_ports[@]}"; do
      echo "   - Port ${occupied_ports[$i]}"
    done
    echo ""
    echo "Please free these ports or update the corresponding .env files."
    echo ""

    # Ask user whether to continue deployment even if some ports are occupied
    local confirm_continue
    read -p "👉 Do you still want to continue deployment even though some ports are in use? [y/N]: " confirm_continue
    confirm_continue=$(sanitize_input "$confirm_continue")
    if ! [[ "$confirm_continue" =~ ^[Yy]$ ]]; then
      echo "🚫 Deployment aborted due to port conflicts."
      exit 1
    fi

    echo "⚠️  Continuing deployment even though some required ports are already in use."
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

check_deployment_ports() {
  PORTS_TO_CHECK=()
  PORT_SOURCES=()

  local port
  for port in $DEPLOYMENT_DOCKER_PORTS; do
    add_port_if_new "$port" "deployment port policy: $DEPLOYMENT_PORT_POLICY"
  done

  if [ ${#PORTS_TO_CHECK[@]} -eq 0 ]; then
    echo "🔍 No host ports are published by the selected deployment configuration."
    echo ""
    echo "--------------------------------"
    echo ""
    return 0
  fi

  echo "🔍 Checking port availability for selected deployment policy..."
  local occupied_ports=()
  local ignored_nexent_ports=0
  local free_ports=0
  local idx
  for idx in "${!PORTS_TO_CHECK[@]}"; do
    local selected_port="${PORTS_TO_CHECK[$idx]}"
    if is_port_in_use "$selected_port"; then
      if is_port_used_by_nexent_only "$selected_port"; then
        ignored_nexent_ports=$((ignored_nexent_ports + 1))
        continue
      fi
      occupied_ports+=("$selected_port")
      echo "   ❌ Port $selected_port is already in use."
    else
      free_ports=$((free_ports + 1))
    fi
  done

  if [ "$free_ports" -gt 0 ]; then
    echo "   ✅ $free_ports port(s) available."
  fi

  if [ "$ignored_nexent_ports" -gt 0 ]; then
    echo "   ↺ Ignored $ignored_nexent_ports port(s) already used by Nexent containers."
  fi

  if [ ${#occupied_ports[@]} -gt 0 ]; then
    echo ""
    echo "❌ Port conflict detected for selected deployment policy:"
    local occupied
    for occupied in "${occupied_ports[@]}"; do
      echo "   - Port $occupied"
    done
    echo ""
    local confirm_continue
    read -p "👉 Do you still want to continue deployment even though some ports are in use? [y/N]: " confirm_continue
    confirm_continue=$(sanitize_input "$confirm_continue")
    if ! [[ "$confirm_continue" =~ ^[Yy]$ ]]; then
      echo "🚫 Deployment aborted due to port conflicts."
      exit 1
    fi
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

trim_quotes() {
  local value="$1"
  value="${value%$'\r'}"
  value="${value%\"}"
  value="${value#\"}"
  echo "$value"
}

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
  value="$(trim_quotes "$line")"
  echo "$value"
}

persist_deploy_options() {
  {
    echo "APP_VERSION=\"${APP_VERSION}\""
    echo "ROOT_DIR=\"${ROOT_DIR}\""
    echo "MODE_CHOICE=\"${MODE_CHOICE_SAVED}\""
    echo "VERSION_CHOICE=\"${VERSION_CHOICE_SAVED}\""
    echo "IS_MAINLAND=\"${IS_MAINLAND_SAVED}\""
    echo "ENABLE_SKILLS=\"${ENABLE_SKILLS_SAVED}\""
    echo "ENABLE_TERMINAL=\"${ENABLE_TERMINAL_SAVED}\""
    echo "TERMINAL_MOUNT_DIR=\"${TERMINAL_MOUNT_DIR_SAVED}\""
  } > "$DEPLOY_OPTIONS_FILE"
}

generate_minio_ak_sk() {
  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ] && [ -n "${MINIO_ACCESS_KEY:-}" ] && [ -n "${MINIO_SECRET_KEY:-}" ]; then
    echo "   MinIO credentials unchanged; reusing deploy/env/.env values"
    export MINIO_ACCESS_KEY
    export MINIO_SECRET_KEY
    return 0
  fi

  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ]; then
    echo "🔁 Rotating MinIO keys..."
  else
    echo "🔑 Generating missing MinIO keys..."
  fi

  if [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "mingw" ] || [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "msys" ]; then
    # Windows
    ACCESS_KEY=$(powershell -Command "[System.Convert]::ToBase64String([System.Guid]::NewGuid().ToByteArray()) -replace '[^a-zA-Z0-9]', '' -replace '=.+$', '' | Select-Object -First 12")
    SECRET_KEY=$(powershell -Command '$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $bytes = New-Object byte[] 32; $rng.GetBytes($bytes); [System.Convert]::ToBase64String($bytes)')
  else
    # Linux/Mac
    # Generate a random AK (12-character alphanumeric)
    ACCESS_KEY=$(openssl rand -hex 12 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9]//g')

    # Generate a random SK (32-character high-strength random string)
    SECRET_KEY=$(openssl rand -base64 32 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9+/=]//g')
  fi

  if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo "   ❌ ERROR Failed to generate MinIO access keys"
    return 1
  fi

  export MINIO_ACCESS_KEY=$ACCESS_KEY
  export MINIO_SECRET_KEY=$SECRET_KEY

  update_env_var "MINIO_ACCESS_KEY" "$ACCESS_KEY"
  update_env_var "MINIO_SECRET_KEY" "$SECRET_KEY"

  echo "   ✅ MinIO keys generated successfully"
}

generate_jwt() {
  # Function to generate JWT token
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

generate_supabase_keys() {
  if [ "$DEPLOYMENT_VERSION" != "full" ]; then
    return 0
  fi

  echo "🔑 Checking Supabase keys..."

  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ] \
    && [ -n "${JWT_SECRET:-}" ] \
    && [ -n "${SECRET_KEY_BASE:-}" ] \
    && [ -n "${VAULT_ENC_KEY:-}" ] \
    && [ -n "${SUPABASE_KEY:-}" ] \
    && [ -n "${SERVICE_ROLE_KEY:-}" ]; then
    echo "   Supabase secrets unchanged; reusing deploy/env/.env values"
    return 0
  fi

  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ -z "${JWT_SECRET:-}" ]; then
    export JWT_SECRET=$(openssl rand -base64 32 | tr -d '[:space:]')
    update_env_var "JWT_SECRET" "$JWT_SECRET"
  fi
  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ -z "${SECRET_KEY_BASE:-}" ]; then
    export SECRET_KEY_BASE=$(openssl rand -base64 64 | tr -d '[:space:]')
    update_env_var "SECRET_KEY_BASE" "$SECRET_KEY_BASE"
  fi
  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ -z "${VAULT_ENC_KEY:-}" ]; then
    export VAULT_ENC_KEY=$(openssl rand -base64 32 | tr -d '[:space:]')
    update_env_var "VAULT_ENC_KEY" "$VAULT_ENC_KEY"
  fi

  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ -z "${SUPABASE_KEY:-}" ]; then
    SUPABASE_KEY=$(generate_jwt "anon")
    export SUPABASE_KEY
    update_env_var "SUPABASE_KEY" "$SUPABASE_KEY"
  fi
  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ -z "${SERVICE_ROLE_KEY:-}" ]; then
    SERVICE_ROLE_KEY=$(generate_jwt "service_role")
    export SERVICE_ROLE_KEY
    update_env_var "SERVICE_ROLE_KEY" "$SERVICE_ROLE_KEY"
  fi

  set -a
  source "$ROOT_ENV_FILE"
  set +a
  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ]; then
    echo "   ✅ Supabase secrets rotated"
  else
    echo "   ✅ Missing Supabase secrets generated"
  fi
}

validate_elasticsearch_api_key() {
  local api_key="$1"
  local http_code
  [ -n "$api_key" ] || return 1
  http_code=$(docker exec nexent-elasticsearch curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: ApiKey $api_key" \
    "http://localhost:9200/_security/_authenticate" 2>/dev/null || true)
  [ "$http_code" = "200" ]
}

generate_elasticsearch_api_key() {
  # Function to generate Elasticsearch API key
  wait_for_elasticsearch_healthy || { echo "   ❌ Elasticsearch health check failed"; return 0; }

  if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ] \
    && [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" != "true" ] \
    && [ -n "${ELASTICSEARCH_API_KEY:-}" ]; then
    echo "🔑 Validating existing ELASTICSEARCH_API_KEY..."
    if validate_elasticsearch_api_key "$ELASTICSEARCH_API_KEY"; then
      echo "   ELASTICSEARCH_API_KEY unchanged; existing key is valid"
      return 0
    fi
    echo "   Existing ELASTICSEARCH_API_KEY is invalid; generating a replacement"
  elif [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" = "true" ]; then
    echo "🔁 Refreshing ELASTICSEARCH_API_KEY by request..."
  fi

  # Generate API key
  echo "🔑 Generating ELASTICSEARCH_API_KEY..."
  API_KEY_JSON=$(docker exec nexent-elasticsearch curl -s -u "elastic:${ELASTIC_PASSWORD:-nexent@2025}" "http://localhost:9200/_security/api_key" -H "Content-Type: application/json" -d '{"name":"my_api_key","role_descriptors":{"my_role":{"cluster":["all"],"index":[{"names":["*"],"privileges":["all"]}]}}}')

  # Extract API key and add to .env
  ELASTICSEARCH_API_KEY=$(echo "$API_KEY_JSON" | grep -o '"encoded":"[^"]*"' | awk -F'"' '{print $4}')
  echo "✅ ELASTICSEARCH_API_KEY Generated: $ELASTICSEARCH_API_KEY"
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    update_env_var "ELASTICSEARCH_API_KEY" "$ELASTICSEARCH_API_KEY"
  fi
}

generate_env_for_infrastructure() {
  # Function to generate complete environment file for infrastructure mode using generate_env.sh
  echo "🔑 Updating deploy/env/.env for infrastructure mode..."
  echo "   🚀 Running generate_env.sh..."

  # Check if generate_env.sh exists
  if [ ! -f "$SCRIPT_DIR/generate_env.sh" ]; then
      echo "   ❌ ERROR generate_env.sh not found in deploy/docker directory"
      return 1
  fi

  # Make sure the script is executable and run it
  chmod +x "$SCRIPT_DIR/generate_env.sh"

  # Export DEPLOYMENT_VERSION to ensure generate_env.sh can access it
  export DEPLOYMENT_VERSION

  if DEPLOYMENT_ROOT_ENV="$ROOT_ENV_FILE" bash "$SCRIPT_DIR/generate_env.sh"; then
      echo "   ✅ deploy/env/.env updated successfully for infrastructure mode!"
      if [ -f "$ROOT_ENV_FILE" ]; then
          set -a
          source "$ROOT_ENV_FILE"
          set +a
          echo "   ✅ Environment variables loaded from deploy/env/.env"
      else
          echo "   ⚠️  Warning: deploy/env/.env file not found after generation"
          return 1
      fi
  else
      echo "   ❌ ERROR Failed to generate environment file"
      return 1
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

get_compose_version() {
  # Function to get the version of docker compose
  if command -v docker &> /dev/null; then
      version_output=$(docker compose version 2>/dev/null)
      if [[ $version_output =~ v([0-9]+\.[0-9]+\.[0-9]+) ]]; then
          echo "v2 ${BASH_REMATCH[1]}"
          return 0
      fi
  fi

  if command -v docker-compose &> /dev/null; then
      version_output=$(docker-compose --version 2>/dev/null)
      if [[ $version_output =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then
          echo "v1 ${BASH_REMATCH[1]}"
          return 0
      fi
  fi

  echo "unknown"
  return 0
}

disable_dashboard() {
  update_env_var "DISABLE_RAY_DASHBOARD" "true"
  update_env_var "DISABLE_CELERY_FLOWER" "true"
}

docker_monitoring_active_services() {
  printf '%s\n' otel-collector

  case "$DEPLOYMENT_MONITORING_PROVIDER" in
    phoenix)
      printf '%s\n' phoenix
      ;;
    grafana)
      printf '%s\n' tempo grafana
      ;;
    zipkin)
      printf '%s\n' zipkin
      ;;
    langfuse)
      printf '%s\n' langfuse-worker langfuse-web langfuse-clickhouse langfuse-minio langfuse-redis langfuse-postgres
      ;;
  esac
}

docker_monitoring_profile_services() {
  printf '%s\n' \
    phoenix \
    tempo \
    grafana \
    zipkin \
    langfuse-worker \
    langfuse-web \
    langfuse-clickhouse \
    langfuse-minio \
    langfuse-redis \
    langfuse-postgres
}

docker_monitoring_container_names() {
  printf '%s\n' \
    nexent-otel-collector \
    nexent-phoenix \
    nexent-tempo \
    nexent-grafana \
    nexent-zipkin \
    nexent-langfuse-worker \
    nexent-langfuse-web \
    nexent-langfuse-clickhouse \
    nexent-langfuse-minio \
    nexent-langfuse-redis \
    nexent-langfuse-postgres
}

docker_monitoring_containers_exist() {
  command -v docker >/dev/null 2>&1 || return 1

  local container
  while IFS= read -r container; do
    [ -n "$container" ] || continue
    if docker container inspect "$container" >/dev/null 2>&1; then
      return 0
    fi
  done < <(docker_monitoring_container_names)

  return 1
}

stop_monitoring_services() {
  local all_profile_args=(--profile phoenix --profile grafana --profile zipkin --profile langfuse)

  [ -f "$COMPOSE_DIR/docker-compose-monitoring.yml" ] || return 0
  docker_monitoring_containers_exist || return 0

  echo "🔭 Stopping monitoring services..."
  if ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE" "${all_profile_args[@]}" -f "$COMPOSE_DIR/docker-compose-monitoring.yml" down --remove-orphans; then
    echo "   ❌ ERROR Failed to stop monitoring services"
    return 1
  fi
}

cleanup_stale_monitoring_services() {
  local all_profile_args=(--profile phoenix --profile grafana --profile zipkin --profile langfuse)
  local active_services
  local service
  local stale_services=()

  active_services="$(docker_monitoring_active_services)"
  while IFS= read -r service; do
    [ -n "$service" ] || continue
    if ! printf '%s\n' "$active_services" | grep -Fxq "$service"; then
      stale_services+=("$service")
    fi
  done < <(docker_monitoring_profile_services)

  [ "${#stale_services[@]}" -gt 0 ] || return 0

  echo "   🧹 Removing stale monitoring provider services..."
  ${docker_compose_command} --env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE" "${all_profile_args[@]}" -f "$COMPOSE_DIR/docker-compose-monitoring.yml" stop "${stale_services[@]}" >/dev/null 2>&1 || true
  if ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE" "${all_profile_args[@]}" -f "$COMPOSE_DIR/docker-compose-monitoring.yml" rm -f "${stale_services[@]}"; then
    echo "   ❌ ERROR Failed to remove stale monitoring services"
    return 1
  fi
}

sync_monitoring_env_vars() {
  deployment_prepare_monitoring_env docker || return 1
}

pull_mcp_image() {
  if [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ]; then
    echo "🔄 Skipping MCP image pull because image source is local-latest."
    echo ""
    echo "--------------------------------"
    echo ""
    return 0
  fi

  echo "🔄 Checking MCP Docker image..."

  # Get MCP image name from environment or use default
  MCP_IMAGE_NAME=${NEXENT_MCP_DOCKER_IMAGE:-nexent/nexent-mcp:latest}
  echo "   📦 Image: ${MCP_IMAGE_NAME}"

  # Check if image already exists locally
  if docker image inspect "${MCP_IMAGE_NAME}" >/dev/null 2>&1; then
    echo "   ✅ MCP image already exists locally"
    echo "   💡 Skipping pull, using existing image"
  else
    echo "   📥 MCP image not found locally, pulling..."
    if docker pull "${MCP_IMAGE_NAME}"; then
      echo "   ✅ MCP image pulled successfully"
      echo "   💡 The image will be available when you need to start MCP services"
    else
      echo "   ⚠️  Failed to pull MCP image, but deployment continues"
      echo "   💡 You can manually pull the image later: docker pull ${MCP_IMAGE_NAME}"
    fi
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

select_deployment_mode() {
  echo "🎛️  Please select deployment mode:"
  echo "   1) 🛠️  Development mode - Expose all service ports for debugging"
  echo "   2) 🏗️  Infrastructure mode - Only start infrastructure services"
  echo "   3) 🚀 Production mode - Only expose port 3000 for security"

  if [ -n "$MODE_CHOICE" ]; then
    mode_choice="$MODE_CHOICE"
    echo "👉 Using mode_choice from argument: $mode_choice"
  else
    read -p "👉 Enter your choice [1/2/3] (default: 1): " mode_choice
  fi

  # Sanitize potential Windows CR in input
  mode_choice=$(sanitize_input "$mode_choice")
  MODE_CHOICE_SAVED="$mode_choice"

  case $mode_choice in
      2|"infrastructure")
          export DEPLOYMENT_MODE="infrastructure"
          export COMPOSE_FILE_SUFFIX=".yml"
          echo "✅ Selected infrastructure mode 🏗️"
          ;;
      3|"production")
          export DEPLOYMENT_MODE="production"
          export COMPOSE_FILE_SUFFIX=".prod.yml"
          disable_dashboard
          echo "✅ Selected production mode 🚀"
          ;;
      1|"development"|*)
          export DEPLOYMENT_MODE="development"
          export COMPOSE_FILE_SUFFIX=".yml"
          echo "✅ Selected development mode 🛠️"
          ;;
  esac
  echo ""

  if [ -n "$ROOT_DIR_PARAM" ]; then
  # Check if root-dir parameter is provided (highest priority)
    ROOT_DIR="$ROOT_DIR_PARAM"
    echo "   📁 Using ROOT_DIR from parameter: $ROOT_DIR"
    # Write to .env file
    if grep -q "^ROOT_DIR=" "$ROOT_ENV_FILE"; then
      # Update existing ROOT_DIR in .env
      update_env_var "ROOT_DIR" "$ROOT_DIR"
    else
      # Add new ROOT_DIR to .env
      update_env_var "ROOT_DIR" "$ROOT_DIR"
    fi
  elif grep -q "^ROOT_DIR=" "$ROOT_ENV_FILE"; then
  # Check if ROOT_DIR already exists in .env (second priority)
    # Extract existing ROOT_DIR value from .env
    env_root_dir=$(grep "^ROOT_DIR=" "$ROOT_ENV_FILE" | cut -d'=' -f2 | sed 's/^"//;s/"$//')
    ROOT_DIR="$env_root_dir"
    echo "   📁 Use existing ROOT_DIR path: $env_root_dir"

  else
  # Use default value and prompt user input (lowest priority)
    default_root_dir="$HOME/nexent-data"
    read -p "   📁 Enter ROOT_DIR path (default: $default_root_dir): " user_root_dir
    ROOT_DIR="${user_root_dir:-$default_root_dir}"

    update_env_var "ROOT_DIR" "$ROOT_DIR"
  fi
  echo ""
  echo "--------------------------------"
  echo ""
}

clean() {
  export MINIO_ACCESS_KEY=
  export MINIO_SECRET_KEY=
  export DEPLOYMENT_MODE=
  export COMPOSE_FILE_SUFFIX=
  export DEPLOYMENT_VERSION=

  rm -f "$ROOT_ENV_FILE.bak" ".env.bak"
}

update_env_var() {
  # Function to update or add a key-value pair to deploy/env/.env
  local key="$1"
  local value="$2"
  deployment_update_env_var_file "$ROOT_ENV_FILE" "$key" "$value"
  if [ "${DEPLOYMENT_LAST_ENV_WRITE_CHANGED:-false}" = "true" ]; then
    echo "   📝 .env updated: $key"
  else
    echo "   ↺ .env unchanged: $key"
  fi
}

create_dir_with_permission() {
  # Function to create a directory and set permissions
  local dir_path="$1"
  local permission="$2"

  # Check if parameters are provided
  if [ -z "$dir_path" ] || [ -z "$permission" ]; then
      echo "   ❌ ERROR Directory path and permission parameters are required." >&2
      return 1
  fi

  # Create the directory if it doesn't exist
  if [ ! -d "$dir_path" ]; then
      mkdir -p "$dir_path"
      if [ $? -ne 0 ]; then
          echo "   ❌ ERROR Failed to create directory $dir_path." >&2
          return 1
      fi
  fi

  # Set directory permissions
  if chmod -R "$permission" "$dir_path" 2>/dev/null; then
      echo "   📁 Directory $dir_path has been created and permissions set to $permission."
  fi
}

sql_files_checksum() {
  local payload=""
  local file rel checksum

  if [ ! -d "$SQL_DIR" ]; then
    echo "Error: SQL directory not found: $SQL_DIR" >&2
    return 1
  fi

  while IFS= read -r file; do
    [ -n "$file" ] || continue
    rel="${file#"$SQL_DIR/"}"
    checksum="$(deployment_sha256_file "$file")"
    payload="${payload}${rel}:${checksum}"$'\n'
  done < <(find "$SQL_DIR" -type f -name '*.sql' -print | sort -V)

  deployment_sha256_string "$payload"
}

update_sql_files_checksum() {
  NEXENT_SQL_FILES_CHECKSUM="$(sql_files_checksum)"
  export NEXENT_SQL_FILES_CHECKSUM
  update_env_var "NEXENT_SQL_FILES_CHECKSUM" "$NEXENT_SQL_FILES_CHECKSUM"
  echo "   SQL files checksum: $NEXENT_SQL_FILES_CHECKSUM"
}

prepare_directory_and_data() {
  # Initialize the sql script permission
  chmod 644 "$SQL_DIR/init.sql"

  echo "🔧 Creating directory with permission..."
  create_dir_with_permission "$ROOT_DIR/elasticsearch" 775
  create_dir_with_permission "$ROOT_DIR/postgresql" 775
  create_dir_with_permission "$ROOT_DIR/minio" 775
  create_dir_with_permission "$ROOT_DIR/redis" 775

  cp -rn "$DOCKER_ASSETS_DIR/volumes" "$ROOT_DIR"
  chmod -R 775 $ROOT_DIR/volumes
  echo "   📁 Directory $ROOT_DIR/volumes has been created and permissions set to 775."

  mkdir -p "$ROOT_DIR/volumes/db/data" "$ROOT_DIR/volumes/db/init"
  if [ -f "$SQL_DIR/supabase/init/data.sql" ]; then
    cp -f "$SQL_DIR/supabase/init/data.sql" "$ROOT_DIR/volumes/db/init/data.sql"
  fi
  chmod -R 775 "$ROOT_DIR/volumes/db"
  echo "   Supabase data directory initialized; SQL files are mounted from $SQL_DIR/supabase."

  # Copy sync_user_supabase2pg.py to ROOT_DIR for container access
  cp -rn "$DOCKER_ASSETS_DIR/scripts" "$ROOT_DIR"
  chmod 644 "$ROOT_DIR/scripts/sync_user_supabase2pg.py"
  echo "   📁 update scripts copied to $ROOT_DIR"

  # Create nexent user workspace directory
  NEXENT_USER_DIR="$HOME/nexent"
  create_dir_with_permission "$NEXENT_USER_DIR" 775
  echo "   🖥️  Nexent user workspace: $NEXENT_USER_DIR"

  # Copy official-skills-zip folder to /mnt/nexent
  if [ -d "$DOCKER_ASSETS_DIR/official-skills-zip" ]; then
    cp -rn "$DOCKER_ASSETS_DIR/official-skills-zip" "$NEXENT_USER_DIR/"
    chmod -R 775 "$NEXENT_USER_DIR/official-skills-zip"
    echo "   📦 Official skills copied to $NEXENT_USER_DIR/official-skills-zip"
  else
    echo "   ⚠️ official-skills-zip directory not found, skipping skills copy"
  fi

  # Export for docker-compose
  export NEXENT_USER_DIR

  echo ""
  echo "--------------------------------"
  echo ""
}

deploy_core_services() {
  # Function to deploy core services
  local core_services=()
  local service
  for service in $DEPLOYMENT_SELECTED_DOCKER_SERVICES; do
    case "$service" in
      nexent-config|nexent-runtime|nexent-mcp|nexent-northbound|nexent-web|nexent-data-process)
        core_services+=("$service")
        ;;
    esac
  done

  if [ ${#core_services[@]} -eq 0 ]; then
    echo "👀 No core services selected, skipping core service startup."
    return 0
  fi

  echo "👀 Starting core services: ${core_services[*]}"
  if ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" -p nexent -f "$COMPOSE_DIR/docker-compose${COMPOSE_FILE_SUFFIX}" up -d "${core_services[@]}"; then
    echo "   ❌ ERROR Failed to start core services"
    return 1
  fi
}

stop_unselected_data_process_service() {
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process" && return 0

  local compose_file="$COMPOSE_DIR/docker-compose${COMPOSE_FILE_SUFFIX}"
  [ -f "$compose_file" ] || return 0

  echo "data-process is not selected; stopping existing Docker container if present..."
  ${docker_compose_command} --env-file "$ROOT_ENV_FILE" -p nexent -f "$compose_file" stop nexent-data-process >/dev/null 2>&1 || true
  ${docker_compose_command} --env-file "$ROOT_ENV_FILE" -p nexent -f "$compose_file" rm -f nexent-data-process >/dev/null 2>&1 || true
}

deploy_infrastructure() {
  # Start infrastructure services (basic services only)
  echo "🔧 Starting infrastructure services..."
  INFRA_SERVICES=""

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "infrastructure"; then
    INFRA_SERVICES="nexent-elasticsearch nexent-postgresql nexent-minio redis"
  fi

  # Add openssh-server if Terminal tool container is enabled
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
    INFRA_SERVICES="$INFRA_SERVICES nexent-openssh-server"
    echo "🔧 Terminal tool container enabled - openssh-server will be included in infrastructure"
  fi

  if [ -n "$INFRA_SERVICES" ]; then
    if ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" -p nexent -f "$COMPOSE_DIR/docker-compose${COMPOSE_FILE_SUFFIX}" up -d $INFRA_SERVICES; then
      echo "   ❌ ERROR Failed to start infrastructure services"
      return 1
    fi
  else
    echo "🔧 No infrastructure services selected, skipping infrastructure startup."
  fi

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
    echo "🔧 Terminal tool container (openssh-server) is now available for AI agents"
  fi

  # Deploy Supabase services based on selected components
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
      echo ""
      echo "🔧 Starting Supabase services..."
      # Check if the supabase compose file exists
      if [ ! -f "$COMPOSE_DIR/docker-compose-supabase${COMPOSE_FILE_SUFFIX}" ]; then
          echo "   ❌ ERROR Supabase compose file not found: $COMPOSE_DIR/docker-compose-supabase${COMPOSE_FILE_SUFFIX}"
          return 1
      fi

      # Start Supabase services
      if ! $docker_compose_command --env-file "$ROOT_ENV_FILE" -p nexent -f "$COMPOSE_DIR/docker-compose-supabase${COMPOSE_FILE_SUFFIX}" up -d; then
          echo "   ❌ ERROR Failed to start supabase services"
          return 1
      fi

      echo "   ✅ Supabase services started successfully"
  else
      echo "   🚧 Skipping Supabase services..."
  fi

  echo "   ✅ Infrastructure services started successfully"
}

deploy_monitoring() {
  if ! deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    stop_monitoring_services || return 1
    return 0
  fi

  if [ ! -f "$COMPOSE_DIR/docker-compose-monitoring.yml" ]; then
    echo "   ❌ ERROR Monitoring compose file not found: $COMPOSE_DIR/docker-compose-monitoring.yml"
    return 1
  fi

  if [ "$DEPLOYMENT_MONITORING_PROVIDER" = "langsmith" ] && [ -z "${LANGSMITH_API_KEY:-}" ]; then
    echo "   ❌ ERROR LANGSMITH_API_KEY is required when --monitoring-provider langsmith is selected"
    return 1
  fi

  local profile_args=()
  case "$DEPLOYMENT_MONITORING_PROVIDER" in
    phoenix|grafana|zipkin|langfuse)
      profile_args+=(--profile "$DEPLOYMENT_MONITORING_PROVIDER")
      ;;
  esac

  echo "🔭 Starting monitoring services..."
  cleanup_stale_monitoring_services || return 1
  if ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" --env-file "$MONITORING_ENV_FILE" "${profile_args[@]}" -f "$COMPOSE_DIR/docker-compose-monitoring.yml" up -d; then
    echo "   ❌ ERROR Failed to start monitoring services"
    return 1
  fi
}

configure_root_dir_from_env() {
  if [ -n "$ROOT_DIR_PARAM" ]; then
    ROOT_DIR="$ROOT_DIR_PARAM"
    echo "   📁 Using ROOT_DIR from parameter: $ROOT_DIR"
    update_env_var "ROOT_DIR" "$ROOT_DIR"
  elif grep -q "^ROOT_DIR=" "$ROOT_ENV_FILE"; then
    ROOT_DIR="$(grep "^ROOT_DIR=" "$ROOT_ENV_FILE" | cut -d'=' -f2 | sed 's/^"//;s/"$//')"
    echo "   📁 Use existing ROOT_DIR path: $ROOT_DIR"
  else
    local default_root_dir="$HOME/nexent-data"
    if [ -t 0 ]; then
      local user_root_dir
      read -p "   📁 Enter ROOT_DIR path (default: $default_root_dir): " user_root_dir
      ROOT_DIR="${user_root_dir:-$default_root_dir}"
    else
      ROOT_DIR="$default_root_dir"
    fi
    update_env_var "ROOT_DIR" "$ROOT_DIR"
  fi
  export ROOT_DIR
  echo ""
  echo "--------------------------------"
  echo ""
}

apply_deployment_common_config() {
  deployment_prepare_config "${ORIGINAL_ARGS[@]}" || return 1

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
    export DEPLOYMENT_VERSION="full"
  else
    export DEPLOYMENT_VERSION="speed"
  fi
  update_env_var "DEPLOYMENT_VERSION" "$DEPLOYMENT_VERSION"

  if [ "$DEPLOYMENT_PORT_POLICY" = "production" ]; then
    export DEPLOYMENT_MODE="production"
    export COMPOSE_FILE_SUFFIX=".prod.yml"
    disable_dashboard
  elif [ "$DEPLOYMENT_COMPONENTS" = "infrastructure" ]; then
    export DEPLOYMENT_MODE="infrastructure"
    export COMPOSE_FILE_SUFFIX=".yml"
  else
    export DEPLOYMENT_MODE="development"
    export COMPOSE_FILE_SUFFIX=".yml"
  fi

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
    ENABLE_TERMINAL_SAVED="Y"
    export ENABLE_TERMINAL_TOOL_CONTAINER="true"
    export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}terminal"
  else
    ENABLE_TERMINAL_SAVED="N"
    export ENABLE_TERMINAL_TOOL_CONTAINER="false"
  fi

  export APP_VERSION="$DEPLOYMENT_APP_VERSION"
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
  deployment_render_docker_env "$SCRIPT_DIR/.env.generated"
  set -a
  source "$SCRIPT_DIR/.env.generated"
  set +a
  sync_monitoring_env_vars
  deployment_print_summary docker
}

select_deployment_version() {
  # Function to select deployment version
  echo "🚀 Please select deployment version:"
  echo "   1) ⚡️  Speed version - Lightweight deployment with essential features"
  echo "   2) 🎯  Full version - Full-featured deployment with all capabilities"
  if [ -n "$VERSION_CHOICE" ]; then
    version_choice="$VERSION_CHOICE"
    echo "👉 Using version_choice from argument: $version_choice"
  else
    read -p "👉 Enter your choice [1/2] (default: 1): " version_choice
  fi

  # Sanitize potential Windows CR in input
  version_choice=$(sanitize_input "$version_choice")
  VERSION_CHOICE_SAVED="${version_choice}"
  case $version_choice in
      2|"full")
          export DEPLOYMENT_VERSION="full"
          echo "✅ Selected complete version 🎯"
          ;;
      1|"speed"|*)
          export DEPLOYMENT_VERSION="speed"
          echo "✅ Selected speed version ⚡️"
          ;;
  esac

  update_env_var "DEPLOYMENT_VERSION" "$DEPLOYMENT_VERSION"

  echo ""
  echo "--------------------------------"
  echo ""
}

setup_package_install_script() {
  # Function to setup package installation script
  echo "📝 Setting up package installation script..."
  mkdir -p "openssh-server/config/custom-cont-init.d"

  # Copy the fixed installation script
  if [ -f "$SCRIPT_DIR/openssh-install-script.sh" ]; then
      cp "$SCRIPT_DIR/openssh-install-script.sh" "openssh-server/config/custom-cont-init.d/openssh-start-script"
      chmod +x "openssh-server/config/custom-cont-init.d/openssh-start-script"
      echo "   ✅ Package installation script created/updated"
  else
      echo "   ❌ ERROR openssh-install-script.sh not found"
      return 1
  fi
}

wait_for_elasticsearch_healthy() {
  # Function to wait for Elasticsearch to become healthy
  local retries=0
  local max_retries=${1:-60}  # Default 10 minutes, can be overridden
  while ! ${docker_compose_command} --env-file "$ROOT_ENV_FILE" -p nexent -f "$COMPOSE_DIR/docker-compose${COMPOSE_FILE_SUFFIX}" ps nexent-elasticsearch | grep -q "healthy" && [ $retries -lt $max_retries ]; do
      echo "⏳ Waiting for Elasticsearch to become healthy... (attempt $((retries + 1))/$max_retries)"
      sleep 10
      retries=$((retries + 1))
  done

  if [ $retries -eq $max_retries ]; then
      echo "   ⚠️  Warning: Elasticsearch did not become healthy within expected time"
      echo "     You may need to check the container logs and try again"
      return 0
  else
      echo "   ✅ Elasticsearch is now healthy!"
      return 0
  fi
}


select_terminal_tool() {
    # Function to ask if user wants to create Terminal tool container
    echo "🔧 Terminal Tool Container Setup:"
    echo "    Terminal tool allows AI agents to execute shell commands via SSH."
    echo "    This will create an openssh-server container for secure command execution."
    if [ -n "$ENABLE_TERMINAL" ]; then
        enable_terminal="$ENABLE_TERMINAL"
    else
        read -p "👉 Do you want to create Terminal tool container? [Y/N] (default: N): " enable_terminal
    fi

    # Sanitize potential Windows CR in input
    enable_terminal=$(sanitize_input "$enable_terminal")

    if [[ "$enable_terminal" =~ ^[Yy]$ ]]; then
        ENABLE_TERMINAL_SAVED="Y"
        export ENABLE_TERMINAL_TOOL_CONTAINER="true"
        export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}terminal"
        echo "✅ Terminal tool container will be created 🔧"
        echo "   🔧 Creating openssh-server container for secure command execution"

        # Ask user to specify directory mapping for container
        default_terminal_dir="/opt/terminal"
        echo "   📁 Terminal container directory mapping:"
        echo "      • Container path: /opt/terminal (fixed)"
        echo "      • Host path: You can specify any directory on your host machine"
        echo "      • Default host path: /opt/terminal (recommended)"
        echo ""
        read -p "   📁 Enter host directory to mount to container (default: /opt/terminal): " terminal_mount_dir
        terminal_mount_dir=$(sanitize_input "$terminal_mount_dir")
        TERMINAL_MOUNT_DIR="${terminal_mount_dir:-$default_terminal_dir}"
        TERMINAL_MOUNT_DIR_SAVED="$TERMINAL_MOUNT_DIR"

        # Save to environment variables
        export TERMINAL_MOUNT_DIR
        update_env_var "TERMINAL_MOUNT_DIR" "$TERMINAL_MOUNT_DIR"

        echo "   📁 Terminal mount configuration:"
        echo "      • Host: $TERMINAL_MOUNT_DIR"
        echo "      • Container: /opt/terminal"
        echo "      • This directory will be created if it doesn't exist"
        echo ""

        # Setup SSH credentials for Terminal tool container
        echo "🔐 Setting up SSH credentials for Terminal tool container..."

        # Check if SSH credentials are already set
        if [ -n "$SSH_USERNAME" ] && [ -n "$SSH_PASSWORD" ]; then
            echo "🚧 SSH credentials already configured, skipping setup..."
            echo "👤 Username: $SSH_USERNAME"
            echo "🔑 Password: [HIDDEN]"
        else
            # Prompt for SSH credentials
            echo "Please enter SSH credentials for Terminal tool container:"
            echo ""

            # Get SSH username
            if [ -z "$SSH_USERNAME" ]; then
                read -p "SSH Username (default: root): " input_username
                SSH_USERNAME=${input_username:-root}
            fi

            # Get SSH password
            if [ -z "$SSH_PASSWORD" ]; then
                echo "SSH Password (will be hidden): "
                read -s input_password
                echo ""
                if [ -z "$input_password" ]; then
                    echo "❌ SSH password cannot be empty"
                    return 1
                fi
                SSH_PASSWORD="$input_password"
            fi

            # Validate credentials
            if [ -z "$SSH_USERNAME" ] || [ -z "$SSH_PASSWORD" ]; then
                echo "❌ Both username and password are required"
                return 1
            fi

            # Export environment variables
            export SSH_USERNAME
            export SSH_PASSWORD

            # Add to .env file
            update_env_var "SSH_USERNAME" "$SSH_USERNAME"
            update_env_var "SSH_PASSWORD" "$SSH_PASSWORD"

            echo "   ✅ SSH credentials configured successfully!"
            echo "      👤 Username: $SSH_USERNAME"
            echo "      🔑 Password: [HIDDEN]"
            echo "      ⚙️  Authentication: Password-based"
        fi
        echo ""
    else
        ENABLE_TERMINAL_SAVED="N"
        export ENABLE_TERMINAL_TOOL_CONTAINER="false"
        echo "🚫 Terminal tool container disabled"
    fi
    echo ""
    echo "--------------------------------"
    echo ""
}

check_super_admin_user_exists() {
  # Check if super admin user exists in Supabase
  local email="${1:-suadmin@nexent.com}"
  local curl_container="nexent-config"

  # Determine which container to use for curl command
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ] || ! docker ps | grep -q "nexent-config"; then
    if docker ps | grep -q "supabase-db-mini"; then
      curl_container="supabase-db-mini"
    else
      echo "   ⚠️  Warning: Cannot check user existence - no suitable container available"
      return 2  # Unknown status
    fi
  fi

  # Try to query Supabase auth.users table directly (most reliable)
  if [ "$DEPLOYMENT_VERSION" = "full" ] && docker ps | grep -q "supabase-db-mini"; then
    local user_exists
    user_exists=$(docker exec supabase-db-mini psql -U postgres -d "$SUPABASE_POSTGRES_DB" -t -c "SELECT COUNT(*) FROM auth.users WHERE email = '${email}';" 2>/dev/null | tr -d '[:space:]')
    if [ "$user_exists" = "1" ]; then
      return 0  # User exists
    elif [ "$user_exists" = "0" ]; then
      return 1  # User does not exist
    fi
  fi

  # Fallback: Try to sign in with a dummy password to check if user exists
  # This is less reliable but works when database access is not available
  local test_response
  test_response=$(docker exec "$curl_container" bash -c "curl -s -X POST http://kong:8000/auth/v1/token?grant_type=password -H \"apikey: ${SUPABASE_KEY}\" -H \"Content-Type: application/json\" -d '{\"email\":\"${email}\",\"password\":\"dummy_password_check\"}'" 2>/dev/null)

  if echo "$test_response" | grep -q '"error_code":"invalid_credentials"'; then
    return 0  # User exists (wrong password means user exists)
  elif echo "$test_response" | grep -q '"error_code":"email_not_confirmed"'; then
    return 0  # User exists
  else
    return 1  # User likely does not exist
  fi
}

prompt_super_admin_password() {
  # Prompt user to enter password for super admin user with confirmation
  # Note: All prompts go to stderr, only password is returned via stdout
  local password=""
  local password_confirm=""
  local max_attempts=3
  local attempts=0

  echo "" >&2
  echo "🔐 Super Admin User Password Setup" >&2
  echo "   Email: suadmin@nexent.com" >&2
  echo "   Requirement: $(deployment_password_validation_message)" >&2
  echo "" >&2

  while [ $attempts -lt $max_attempts ]; do
    # First password input
    echo "   🔐 Please enter password for super admin user:" >&2
    read -s password
    echo "" >&2

    # Check if password is empty
    if [ -z "$password" ]; then
      echo "   ❌ Password cannot be empty. Please try again." >&2
      attempts=$((attempts + 1))
      continue
    fi

    if ! deployment_validate_password "$password"; then
      echo "   ❌ $(deployment_password_validation_message)" >&2
      attempts=$((attempts + 1))
      continue
    fi

    # Confirm password input
    echo "   🔐 Please confirm the password:" >&2
    read -s password_confirm
    echo "" >&2

    # Check if passwords match
    if [ "$password" != "$password_confirm" ]; then
      echo "   ❌ Passwords do not match. Please try again." >&2
      attempts=$((attempts + 1))
      continue
    fi

    # Passwords match, return the password via stdout
    echo "$password"
    return 0
  done

  # Max attempts reached
  echo "   ❌ Maximum attempts reached. Failed to set password." >&2
  return 1
}

create_default_super_admin_user() {
  # Call the dedicated script for creating super admin user
  local script_path="$SCRIPT_DIR/create-su.sh"
  local email="suadmin@nexent.com"

  if [ ! -f "$script_path" ]; then
    echo "   ❌ ERROR create-su.sh not found at $script_path"
    return 1
  fi

  # Make sure the script is executable
  chmod +x "$script_path"

  # Check if super admin user already exists
  echo ""
  echo "🔍 Checking if super admin user exists..."
  local check_result
  check_super_admin_user_exists
  check_result=$?

  if [ $check_result -eq 0 ]; then
    echo "   ✅ Super admin user (${email}) already exists."
    echo "   💡 Skipping user creation. If you need to reset the password, please do so manually."
    return 0
  elif [ $check_result -eq 1 ]; then
    echo "   ℹ️  Super admin user (${email}) does not exist. Proceeding with creation..."
  else
    echo "   ⚠️  Warning: Could not determine if user exists. Proceeding with creation..."
  fi

  # Prompt for password
  local password
  password="$(prompt_super_admin_password)"
  local prompt_result=$?

  if [ $prompt_result -ne 0 ] || [ -z "$password" ]; then
    echo "   ❌ Failed to get password from user."
    return 1
  fi

  # Export necessary environment variables for the script
  export SUPABASE_KEY
  export POSTGRES_USER
  export POSTGRES_DB
  export DEPLOYMENT_VERSION
  export SUPABASE_POSTGRES_DB
  export DEPLOYMENT_MODE

  # Execute the script with password as argument
  if bash "$script_path" "$password"; then
    unset password
    return 0
  else
    unset password
    return 1
  fi
}

choose_image_env() {
  if [ -n "$IS_MAINLAND" ]; then
    is_mainland="$IS_MAINLAND"
    echo "🌏 Using is_mainland from argument: $is_mainland"
  else
    read -p "🌏 Is your server network located in mainland China? [Y/N] (default N): " is_mainland
  fi

  # Sanitize potential Windows CR in input
  is_mainland=$(sanitize_input "$is_mainland")
  if [[ "$is_mainland" =~ ^[Yy]$ ]]; then
    IS_MAINLAND_SAVED="Y"
    echo "🌐 Detected mainland China network, using image-source.mainland.env for image sources."
    source "$DEPLOY_ROOT/env/image-source.mainland.env"
  else
    IS_MAINLAND_SAVED="N"
    echo "🌐 Using general image sources from image-source.general.env."
    source "$DEPLOY_ROOT/env/image-source.general.env"
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

main_deploy() {
  # Main deployment function
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "🚀 Nexent 部署脚本 🚀"
  else
    echo "🚀 Nexent Deployment Script 🚀"
  fi
  echo ""
  echo "--------------------------------"
  echo ""

  APP_VERSION="latest"
  if [ -z "$APP_VERSION" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 获取应用版本失败，请检查 VERSION 或 backend/consts/const.py"
    else
      echo "❌ Failed to get app version, please check VERSION or backend/consts/const.py"
    fi
    exit 1
  fi
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "🌐 应用版本：$APP_VERSION"
  else
    echo "🌐 App version: $APP_VERSION"
  fi

  # Select deployment components, port policy and image source via shared config.
  apply_deployment_common_config || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 部署配置失败"
    else
      echo "❌ Deployment configuration failed"
    fi
    exit 1
  }

  deployment_persist_local_config

  # Check only the ports published by the selected deployment configuration.
  check_deployment_ports

  configure_root_dir_from_env || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ ROOT_DIR 配置失败"
    else
      echo "❌ ROOT_DIR configuration failed"
    fi
    exit 1
  }

  # Set NEXENT_MCP_DOCKER_IMAGE in .env file
  if [ -n "${NEXENT_MCP_DOCKER_IMAGE:-}" ]; then
    update_env_var "NEXENT_MCP_DOCKER_IMAGE" "${NEXENT_MCP_DOCKER_IMAGE}"
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "🔧 NEXENT_MCP_DOCKER_IMAGE 已设置为：${NEXENT_MCP_DOCKER_IMAGE}"
    else
      echo "🔧 NEXENT_MCP_DOCKER_IMAGE set to: ${NEXENT_MCP_DOCKER_IMAGE}"
    fi
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "⚠️  环境中未找到 NEXENT_MCP_DOCKER_IMAGE，将使用代码默认值"
    else
      echo "⚠️  NEXENT_MCP_DOCKER_IMAGE not found in environment, will use default from code"
    fi
  fi

  # Add permission
  prepare_directory_and_data || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 权限设置失败"
    else
      echo "❌ Permission setup failed"
    fi
    exit 1
  }
  update_sql_files_checksum || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "ERROR SQL checksum 更新失败"
    else
      echo "ERROR SQL checksum update failed"
    fi
    exit 1
  }
  generate_minio_ak_sk || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ MinIO key 生成失败"
    else
      echo "❌ MinIO key generation failed"
    fi
    exit 1
  }


  # Generate Supabase secrets
  generate_supabase_keys || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ Supabase secrets 生成失败"
    else
      echo "❌ Supabase secrets generation failed"
    fi
    exit 1
  }

  # Deploy infrastructure services
  deploy_infrastructure || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 基础设施部署失败"
    else
      echo "❌ Infrastructure deployment failed"
    fi
    exit 1
  }

  deploy_monitoring || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 监控部署失败"
    else
      echo "❌ Monitoring deployment failed"
    fi
    exit 1
  }

  stop_unselected_data_process_service

  # Generate Elasticsearch API key
  generate_elasticsearch_api_key || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ Elasticsearch API key 生成失败"
    else
      echo "❌ Elasticsearch API key generation failed"
    fi
    exit 1
  }

  echo ""
  echo "--------------------------------"
  echo ""

  # Special handling for infrastructure mode
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ]; then
    generate_env_for_infrastructure || {
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "❌ 环境变量生成失败"
      else
        echo "❌ Environment generation failed"
      fi
      exit 1
    }

    # Create default super admin user (only for full version)
    if [ "$DEPLOYMENT_VERSION" = "full" ]; then
      create_default_super_admin_user || {
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "❌ 默认超级管理员创建失败"
        else
          echo "❌ Default super admin user creation failed"
        fi
        exit 1
      }
    fi

    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "🎉 基础设施部署完成！"
      echo "     现在可以使用 dev containers 手动启动核心服务"
      echo "     环境变量文件：$ROOT_ENV_FILE"
      echo "💡 在项目根目录执行 'source deploy/env/.env' 可加载环境变量"
    else
      echo "🎉 Infrastructure deployment completed successfully!"
      echo "     You can now start the core services manually using dev containers"
      echo "     Environment file available at: $ROOT_ENV_FILE"
      echo "💡 Use 'source deploy/env/.env' from the project root to load environment variables"
    fi

    # Pull MCP image for later use
    pull_mcp_image

    persist_deploy_options
    deployment_persist_local_config
    return 0
  fi

  # Start core services
  deploy_core_services || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 核心服务部署失败"
    else
      echo "❌ Core services deployment failed"
    fi
    exit 1
  }

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "   ✅ 核心服务启动成功"
  else
    echo "   ✅ Core services started successfully"
  fi
  echo ""
  echo "--------------------------------"
  echo ""

  # Create default super admin user
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    create_default_super_admin_user || {
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "❌ 默认超级管理员创建失败"
      else
        echo "❌ Default super admin user creation failed"
      fi
      exit 1
    }
  fi

  persist_deploy_options
  deployment_persist_local_config

  # Pull MCP image for later use
  pull_mcp_image

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "🎉  部署完成！"
    echo "🌐  现在可以访问应用：http://localhost:3000"
  else
    echo "🎉  Deployment completed successfully!"
    echo "🌐  You can now access the application at http://localhost:3000"
  fi
}

# get docker compose version
version_info=$(get_compose_version)
if [[ $version_info == "unknown" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "错误：未找到 Docker Compose 或版本检测失败"
    else
        echo "Error: Docker Compose not found or version detection failed"
    fi
    exit 1
fi

# extract version
version_type=$(echo "$version_info" | awk '{print $1}')
version_number=$(echo "$version_info" | awk '{print $2}')

# define docker compose command
docker_compose_command=""
case $version_type in
    "v1")
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "检测到 Docker Compose V1，版本：$version_number"
        else
            echo "Detected Docker Compose V1, version: $version_number"
        fi
        # The version 1.28.0 is the minimum requirement in Docker Compose v1 for default interpolation syntax.
        if [[ $version_number < "1.28.0" ]]; then
            if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
                echo "警告：V1 版本过旧，建议升级到 V2"
            else
                echo "Warning: V1 version is too old, consider upgrading to V2"
            fi
            exit 1
        fi
        docker_compose_command="docker-compose"
        ;;
    "v2")
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "检测到 Docker Compose V2，版本：$version_number"
        else
            echo "Detected Docker Compose V2, version: $version_number"
        fi
        docker_compose_command="docker compose"
        ;;
    *)
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "错误：未知 Docker Compose 版本类型。"
        else
            echo "Error: Unknown docker compose version type."
        fi
        exit 1
        ;;
esac

# Execute main deployment with error handling
if ! main_deploy; then
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "❌ 部署失败。请检查上面的错误信息后重试。"
  else
    echo "❌ Deployment failed. Please check the error messages above and try again."
  fi
  exit 1
fi

clean
