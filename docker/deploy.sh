#!/bin/bash

# Ensure the script is executed with bash (required for arrays and [[ ]])
if [ -z "$BASH_VERSION" ]; then
  echo "❌ This script must be run with bash. Please use: bash deploy.sh or ./deploy.sh"
  exit 1
fi

# Exit immediately if a command exits with a non-zero status
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONST_FILE="$PROJECT_ROOT/backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"

MODE_CHOICE_SAVED=""
VERSION_CHOICE_SAVED=""
IS_MAINLAND_SAVED=""
DOWNLOAD_MODELS="N"
ENABLE_TERMINAL_SAVED="N"
TERMINAL_MOUNT_DIR_SAVED="${TERMINAL_MOUNT_DIR:-}"
APP_VERSION=""

cd "$SCRIPT_DIR"

set -a
source .env

# Parse arg
MODE_CHOICE=""
IS_MAINLAND=""
ENABLE_TERMINAL=""
VERSION_CHOICE=""
ROOT_DIR_PARAM=""

# Suppress the orphan warning
export COMPOSE_IGNORE_ORPHANS=True

while [[ $# -gt 0 ]]; do
  case "$1" in
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

detect_os_type() {
  # Return: windows | mac | linux | unknown
  local os_name
  os_name=$(uname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')
  case "$os_name" in
    mingw*|msys*|cygwin*)
      echo "windows"
      ;;
    darwin*)
      echo "mac"
      ;;
    linux*)
      echo "linux"
      ;;
    *)
      echo "unknown"
      ;;
  esac
  return 0
}

format_path_for_env() {
  # Convert path to OS-specific format for .env values
  local input_path="$1"
  local os_type
  os_type=$(detect_os_type)

  if [[ "$os_type" = "windows" ]]; then
    if command -v cygpath >/dev/null 2>&1; then
      cygpath -w "$input_path"
      return 0
    fi

    if [[ "$input_path" =~ ^/([a-zA-Z])/(.*)$ ]]; then
      local drive="${BASH_REMATCH[1]}"
      local rest="${BASH_REMATCH[2]}"
      rest="${rest//\//\\}"
      printf "%s:\\%s" "$(echo "$drive" | tr '[:lower:]' '[:upper:]')" "$rest"
      return 0
    fi
  fi

  printf "%s" "$input_path"
}

escape_backslashes() {
  # Escape backslashes for safe writing into .env or JSON
  local input_path="$1"
  printf "%s" "$input_path" | sed 's/\\/\\\\/g'
  return 0
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

  # Always include the main .env if present, plus any .env.* files
  local env_files=()
  if [ -f ".env" ]; then
    env_files+=(".env")
  fi

  # Include additional env variants such as .env.general and .env.mainland
  local f
  for f in .env.*; do
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

  local idx
  for idx in "${!PORTS_TO_CHECK[@]}"; do
    local port="${PORTS_TO_CHECK[$idx]}"
    local source="${PORT_SOURCES[$idx]}"

    if is_port_in_use "$port"; then
      occupied_ports+=("$port")
      occupied_sources+=("$source")
      echo "   ❌ Port $port is already in use."
    else
      echo "   ✅ Port $port is free."
    fi
  done

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

trim_quotes() {
  local value="$1"
  value="${value%$'\r'}"
  value="${value%\"}"
  value="${value#\"}"
  echo "$value"
}

get_app_version() {
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
    echo "DOWNLOAD_MODELS=\"${DOWNLOAD_MODELS}\""
    echo "ENABLE_TERMINAL=\"${ENABLE_TERMINAL_SAVED}\""
    echo "TERMINAL_MOUNT_DIR=\"${TERMINAL_MOUNT_DIR_SAVED}\""
  } > "$DEPLOY_OPTIONS_FILE"
}

