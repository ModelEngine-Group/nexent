#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy.sh"
SQL_DIR="$SCRIPT_DIR/sql"
ENV_FILE="$SCRIPT_DIR/.env"
V180_SCRIPT="$SCRIPT_DIR/scripts/v180_sync_user_metadata.sh"
V180_VERSION="1.8.0"

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
  local input_type="${4:-text}"  # Default to text type
  local input=""

  while true; do
    read -rp "${prompt_msg}: " input

    input="$(trim_quotes "$input")"

    # Handle yes/no type inputs
    if [[ "$input_type" == "boolean" ]]; then
      # Convert to uppercase for consistency
      input=$(echo "$input" | tr '[:lower:]' '[:upper:]')

      # Validate input
      if [[ "$input" =~ ^[YN]$ ]]; then
        DEPLOY_OPTIONS[$key]="$input"
        update_option_value "$key" "$input"
        break
      elif [ -z "$input" ] && [ -n "$default_value" ]; then
        # Use default value if input is empty
        DEPLOY_OPTIONS[$key]="$default_value"
        update_option_value "$key" "$default_value"
        break
      fi
    else
      # Handle other types of inputs
      if [ -n "$input" ]; then
        DEPLOY_OPTIONS[$key]="$input"
        update_option_value "$key" "$input"
        break
      elif [ -z "$input" ] && [ -n "$default_value" ]; then
        # Use default value if input is empty
        DEPLOY_OPTIONS[$key]="$default_value"
        update_option_value "$key" "$default_value"
        break
      fi
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

# Check if the upgrade version span includes v1.8.0
# Returns 0 (success) if span includes v1.8.0, 1 otherwise
check_version_spans_v180() {
  local cmp_with_v180
  local cmp_current

  # Check if current version is less than v1.8.0
  cmp_current="$(compare_versions "$CURRENT_APP_VERSION" "$V180_VERSION")"
  if [ "$cmp_current" -ge 0 ]; then
    # Current version is >= v1.8.0, no need to run v180 sync
    return 1
  fi

  # Check if target version is >= v1.8.0
  cmp_with_v180="$(compare_versions "$NEW_APP_VERSION" "$V180_VERSION")"
  if [ "$cmp_with_v180" -lt 0 ]; then
    # Target version is < v1.8.0, no need to run v180 sync
    return 1
  fi

  # Version span includes v1.8.0
  return 0
}

# Execute the v1.8.0 user metadata sync script
run_v180_sync_script() {
  if [ ! -f "$V180_SCRIPT" ]; then
    log "WARN" "⚠️  v180_sync_user_metadata.sh not found, skipping v1.8.0 metadata sync."
    return
  fi

  log "INFO" "🗄️  Detected version span includes v1.8.0, executing user metadata sync script..."

  if ! bash "$V180_SCRIPT"; then
    log "ERROR" "❌ Failed to execute v180_sync_user_metadata.sh, please verify the script."
    exit 1
  fi

  log "INFO" "✅ v1.8.0 user metadata sync completed successfully."
}


prompt_deploy_options() {
  # Only prompt for options that already exist in DEPLOY_OPTIONS
  if [[ -n "${DEPLOY_OPTIONS[VERSION_CHOICE]:-}" ]]; then
    echo "🚀 Please select deployment version:"
    echo "   1) ⚡️  Speed version - Lightweight deployment with essential features"
    echo "   2) 🎯  Full version - Full-featured deployment with all capabilities"
    prompt_option_value "VERSION_CHOICE" "Enter your choice [1/2] (default: ${DEPLOY_OPTIONS[VERSION_CHOICE]:-1})" "${DEPLOY_OPTIONS[VERSION_CHOICE]:-1}" "text"
  fi
  if [[ -n "${DEPLOY_OPTIONS[MODE_CHOICE]:-}" ]]; then
    echo "🎛️  Please select deployment mode:"
    echo "   1) 🛠️  Development mode - Expose all service ports for debugging"
    echo "   2) 🏗️  Infrastructure mode - Only start infrastructure services"
    echo "   3) 🚀 Production mode - Only expose port 3000 for security"
    prompt_option_value "MODE_CHOICE" "Enter your choice [1/2/3] (default: ${DEPLOY_OPTIONS[MODE_CHOICE]:-1})" "${DEPLOY_OPTIONS[MODE_CHOICE]:-1}" "text"
  fi
  if [[ -n "${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-}" ]]; then
    prompt_option_value "ENABLE_TERMINAL" "Do you want to create Terminal tool container? [Y/N] (default: ${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-N})" "${DEPLOY_OPTIONS[ENABLE_TERMINAL]:-N}" "boolean"
  fi
  if [[ -n "${DEPLOY_OPTIONS[IS_MAINLAND]:-}" ]]; then
    prompt_option_value "IS_MAINLAND" "Is your server network located in mainland China? [Y/N] (default: ${DEPLOY_OPTIONS[IS_MAINLAND]:-N})" "${DEPLOY_OPTIONS[IS_MAINLAND]:-N}" "boolean"
  fi
}

