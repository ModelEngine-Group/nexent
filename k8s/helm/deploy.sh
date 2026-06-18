#!/bin/bash
# Helm Deployment Script for Nexent
# Usage: ./deploy.sh [apply] [options]
#
# Deploy only. Use uninstall.sh for uninstall and cleanup commands.

set -e

# Use absolute path relative to the script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$SCRIPT_DIR/nexent"
COMMON_VALUES="$CHART_DIR/charts/nexent-common/values.yaml"
NAMESPACE="nexent"
RELEASE_NAME="nexent"
DEPLOYMENT_COMMON="$(cd "$SCRIPT_DIR/../.." && pwd)/scripts/deployment/common.sh"

# Constants for deployment options
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONST_FILE="$PROJECT_ROOT/../backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
GENERATED_VALUES="$CHART_DIR/generated-values.yaml"
GENERATED_SECRETS_VALUES="$CHART_DIR/generated-secrets-values.yaml"

if [ -f "$DEPLOYMENT_COMMON" ]; then
    # shellcheck source=/dev/null
    source "$DEPLOYMENT_COMMON"
else
    echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON"
    exit 1
fi

# Global variables for deployment options
IS_MAINLAND=""
APP_VERSION=""
DEPLOYMENT_VERSION=""
VERSION_CHOICE_SAVED=""

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
    *)
      shift
      ;;
  esac
done

cd "$SCRIPT_DIR"

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
            source .env.mainland
            ;;
        general|local-latest)
            IS_MAINLAND_SAVED="N"
            source .env.general
            ;;
    esac

    deployment_apply_image_source
    deployment_render_helm_values "$GENERATED_VALUES"
    deployment_print_summary k8s
}

# Get APP_VERSION from backend/consts/const.py
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
    echo "Detected mainland China network, using .env.mainland for image sources."
    source .env.mainland
  else
    IS_MAINLAND_SAVED="N"
    echo "Using general image sources from .env.general."
    source .env.general
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
  echo "Generated Helm values: $GENERATED_VALUES"
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

# Generate Supabase secrets (only for full version)
generate_supabase_secrets() {
    if [ "$DEPLOYMENT_VERSION" != "full" ]; then
        echo "Skipping Supabase secrets generation (deployment version is speed)"
        return 0
    fi

    echo "=========================================="
    echo "  Supabase Secrets Generation"
    echo "=========================================="

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

restart_supabase_auth_services() {
    if ! deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
        return 0
    fi

    echo ""
    echo "Restarting Supabase auth services to pick up current secrets..."
    for svc in supabase-auth supabase-kong; do
        echo "  Restarting nexent-$svc..."
        kubectl rollout restart deployment/nexent-$svc -n "$NAMESPACE" 2>/dev/null || true
    done

    for svc in supabase-auth supabase-kong; do
        echo "  Waiting for nexent-$svc..."
        if kubectl rollout status deployment/nexent-$svc -n "$NAMESPACE" --timeout=300s >/dev/null 2>&1; then
            echo "  nexent-$svc is ready."
        else
            echo "  Warning: nexent-$svc did not become ready within timeout."
        fi
    done
}

restart_minio_for_current_secrets() {
    deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "infrastructure" || return 0

    echo ""
    echo "Restarting MinIO to ensure current credentials are loaded..."
    kubectl rollout restart deployment/nexent-minio -n "$NAMESPACE" 2>/dev/null || true
    if kubectl rollout status deployment/nexent-minio -n "$NAMESPACE" --timeout=300s >/dev/null 2>&1; then
        echo "  nexent-minio is ready."
    else
        echo "  Warning: nexent-minio did not become ready within timeout."
    fi
}

render_runtime_secret_values() {
    {
        echo "nexent-common:"
        echo "  secrets:"
        echo "    minio:"
        echo "      accessKey: \"$MINIO_ACCESS_KEY\""
        echo "      secretKey: \"$MINIO_SECRET_KEY\""
        if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
            echo "    supabase:"
            echo "      jwtSecret: \"$JWT_SECRET\""
            echo "      secretKeyBase: \"$SECRET_KEY_BASE\""
            echo "      vaultEncKey: \"$VAULT_ENC_KEY\""
            echo "      anonKey: \"$SUPABASE_ANON_KEY\""
            echo "      serviceRoleKey: \"$SUPABASE_SERVICE_ROLE_KEY\""
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
    if load_existing_minio_secrets; then
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
    echo "Deploying Helm chart..."
    helm upgrade --install nexent "$CHART_DIR" \
        --namespace "$NAMESPACE" \
        -f "$GENERATED_VALUES" \
        -f "$GENERATED_SECRETS_VALUES" \
        --set nexent-openssh.enabled="$ENABLE_OPENSSH" \
        --set nexent-common.secrets.ssh.username="$SSH_USERNAME" \
        --set nexent-common.secrets.ssh.password="$SSH_PASSWORD"

    restart_minio_for_current_secrets
    restart_supabase_auth_services

    # Step 9: Wait for Elasticsearch to be ready and initialize API key
    echo ""
    echo "=========================================="
    echo "  Elasticsearch Initialization"
    echo "=========================================="
    local deploy_success=true

    echo "Waiting for Elasticsearch pod to be ready..."
    sleep 5
    if kubectl wait --for=condition=ready pod -l app=nexent-elasticsearch -n $NAMESPACE --timeout=300s; then
        echo "Elasticsearch pod is ready."

        # Initialize Elasticsearch API key
        INIT_ES_SCRIPT="$SCRIPT_DIR/init-elasticsearch.sh"
        if [ -f "$INIT_ES_SCRIPT" ]; then
            echo "Running Elasticsearch initialization script..."
            if bash "$INIT_ES_SCRIPT"; then
                echo "Elasticsearch API key initialized successfully."

                # Restart backend services to pick up the new ES API key
                echo ""
                echo "Restarting backend services..."
                local backend_services="config runtime mcp northbound"
                deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process" && backend_services="$backend_services data-process"
                for svc in $backend_services; do
                    echo "  Restarting nexent-$svc..."
                    kubectl rollout restart deployment/nexent-$svc -n $NAMESPACE 2>/dev/null || true
                done

                # Wait for backend services to be ready
                echo ""
                echo "Waiting for backend services to be ready..."
                sleep 5
                for svc in $backend_services; do
                    echo "  Waiting for nexent-$svc..."
                    if kubectl wait --for=condition=ready pod -l app=nexent-$svc -n $NAMESPACE --timeout=300s 2>/dev/null; then
                        echo "  nexent-$svc is ready."
                    else
                        echo "  Error: nexent-$svc did not become ready within timeout."
                        deploy_success=false
                    fi
                done
            else
                echo "Error: Elasticsearch initialization script failed."
                deploy_success=false
            fi
        else
            echo "Error: init-elasticsearch.sh not found at $INIT_ES_SCRIPT"
            deploy_success=false
        fi
    else
        echo "Error: Elasticsearch pod did not become ready within timeout."
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