generate_minio_ak_sk() {
  echo "🔑 Generating MinIO keys..."

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
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    # Function to generate Supabase secrets
    echo "🔑 Generating Supabase keys..."

    # Generate fresh keys on every run for security
    export JWT_SECRET=$(openssl rand -base64 32 | tr -d '[:space:]')
    export SECRET_KEY_BASE=$(openssl rand -base64 64 | tr -d '[:space:]')
    export VAULT_ENC_KEY=$(openssl rand -base64 32 | tr -d '[:space:]')

    # Generate JWT-dependent keys using the new JWT_SECRET
    local anon_key=$(generate_jwt "anon")
    local service_role_key=$(generate_jwt "service_role")

    # Update or add all keys to the .env file
    update_env_var "JWT_SECRET" "$JWT_SECRET"
    update_env_var "SECRET_KEY_BASE" "$SECRET_KEY_BASE"
    update_env_var "VAULT_ENC_KEY" "$VAULT_ENC_KEY"
    update_env_var "SUPABASE_KEY" "$anon_key"
    update_env_var "SERVICE_ROLE_KEY" "$service_role_key"

    # Reload the environment variables from the updated .env file
    source .env
    echo "   ✅ Supabase keys generated successfully"
  fi
}


generate_elasticsearch_api_key() {
  # Function to generate Elasticsearch API key
  wait_for_elasticsearch_healthy || { echo "   ❌ Elasticsearch health check failed"; return 0; }

  # Generate API key
  echo "🔑 Generating ELASTICSEARCH_API_KEY..."
  API_KEY_JSON=$(docker exec nexent-elasticsearch curl -s -u "elastic:$ELASTIC_PASSWORD" "http://localhost:9200/_security/api_key" -H "Content-Type: application/json" -d '{"name":"my_api_key","role_descriptors":{"my_role":{"cluster":["all"],"index":[{"names":["*"],"privileges":["all"]}]}}}')

  # Extract API key and add to .env
  ELASTICSEARCH_API_KEY=$(echo "$API_KEY_JSON" | grep -o '"encoded":"[^"]*"' | awk -F'"' '{print $4}')
  echo "✅ ELASTICSEARCH_API_KEY Generated: $ELASTICSEARCH_API_KEY"
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    update_env_var "ELASTICSEARCH_API_KEY" "$ELASTICSEARCH_API_KEY"
  fi
}