# Get friendly description for option keys
_get_option_description() {
  local key="$1"
  case "$key" in
    "MODE_CHOICE") echo "Deployment Mode" ;;
    "VERSION_CHOICE") echo "Deployment Version" ;;
    "IS_MAINLAND") echo "Mainland China Network" ;;
    "ENABLE_TERMINAL") echo "Terminal Tool Container" ;;
    "APP_VERSION") echo "Application Version" ;;
    "ROOT_DIR") echo "Root Directory" ;;
    *) echo "$key" ;;
  esac
}

# Get friendly value for option values
_get_option_value_description() {
  local key="$1"
  local value="$2"

  case "$key" in
    "MODE_CHOICE")
      case "$value" in
        "1") echo "1 - Development Mode" ;;
        "2") echo "2 - Infrastructure Mode" ;;
        "3") echo "3 - Production Mode" ;;
        *) echo "$value" ;;
      esac
      ;;
    "VERSION_CHOICE")
      case "$value" in
        "1") echo "1 - Speed Version" ;;
        "2") echo "2 - Full Version" ;;
        *) echo "$value" ;;
      esac
      ;;
    *) echo "$value" ;;
  esac
}

main() {
  ensure_docker
  load_options

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

  # Ask user if they want to inherit previous deployment options
  if [ -f "$OPTIONS_FILE" ] && [ -s "$OPTIONS_FILE" ]; then
    # Calculate maximum width of option descriptions for better alignment
    max_desc_width=0
    for key in "${!DEPLOY_OPTIONS[@]}"; do
      desc=$(_get_option_description "$key")
      desc_length=${#desc}
      if (( desc_length > max_desc_width )); then
        max_desc_width=$desc_length
      fi
    done

    # Ensure minimum width for better readability
    if (( max_desc_width < 20 )); then
      max_desc_width=20
    fi

    # Display current deployment options in a readable format
    log "INFO" "📋 Current deployment options:"
    echo ""
    for key in "${!DEPLOY_OPTIONS[@]}"; do
      value="${DEPLOY_OPTIONS[$key]}"
      desc=$(_get_option_description "$key")
      value_desc=$(_get_option_value_description "$key" "$value")
      printf "   • %-${max_desc_width}s : %s\n" "$desc" "$value_desc"
    done
    echo ""

    read -rp "🔄 Do you want to inherit previous deployment options? [Y/N] (default: Y): " inherit_choice
    inherit_choice="${inherit_choice:-Y}"
    inherit_choice="$(trim_quotes "$inherit_choice")"
    if [[ "$inherit_choice" =~ ^[Nn]$ ]]; then
      log "INFO" "📝 Starting configuration..."
      # Prompt for deployment options with existing values as defaults
      prompt_deploy_options
    fi
  fi

  build_deploy_args
  run_deploy

  # Check if version span includes v1.8.0 and run sync script if needed
  if check_version_spans_v180; then
    run_v180_sync_script
  fi

  collect_upgrade_sqls
  run_sql_scripts

  log "INFO" "🎉 Upgrade to ${NEW_APP_VERSION} completed, please verify service health."
}

main "$@"

