#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy.sh"
SQL_DIR="$SCRIPT_DIR/sql"
ENV_FILE="$SCRIPT_DIR/.env"

declare -A DEPLOY_OPTIONS
UPGRADE_SQL_FILES=()

log() {
  local level="$1"
  shift
  printf "[%s] %s\n" "$level" "$*"
}

require_file() {
  local path="$1"
  local message="$2"
  if [ ! -f "$path" ]; then
    log "ERROR" "$message"
    exit 1
  fi
}

trim_quotes() {
  local value="$1"
  value="${value%$'\r'}"
  value="${value%\"}"
  value="${value#\"}"
  echo "$value"
}

load_options() {
  if [ ! -f "$OPTIONS_FILE" ]; then
    log "WARN" "⚙️  deploy.options not found, entering interactive configuration mode."
    : > "$OPTIONS_FILE"
    return
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[[:space:]]*([A-Za-z0-9_]+)[[:space:]]*=(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local raw_value="${BASH_REMATCH[2]}"
      raw_value="$(echo "$raw_value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
      DEPLOY_OPTIONS[$key]="$(trim_quotes "$raw_value")"
    fi
  done < "$OPTIONS_FILE"
}

prompt_option_value() {
  local key="$1"
  local prompt_msg="$2"
  local default_value="${3:-}"
  local input=""

  while true; do
    if [ -n "$default_value" ]; then
      read -rp "${prompt_msg} [${default_value}]: " input
      input="${input:-$default_value}"
    else
      read -rp "${prompt_msg}: " input
    fi

    input="$(trim_quotes "$input")"
    if [ -n "$input" ]; then
      DEPLOY_OPTIONS[$key]="$input"
      update_option_value "$key" "$input"
      break
    fi

    log "WARN" "⚠️  ${key} cannot be empty, please enter a value."
  done
}

require_option() {
  local key="$1"
  local prompt_msg="${2:-}"
  local value="${DEPLOY_OPTIONS[$key]:-}"
  if [ -z "$value" ]; then
    if [ -n "$prompt_msg" ]; then
      prompt_option_value "$key" "$prompt_msg"
    else
      log "ERROR" "❌ ${key} is missing in deploy.options, add it and rerun."
      exit 1
    fi
  fi
}

get_const_app_version() {
  require_file "$CONST_FILE" "backend/consts/const.py not found, unable to read the latest version."
  local line
  line=$(grep -E 'APP_VERSION' "$CONST_FILE" | tail -n 1 || true)
  line="${line##*=}"
  line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  trim_quotes "$line"
}

compare_versions() {
  local v1="${1#v}"
  local v2="${2#v}"
  IFS='.' read -r -a parts1 <<< "$v1"
  IFS='.' read -r -a parts2 <<< "$v2"
  local max_len="${#parts1[@]}"
  if [ "${#parts2[@]}" -gt "$max_len" ]; then
    max_len="${#parts2[@]}"
  fi
  for ((i=0; i<max_len; i++)); do
    local num1="${parts1[i]:-0}"
    local num2="${parts2[i]:-0}"
    ((10#$num1 > 10#$num2)) && { echo 1; return; }
    ((10#$num1 < 10#$num2)) && { echo -1; return; }
  done
  echo 0
}

collect_upgrade_sqls() {
  if [ ! -d "$SQL_DIR" ]; then
    log "WARN" "📭 SQL directory not found, skipping database upgrade scripts."
    return
  fi

  mapfile -t sql_files < <(find "$SQL_DIR" -maxdepth 1 -type f -name "v*.sql" -print | sort -V || true)
  if [ "${#sql_files[@]}" -eq 0 ]; then
    return
  fi

  for file in "${sql_files[@]}"; do
    local base version_prefix
    base="$(basename "$file")"
    version_prefix="${base%%_*}"
    [[ -z "$version_prefix" ]] && continue

    local cmp_current
    cmp_current="$(compare_versions "$version_prefix" "$CURRENT_APP_VERSION")"

    if [ "$cmp_current" -eq 1 ]; then
      UPGRADE_SQL_FILES+=("$file")
    fi
  done
}

build_deploy_args() {
  DEPLOY_ARGS=()
  local mode="${DEPLOY_OPTIONS[MODE_CHOICE]:-}"
  local version_choice="${DEPLOY_OPTIONS[VERSION_CHOICE]:-}"
  local is_mainland="${DEPLOY_OPTIONS[IS_MAINLAND]:-}"
  local enable_terminal="${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-}"
  local root_dir="${DEPLOY_OPTIONS[ROOT_DIR]:-}"

  [[ -n "$mode" ]] && DEPLOY_ARGS+=(--mode "$mode")
  [[ -n "$version_choice" ]] && DEPLOY_ARGS+=(--version "$version_choice")
  [[ -n "$is_mainland" ]] && DEPLOY_ARGS+=(--is-mainland "$is_mainland")
  [[ -n "$enable_terminal" ]] && DEPLOY_ARGS+=(--enable-terminal "$enable_terminal")
  [[ -n "$root_dir" ]] && DEPLOY_ARGS+=(--root-dir "$root_dir")
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    log "ERROR" "🛑 Docker CLI not detected, install Docker before continuing."
    exit 1
  fi
}

ensure_postgres_env() {
  require_file "$ENV_FILE" "📁 docker/.env not found; unable to load database credentials."
  set -a
  source "$ENV_FILE"
  set +a
  : "${POSTGRES_USER:?docker/.env is missing POSTGRES_USER}"
  : "${POSTGRES_DB:?docker/.env is missing POSTGRES_DB}"
}

run_deploy() {
  # Stop and remove any existing containers before redeployment
  docker compose -p nexent down -v
  log "INFO" "🚀 Starting deploy..."
  (cd "$SCRIPT_DIR" && cp .env.example .env && bash "$DEPLOY_SCRIPT" "${DEPLOY_ARGS[@]}")

}

run_sql_scripts() {
  if [ "${#UPGRADE_SQL_FILES[@]}" -eq 0 ]; then
    log "INFO" "📭 No database upgrade scripts detected, skipping this step."
    return
  fi

  ensure_postgres_env

  for sql_file in "${UPGRADE_SQL_FILES[@]}"; do
    log "INFO" "🗃️  Running database upgrade script $(basename "$sql_file") ..."
    if ! docker exec -i nexent-postgresql psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < "$sql_file"; then
      log "ERROR" "❌ Failed to execute $(basename "$sql_file"), please verify the script."
      exit 1
    fi
  done
}

update_option_value() {
  local key="$1"
  local value="$2"
  touch "$OPTIONS_FILE"
  if grep -q "^${key}[[:space:]]*=" "$OPTIONS_FILE"; then
    sed -i.bak -E "s|^(${key}[[:space:]]*=[[:space:]]*)\"?[^\"]*\"?|\1\"${value}\"|" "$OPTIONS_FILE"
  else
    echo "${key} = \"${value}\"" >> "$OPTIONS_FILE"
  fi
}


prompt_deploy_options() {
  # Only prompt for options that already exist in DEPLOY_OPTIONS
  if [[ -n "${DEPLOY_OPTIONS[MODE_CHOICE]:-}" ]]; then
    echo "🎛️  Please select deployment mode:"
    echo "   1) 🛠️  Development mode - Expose all service ports for debugging"
    echo "   2) 🏗️  Infrastructure mode - Only start infrastructure services"
    echo "   3) 🚀 Production mode - Only expose port 3000 for security"
    prompt_option_value "MODE_CHOICE" "Please select deployment mode [1/2/3]" "${DEPLOY_OPTIONS[MODE_CHOICE]:-}"
  fi
  if [[ -n "${DEPLOY_OPTIONS[VERSION_CHOICE]:-}" ]]; then
    echo "🚀 Please select deployment version:"
    echo "   1) ⚡️  Speed version - Lightweight deployment with essential features"
    echo "   2) 🎯  Full version - Full-featured deployment with all capabilities"
    prompt_option_value "VERSION_CHOICE" "Please select deployment version [1/2]" "${DEPLOY_OPTIONS[VERSION_CHOICE]:-}"
  fi
  if [[ -n "${DEPLOY_OPTIONS[IS_MAINLAND]:-}" ]]; then
    prompt_option_value "IS_MAINLAND" "Is your server network located in mainland China? (yes/no)" "${DEPLOY_OPTIONS[IS_MAINLAND]:-}"
  fi
  if [[ -n "${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-}" ]]; then
    prompt_option_value "ENABLE_TERMINAL" "Do you want to create Terminal tool container? (yes/no)" "${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-}"
  fi
}

main() {
  ensure_docker
  load_options

  # Ask user if they want to inherit previous deployment options
  if [ -f "$OPTIONS_FILE" ] && [ -s "$OPTIONS_FILE" ]; then
    # Display current deployment options in a readable format
    log "INFO" "📋 Current deployment options:"
    echo "   ┌───────────────────────────────────────────┐"
    for key in "${!DEPLOY_OPTIONS[@]}"; do
      value="${DEPLOY_OPTIONS[$key]}"
      printf "   │ %-25s : %-20s │\n" "$key" "$value"
    done
    echo "   └───────────────────────────────────────────┘"
    echo ""
    
    read -rp "🔄 Do you want to inherit previous deployment options? (yes/no) [yes]: " inherit_choice
    inherit_choice="${inherit_choice:-yes}"
    inherit_choice="$(trim_quotes "$inherit_choice")"
    
    if [ "$inherit_choice" != "yes" ]; then
      log "INFO" "📝 Starting configuration with previous defaults..."
      # Prompt for deployment options with existing values as defaults
      prompt_deploy_options
    fi
  fi
  
  # Ensure required options are present
  require_option "APP_VERSION" "APP_VERSION not detected, please enter the current deployed version"
  require_option "ROOT_DIR" "ROOT_DIR not detected, please enter the absolute deployment directory path"
  CURRENT_APP_VERSION="${DEPLOY_OPTIONS[APP_VERSION]:-}"

  NEW_APP_VERSION="$(get_const_app_version)"
  if [ -z "$NEW_APP_VERSION" ]; then
    log "ERROR" "❌ Unable to parse APP_VERSION from const.py, please verify the file."
    exit 1
  fi

  log "INFO" "📦 Current version: $CURRENT_APP_VERSION"
  log "INFO" "🎯 Target version: $NEW_APP_VERSION"

  local cmp_result
  cmp_result="$(compare_versions "$NEW_APP_VERSION" "$CURRENT_APP_VERSION")"
  if [ "$cmp_result" -le 0 ]; then
    log "INFO" "🚫 Target version ($NEW_APP_VERSION) is not higher than current version ($CURRENT_APP_VERSION), upgrade aborted."
    exit 1
  fi

  build_deploy_args
  run_deploy
  collect_upgrade_sqls
  run_sql_scripts

  log "INFO" "🎉 Upgrade to ${NEW_APP_VERSION} completed, please verify service health."
}

main "$@"