generate_env_for_infrastructure() {
  # Function to generate complete environment file for infrastructure mode using generate_env.sh
  echo "🔑 Generating complete environment file in root directory..."
  echo "   🚀 Running generate_env.sh..."

  # Check if generate_env.sh exists
  if [ ! -f "generate_env.sh" ]; then
      echo "   ❌ ERROR generate_env.sh not found in docker directory"
      return 1
  fi

  # Make sure the script is executable and run it
  chmod +x generate_env.sh

  # Export DEPLOYMENT_VERSION to ensure generate_env.sh can access it
  export DEPLOYMENT_VERSION

  if ./generate_env.sh; then
      echo "   ✅ Environment file generated successfully for infrastructure mode!"
      # Source the generated .env file to make variables available
      if [ -f "../.env" ]; then
          echo "   ⏏️ Sourcing generated root .env file..."
          set -a
          source ../.env
          set +a
          echo "   ✅ Environment variables loaded from ../.env"
      else
          echo "   ⚠️  Warning: ../.env file not found after generation"
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
      if [[ $version_output =~ (v[0-9]+\.[0-9]+\.[0-9]+) ]]; then
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

pull_mcp_image() {
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
    if grep -q "^ROOT_DIR=" .env; then
      # Update existing ROOT_DIR in .env
      sed -i "s|^ROOT_DIR=.*|ROOT_DIR=\"$ROOT_DIR\"|" .env
    else
      # Add new ROOT_DIR to .env
      echo "# Root dir" >> .env
      echo "ROOT_DIR=\"$ROOT_DIR\"" >> .env
    fi
  elif grep -q "^ROOT_DIR=" .env; then
  # Check if ROOT_DIR already exists in .env (second priority)
    # Extract existing ROOT_DIR value from .env
    env_root_dir=$(grep "^ROOT_DIR=" .env | cut -d'=' -f2 | sed 's/^"//;s/"$//')
    ROOT_DIR="$env_root_dir"
    echo "   📁 Use existing ROOT_DIR path: $env_root_dir"

  else
  # Use default value and prompt user input (lowest priority)
    default_root_dir="$HOME/nexent-data"
    read -p "   📁 Enter ROOT_DIR path (default: $default_root_dir): " user_root_dir
    ROOT_DIR="${user_root_dir:-$default_root_dir}"

    echo "# Root dir" >> .env
    echo "ROOT_DIR=\"$ROOT_DIR\"" >> .env
  fi
  echo ""
  echo "--------------------------------"
  echo ""
}


# Model download selection
select_model_download() {
  echo ""

  local input_choice=""
  read -r -p "Do you want to download AI model files (table-transformer and yolox)? [Y/N] (default: N): " input_choice
  echo ""

  if [[ $input_choice =~ ^[Yy]$ ]]; then
    DOWNLOAD_MODELS="Y"
    echo "INFO: Model download will be performed."
  else
    DOWNLOAD_MODELS="N"
    echo "INFO: Skipping model download."
  fi
  echo "----------------------------------------"
  echo ""
  return 0
}

# kerry

download_and_config_models() {
  if [[ "$DOWNLOAD_MODELS" != "Y" ]]; then
    echo "INFO: Model download skipped by user choice."
    return 0
  fi

  echo "INFO: Downloading AI model files (this may take a while)..."

  local env_file_dir="$SCRIPT_DIR"
  local env_file_path="$env_file_dir/.env"
  local original_dir="$(pwd)"

  MODEL_ROOT="$ROOT_DIR/model"
  mkdir -p "$MODEL_ROOT"
  echo "INFO: Model directory: $MODEL_ROOT"

  export HF_ENDPOINT="https://hf-mirror.com"

  command -v git >/dev/null || { echo "ERROR: git is required but not found." >&2; return 1; }

  # ==========================================
  # 1. Table Transformer (table-structure recognition)
  echo "INFO: Downloading table-transformer-structure-recognition..."

  TT_MODEL_DIR_NAME="table-transformer-structure-recognition"
  TT_MODEL_DIR_PATH="$MODEL_ROOT/$TT_MODEL_DIR_NAME"
  MODEL_SAFETENSORS_FILE="model.safetensors"
  TT_MODEL_FILE_CHECK="$TT_MODEL_DIR_PATH/$MODEL_SAFETENSORS_FILE"

  cd "$MODEL_ROOT" || return 1

  if [[ -d "$TT_MODEL_DIR_PATH" ]] && [[ -f "$TT_MODEL_FILE_CHECK" ]]; then
      FILE_SIZE=$(stat -c%s "$TT_MODEL_FILE_CHECK" 2>/dev/null || stat -f%z "$TT_MODEL_FILE_CHECK" 2>/dev/null)
      if [[ "$FILE_SIZE" -gt 1000000 ]]; then
          echo "INFO: Table Transformer already exists."
      else
          echo "WARN: Existing model file looks incomplete, re-downloading..."
          rm -rf "$TT_MODEL_DIR_NAME"
      fi
  fi

  if [[ ! -f "$TT_MODEL_FILE_CHECK" ]]; then
      if [[ -d "$TT_MODEL_DIR_NAME" ]]; then
          echo "WARN: Removing existing directory before re-download..."
          rm -rf "$TT_MODEL_DIR_NAME"
      fi

      echo "INFO: Step 1/2: Clone repo (skip LFS files)..."
      if ! GIT_LFS_SKIP_SMUDGE=1 git clone "$HF_ENDPOINT/microsoft/$TT_MODEL_DIR_NAME" "$TT_MODEL_DIR_NAME"; then
          echo "ERROR: Failed to clone repository." >&2
          cd "$original_dir"
          return 1
      fi

      cd "$TT_MODEL_DIR_NAME" || return 1

      echo "INFO: Step 2/2: Download model.safetensors..."
      LARGE_FILE_URL="$HF_ENDPOINT/microsoft/$TT_MODEL_DIR_NAME/resolve/main/$MODEL_SAFETENSORS_FILE"

      if command -v curl &> /dev/null; then
          curl -L -o "$MODEL_SAFETENSORS_FILE" "$LARGE_FILE_URL" --progress-bar
      elif command -v wget &> /dev/null; then
          wget "$LARGE_FILE_URL" -O "$MODEL_SAFETENSORS_FILE"
      else
          echo "ERROR: curl or wget is required to download model files." >&2
          cd "$MODEL_ROOT"; rm -rf "$TT_MODEL_DIR_NAME"; cd "$original_dir"; return 1
      fi

      if [[ ! -f "$MODEL_SAFETENSORS_FILE" ]]; then
          echo "ERROR: $MODEL_SAFETENSORS_FILE download failed." >&2
          cd "$MODEL_ROOT"; rm -rf "$TT_MODEL_DIR_NAME"; cd "$original_dir"; return 1
      fi

      FILE_SIZE=$(stat -c%s "$MODEL_SAFETENSORS_FILE" 2>/dev/null || stat -f%z "$MODEL_SAFETENSORS_FILE" 2>/dev/null)
      if [[ "$FILE_SIZE" -lt 1000000 ]]; then
          echo "ERROR: $MODEL_SAFETENSORS_FILE seems too small (size: $FILE_SIZE bytes)." >&2
          cd "$MODEL_ROOT"; rm -rf "$TT_MODEL_DIR_NAME"; cd "$original_dir"; return 1
      fi

      echo "INFO: $MODEL_SAFETENSORS_FILE downloaded (size: $(du -h "$MODEL_SAFETENSORS_FILE" | cut -f1))"
      cd "$MODEL_ROOT"
  fi

  echo "INFO: Table Transformer OK"

  # ==========================================
  # 2. YOLOX (layout detection model)
  echo "INFO: Downloading yolox_l0.05.onnx"

  YOLOX_MODEL_FILE="$MODEL_ROOT/yolox_l0.05.onnx"
  MIN_YOLOX_SIZE=50000000

  NEED_DOWNLOAD=false

  if [[ -f "$YOLOX_MODEL_FILE" ]]; then
      CURRENT_SIZE=$(stat -c%s "$YOLOX_MODEL_FILE" 2>/dev/null || stat -f%z "$YOLOX_MODEL_FILE" 2>/dev/null)
      if [[ "$CURRENT_SIZE" -lt "$MIN_YOLOX_SIZE" ]]; then
          echo "WARN: Existing YOLOX file looks incomplete (size: $(numfmt --to=iec-i --suffix=B $CURRENT_SIZE 2>/dev/null || echo $CURRENT_SIZE)). Re-downloading..."
          NEED_DOWNLOAD=true
      else
          echo "INFO: YOLOX already exists."
      fi
  else
      NEED_DOWNLOAD=true
  fi

  if [[ "$NEED_DOWNLOAD" = true ]]; then
      ONNX_URL="$HF_ENDPOINT/unstructuredio/yolo_x_layout/resolve/main/yolox_l0.05.onnx"

      if command -v curl &> /dev/null; then
          echo "INFO: Downloading with curl (supports resume -C -)..."
          if curl -L -C - -o "$YOLOX_MODEL_FILE" "$ONNX_URL" --progress-bar; then
              echo "INFO: curl download completed"
          else
              echo "ERROR: curl download failed." >&2
              cd "$original_dir"
              return 1
          fi
      elif command -v wget &> /dev/null; then
          echo "INFO: Downloading with wget (supports resume -c)..."
          wget -c "$ONNX_URL" -O "$YOLOX_MODEL_FILE"
      else
          echo "ERROR: curl or wget is required to download model files." >&2
          cd "$original_dir"
          return 1
      fi

      if [[ -f "$YOLOX_MODEL_FILE" ]]; then
          FINAL_SIZE=$(stat -c%s "$YOLOX_MODEL_FILE" 2>/dev/null || stat -f%z "$YOLOX_MODEL_FILE" 2>/dev/null)
          if [[ "$FINAL_SIZE" -lt "$MIN_YOLOX_SIZE" ]]; then
              echo "ERROR: YOLOX file seems too small (size: $FINAL_SIZE bytes)." >&2
              cd "$original_dir"
              return 1
          else
              echo "INFO: YOLOX downloaded (size: $(numfmt --to=iec-i --suffix=B $FINAL_SIZE 2>/dev/null || echo $FINAL_SIZE))"
          fi
      else
          echo "ERROR: YOLOX download failed: file not found." >&2
          cd "$original_dir"
          return 1
      fi
  fi

  echo "INFO: YOLOX OK"

  # ==========================================
  # 3. config.json
  CONFIG_FILE="$MODEL_ROOT/config.json"
  YOLOX_ABS_PATH=$(cd "$(dirname "$YOLOX_MODEL_FILE")" && pwd)/$(basename "$YOLOX_MODEL_FILE")
  YOLOX_OS_PATH=$(format_path_for_env "$YOLOX_ABS_PATH")
  YOLOX_CONFIG_PATH=$(escape_backslashes "$YOLOX_OS_PATH")

  cat > "$CONFIG_FILE" <<EOF
{
    "model_path": "$YOLOX_CONFIG_PATH",
    "label_map": {
        "0": "Caption",
        "1": "Footnote",
        "2": "Formula",
        "3": "List-item",
        "4": "Page-footer",
        "5": "Page-header",
        "6": "Picture",
        "7": "Section-header",
        "8": "Table",
        "9": "Text",
        "10": "Title"
    }
}
EOF
  echo "INFO: config.json generated"

  # ==========================================
  # 4. Update .env
  cd "$env_file_dir" || return 1
  touch "$env_file_path"

  TT_MODEL_DIR_ABS_PATH=$(cd "$TT_MODEL_DIR_PATH" && pwd)
  CONFIG_FILE_ABS_PATH=$(cd "$(dirname "$CONFIG_FILE")" && pwd)/$(basename "$CONFIG_FILE")
  TT_MODEL_DIR_ENV_PATH=$(format_path_for_env "$TT_MODEL_DIR_ABS_PATH")
  CONFIG_FILE_ENV_PATH=$(format_path_for_env "$CONFIG_FILE_ABS_PATH")
  TT_MODEL_DIR_ENV_PATH=$(escape_backslashes "$TT_MODEL_DIR_ENV_PATH")
  CONFIG_FILE_ENV_PATH=$(escape_backslashes "$CONFIG_FILE_ENV_PATH")

  if declare -f update_env_var > /dev/null; then
      update_env_var "TABLE_TRANSFORMER_MODEL_PATH" "$TT_MODEL_DIR_ENV_PATH"
      update_env_var "UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH" "$CONFIG_FILE_ENV_PATH"
  else
      sed -i.bak "/^TABLE_TRANSFORMER_MODEL_PATH=/d" "$env_file_path" 2>/dev/null || true
      echo "TABLE_TRANSFORMER_MODEL_PATH="$TT_MODEL_DIR_ENV_PATH"" >> "$env_file_path"

      sed -i.bak "/^UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH=/d" "$env_file_path" 2>/dev/null || true
      echo "UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH="$CONFIG_FILE_ENV_PATH"" >> "$env_file_path"
      rm -f "$env_file_path.bak" 2>/dev/null
  fi

  echo "INFO: Environment file updated"
  cd "$original_dir"
}

clean() {
  export MINIO_ACCESS_KEY=
  export MINIO_SECRET_KEY=
  export DEPLOYMENT_MODE=
  export COMPOSE_FILE_SUFFIX=
  export DEPLOYMENT_VERSION=

  if [ -f ".env.bak" ]; then
    rm .env.bak
  fi
  if [ -f "../.env.bak" ]; then
    rm ../.env.bak
  fi
}

update_env_var() {
  # Function to update or add a key-value pair to .env
  local key="$1"
  local value="$2"
  local env_file=".env"

  # Ensure the .env file exists
  touch "$env_file"

  if grep -q "^${key}=" "$env_file"; then
    # Key exists, so update it. Escape \ and & for sed's replacement string.
    # Use ~ as the separator to avoid issues with / in the value.
    local escaped_value=$(echo "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')
    sed -i.bak "s~^${key}=.*~${key}=\"${escaped_value}\"~" "$env_file"
  else
    # Key doesn't exist, so add it
    echo "${key}=\"${value}\"" >> "$env_file"
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

prepare_directory_and_data() {
  # Initialize the sql script permission
  chmod 644 "init.sql"

  echo "🔧 Creating directory with permission..."
  create_dir_with_permission "$ROOT_DIR/elasticsearch" 775
  create_dir_with_permission "$ROOT_DIR/postgresql" 775
  create_dir_with_permission "$ROOT_DIR/minio" 775
  create_dir_with_permission "$ROOT_DIR/redis" 775

  echo "📦 Check the status of model configuration..."
  download_and_config_models || { 
    echo "⚠️  A warning occurred during the model configuration step, but subsequent deployment will proceed..." 
    # Do not exit here; the user may choose N or prefer to continue after a download failure.
  }
  echo ""

  cp -rn volumes $ROOT_DIR
  chmod -R 775 $ROOT_DIR/volumes
  echo "   📁 Directory $ROOT_DIR/volumes has been created and permissions set to 775."

  # Copy sync_user_supabase2pg.py to ROOT_DIR for container access
  cp -rn scripts $ROOT_DIR
  chmod 644 "$ROOT_DIR/scripts/sync_user_supabase2pg.py"
  echo "   📁 update scripts copied to $ROOT_DIR"

  # Create nexent user workspace directory
  NEXENT_USER_DIR="$HOME/nexent"
  create_dir_with_permission "$NEXENT_USER_DIR" 775
  echo "   🖥️  Nexent user workspace: $NEXENT_USER_DIR"

  # Export for docker-compose
  export NEXENT_USER_DIR

  echo ""
  echo "--------------------------------"
  echo ""
}

deploy_core_services() {
  # Function to deploy core services
  echo "👀 Starting core services..."
  if ! ${docker_compose_command} -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" up -d nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-web nexent-data-process; then
    echo "   ❌ ERROR Failed to start core services"
    return 1
  fi
}

deploy_infrastructure() {
  # Start infrastructure services (basic services only)
  echo "🔧 Starting infrastructure services..."
  INFRA_SERVICES="nexent-elasticsearch nexent-postgresql nexent-minio redis"

  # Add openssh-server if Terminal tool container is enabled
  if [ "$ENABLE_TERMINAL_TOOL_CONTAINER" = "true" ]; then
    INFRA_SERVICES="$INFRA_SERVICES nexent-openssh-server"
    echo "🔧 Terminal tool container enabled - openssh-server will be included in infrastructure"
  fi

  if ! ${docker_compose_command} -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" up -d $INFRA_SERVICES; then
    echo "   ❌ ERROR Failed to start infrastructure services"
    return 1
  fi

  if [ "$ENABLE_TERMINAL_TOOL_CONTAINER" = "true" ]; then
    echo "🔧 Terminal tool container (openssh-server) is now available for AI agents"
  fi

  # Deploy Supabase services based on DEPLOYMENT_VERSION
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
      echo ""
      echo "🔧 Starting Supabase services..."
      # Check if the supabase compose file exists
      if [ ! -f "docker-compose-supabase${COMPOSE_FILE_SUFFIX}" ]; then
          echo "   ❌ ERROR Supabase compose file not found: docker-compose-supabase${COMPOSE_FILE_SUFFIX}"
          return 1
      fi

      # Start Supabase services
      if ! $docker_compose_command -p nexent -f "docker-compose-supabase${COMPOSE_FILE_SUFFIX}" up -d; then
          echo "   ❌ ERROR Failed to start supabase services"
          return 1
      fi

      echo "   ✅ Supabase services started successfully"
  else
      echo "   🚧 Skipping Supabase services..."
  fi

  echo "   ✅ Infrastructure services started successfully"
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

  # Save the version choice to .env file
  local key="DEPLOYMENT_VERSION"
  local value="$DEPLOYMENT_VERSION"
  local env_file=".env"

  # Ensure the .env file exists
  touch "$env_file"

  if grep -q "^${key}=" "$env_file"; then
    # Key exists, so update it. Escape \ and & for sed's replacement string.
    # Use ~ as the separator to avoid issues with / in the value.
    local escaped_value=$(echo "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')
    sed -i.bak "s~^${key}=.*~${key}=\"${escaped_value}\"~" "$env_file"
  else
    # Key doesn't exist, so add it
    echo "${key}=\"${value}\"" >> "$env_file"
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

setup_package_install_script() {
  # Function to setup package installation script
  echo "📝 Setting up package installation script..."
  mkdir -p "openssh-server/config/custom-cont-init.d"

  # Copy the fixed installation script
  if [ -f "openssh-install-script.sh" ]; then
      cp "openssh-install-script.sh" "openssh-server/config/custom-cont-init.d/openssh-start-script"
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
  while ! ${docker_compose_command} -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" ps nexent-elasticsearch | grep -q "healthy" && [ $retries -lt $max_retries ]; do
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
  local email="suadmin@nexent.com"
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
    return 0
  else
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
    echo "🌐 Detected mainland China network, using .env.mainland for image sources."
    source .env.mainland
  else
    IS_MAINLAND_SAVED="N"
    echo "🌐 Using general image sources from .env.general."
    source .env.general
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

main_deploy() {
  # Main deployment function
  echo  "🚀 Nexent Deployment Script 🚀"
  echo ""
  echo "--------------------------------"
  echo ""

  APP_VERSION="$(get_app_version)"
  if [ -z "$APP_VERSION" ]; then
    echo "❌ Failed to get app version, please check the backend/consts/const.py file"
    exit 1
  fi
  echo "🌐 App version: $APP_VERSION"

  # Check all relevant ports from environment files before starting deployment
  check_ports_in_env_files

  # Select deployment version, mode and image source
  select_deployment_version || { echo "❌ Deployment version selection failed"; exit 1; }
  select_deployment_mode || { echo "❌ Deployment mode selection failed"; exit 1; }
  select_terminal_tool || { echo "❌ Terminal tool container configuration failed"; exit 1; }
  choose_image_env || { echo "❌ Image environment setup failed"; exit 1; }

  select_model_download || { echo "❌ Model download failed"; exit 1;}

  # Set NEXENT_MCP_DOCKER_IMAGE in .env file
  if [ -n "${NEXENT_MCP_DOCKER_IMAGE:-}" ]; then
    update_env_var "NEXENT_MCP_DOCKER_IMAGE" "${NEXENT_MCP_DOCKER_IMAGE}"
    echo "🔧 NEXENT_MCP_DOCKER_IMAGE set to: ${NEXENT_MCP_DOCKER_IMAGE}"
  else
    echo "⚠️  NEXENT_MCP_DOCKER_IMAGE not found in environment, will use default from code"
  fi

  # Add permission
  prepare_directory_and_data || { echo "❌ Permission setup failed"; exit 1; }
  generate_minio_ak_sk || { echo "❌ MinIO key generation failed"; exit 1; }


  # Generate Supabase secrets
  generate_supabase_keys || { echo "❌ Supabase secrets generation failed"; exit 1; }

  # Deploy infrastructure services
  deploy_infrastructure || { echo "❌ Infrastructure deployment failed"; exit 1; }

  # Generate Elasticsearch API key
  generate_elasticsearch_api_key || { echo "❌ Elasticsearch API key generation failed"; exit 1; }

  echo ""
  echo "--------------------------------"
  echo ""

  # Special handling for infrastructure mode
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ]; then
    generate_env_for_infrastructure || { echo "❌ Environment generation failed"; exit 1; }

    # Create default super admin user (only for full version)
    if [ "$DEPLOYMENT_VERSION" = "full" ]; then
      create_default_super_admin_user || { echo "❌ Default super admin user creation failed"; exit 1; }
    fi

    echo "🎉 Infrastructure deployment completed successfully!"
    echo "     You can now start the core services manually using dev containers"
    echo "     Environment file available at: $(cd .. && pwd)/.env"
    echo "💡 Use 'source .env' to load environment variables in your development shell"

    # Pull MCP image for later use
    pull_mcp_image

    persist_deploy_options
    return 0
  fi

  # Start core services
  deploy_core_services || { echo "❌ Core services deployment failed"; exit 1; }

  echo "   ✅ Core services started successfully"
  echo ""
  echo "--------------------------------"
  echo ""

  # Create default super admin user
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    create_default_super_admin_user || { echo "❌ Default super admin user creation failed"; exit 1; }
  fi

  persist_deploy_options

  # Pull MCP image for later use
  pull_mcp_image

  echo "🎉  Deployment completed successfully!"
  echo "🌐  You can now access the application at http://localhost:3000"
}

# get docker compose version
version_info=$(get_compose_version)
if [[ $version_info == "unknown" ]]; then
    echo "Error: Docker Compose not found or version detection failed"
    exit 1
fi

# extract version
version_type=$(echo "$version_info" | awk '{print $1}')
version_number=$(echo "$version_info" | awk '{print $2}')

# define docker compose command
docker_compose_command=""
case $version_type in
    "v1")
        echo "Detected Docker Compose V1, version: $version_number"
        # The version 1.28.0 is the minimum requirement in Docker Compose v1 for default interpolation syntax.
        if [[ $version_number < "1.28.0" ]]; then
            echo "Warning: V1 version is too old, consider upgrading to V2"
            exit 1
        fi
        docker_compose_command="docker-compose"
        ;;
    "v2")
        echo "Detected Docker Compose V2, version: $version_number"
        docker_compose_command="docker compose"
        ;;
    *)
        echo "Error: Unknown docker compose version type."
        exit 1
        ;;
esac

# Execute main deployment with error handling
if ! main_deploy; then
  echo "❌ Deployment failed. Please check the error messages above and try again."
  exit 1
fi

clean
