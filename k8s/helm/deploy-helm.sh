#!/bin/bash
# Helm Deployment Script for Nexent
# Usage: ./deploy-helm.sh [apply|delete|delete-all|clean]
#
# Commands:
#   apply    - Deploy all K8s resources using Helm
#   delete   - Delete resources but PRESERVE data (PVC/PV)
#   delete-all - Delete ALL resources including data
#   clean    - Clean helm state only (for fixing stuck releases)

set -e

# Use absolute path relative to the script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$SCRIPT_DIR/nexent"
NAMESPACE="nexent"
RELEASE_NAME="nexent"

# Constants for deployment options
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONST_FILE="$PROJECT_ROOT/../backend/consts/const.py"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/.deploy.options"

# Global variables for deployment options
IS_MAINLAND=""
APP_VERSION=""
DEPLOYMENT_VERSION=""
VERSION_CHOICE_SAVED=""

# Parse command line arguments
# First argument is the command
COMMAND="$1"
shift

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

# Update image tags in values.yaml based on loaded environment variables
update_values_yaml() {
  echo "=========================================="
  echo "  Updating Image Tags in values.yaml"
  echo "=========================================="

  # Get APP_VERSION if not already set
  if [ -z "$APP_VERSION" ]; then
    APP_VERSION="latest"
  fi

  if [ -z "$APP_VERSION" ]; then
    echo "Failed to determine APP_VERSION from const.py, using 'latest'"
    APP_VERSION="latest"
  fi
  echo "Using APP_VERSION: $APP_VERSION"
  echo ""

  # Echo all image updates
  echo "Backend image:"
  echo "  Repository: ${NEXENT_IMAGE%%:*}"
  echo "  Tag: $APP_VERSION"
  echo ""
  echo "Web image:"
  echo "  Repository: ${NEXENT_WEB_IMAGE%%:*}"
  echo "  Tag: $APP_VERSION"
  echo ""
  echo "Data process image:"
  echo "  Repository: ${NEXENT_DATA_PROCESS_IMAGE%%:*}"
  echo "  Tag: $APP_VERSION"
  echo ""
  echo "OpenSSH server image:"
  echo "  Repository: ${OPENSSH_SERVER_IMAGE%%:*}"
  echo "  Tag: $APP_VERSION"
  echo ""
  echo "Elasticsearch image:"
  echo "  Repository: ${ELASTICSEARCH_IMAGE%%:*}"
  echo "  Tag: ${ELASTICSEARCH_IMAGE##*:}"
  echo ""
  echo "PostgreSQL image:"
  echo "  Repository: ${POSTGRESQL_IMAGE%%:*}"
  echo "  Tag: ${POSTGRESQL_IMAGE##*:}"
  echo ""
  echo "Redis image:"
  echo "  Repository: ${REDIS_IMAGE%%:*}"
  echo "  Tag: ${REDIS_IMAGE##*:}"
  echo ""
  echo "MinIO image:"
  echo "  Repository: ${MINIO_IMAGE%%:*}"
  echo "  Tag: ${MINIO_IMAGE##*:}"
  echo ""

  # Supabase images (only for full version)
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    echo "Supabase Kong image:"
    echo "  Repository: ${SUPABASE_KONG%%:*}"
    echo "  Tag: ${SUPABASE_KONG##*:}"
    echo ""
    echo "Supabase Gotrue image:"
    echo "  Repository: ${SUPABASE_GOTRUE%%:*}"
    echo "  Tag: ${SUPABASE_GOTRUE##*:}"
    echo ""
    echo "Supabase DB image:"
    echo "  Repository: ${SUPABASE_DB%%:*}"
    echo "  Tag: ${SUPABASE_DB##*:}"
    echo ""
  fi

  # Update backend image
  sed -i "/^  backend:/,/^  [a-z]/{s|    repository:.*|    repository: \"${NEXENT_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  backend:/,/^  [a-z]/{s|    tag:.*|    tag: \"$APP_VERSION\"|}" "$CHART_DIR/values.yaml"

  # Update web image
  sed -i "/^  web:/,/^  [a-z]/{s|    repository:.*|    repository: \"${NEXENT_WEB_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  web:/,/^  [a-z]/{s|    tag:.*|    tag: \"$APP_VERSION\"|}" "$CHART_DIR/values.yaml"

  # Update dataProcess image
  sed -i "/^  dataProcess:/,/^  [a-z]/{s|    repository:.*|    repository: \"${NEXENT_DATA_PROCESS_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  dataProcess:/,/^  [a-z]/{s|    tag:.*|    tag: \"$APP_VERSION\"|}" "$CHART_DIR/values.yaml"

  # Update elasticsearch image
  sed -i "/^  elasticsearch:/,/^  [a-z]/{s|    repository:.*|    repository: \"${ELASTICSEARCH_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  elasticsearch:/,/^  [a-z]/{s|    tag:.*|    tag: \"${ELASTICSEARCH_IMAGE##*:}\"|}" "$CHART_DIR/values.yaml"

  # Update postgresql image
  sed -i "/^  postgresql:/,/^  [a-z]/{s|    repository:.*|    repository: \"${POSTGRESQL_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  postgresql:/,/^  [a-z]/{s|    tag:.*|    tag: \"${POSTGRESQL_IMAGE##*:}\"|}" "$CHART_DIR/values.yaml"

  # Update redis image
  sed -i "/^  redis:/,/^  [a-z]/{s|    repository:.*|    repository: \"${REDIS_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  redis:/,/^  [a-z]/{s|    tag:.*|    tag: \"${REDIS_IMAGE##*:}\"|}" "$CHART_DIR/values.yaml"

  # Update minio image
  sed -i "/^  minio:/,/^  [a-z]/{s|    repository:.*|    repository: \"${MINIO_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  minio:/,/^  [a-z]/{s|    tag:.*|    tag: \"${MINIO_IMAGE##*:}\"|}" "$CHART_DIR/values.yaml"

  # Update Supabase images using grep to find exact line numbers
  # Only for full version
  if [ "$DEPLOYMENT_VERSION" = "full" ] && grep -q "^  supabase:" "$CHART_DIR/values.yaml"; then
    # Find line numbers for each field dynamically
    KONG_REPO_LINE=$(grep -n '    kong:' "$CHART_DIR/values.yaml" | head -1 | cut -d: -f1)
    KONG_REPO_LINE=$((KONG_REPO_LINE + 1))
    KONG_TAG_LINE=$((KONG_REPO_LINE + 1))

    GOTRUE_REPO_LINE=$(grep -n '    gotrue:' "$CHART_DIR/values.yaml" | head -1 | cut -d: -f1)
    GOTRUE_REPO_LINE=$((GOTRUE_REPO_LINE + 1))
    GOTRUE_TAG_LINE=$((GOTRUE_REPO_LINE + 1))

    POSTGRES_REPO_LINE=$(grep -n '    postgres:' "$CHART_DIR/values.yaml" | head -1 | cut -d: -f1)
    POSTGRES_REPO_LINE=$((POSTGRES_REPO_LINE + 1))
    POSTGRES_TAG_LINE=$((POSTGRES_REPO_LINE + 1))

    # Update supabase.kong
    sed -i "${KONG_REPO_LINE}s|.*|      repository: \"${SUPABASE_KONG%%:*}\"|" "$CHART_DIR/values.yaml"
    sed -i "${KONG_TAG_LINE}s|.*|      tag: \"${SUPABASE_KONG##*:}\"|" "$CHART_DIR/values.yaml"

    # Update supabase.gotrue
    sed -i "${GOTRUE_REPO_LINE}s|.*|      repository: \"${SUPABASE_GOTRUE%%:*}\"|" "$CHART_DIR/values.yaml"
    sed -i "${GOTRUE_TAG_LINE}s|.*|      tag: \"${SUPABASE_GOTRUE##*:}\"|" "$CHART_DIR/values.yaml"

    # Update supabase.postgres
    sed -i "${POSTGRES_REPO_LINE}s|.*|      repository: \"${SUPABASE_DB%%:*}\"|" "$CHART_DIR/values.yaml"
    sed -i "${POSTGRES_TAG_LINE}s|.*|      tag: \"${SUPABASE_DB##*:}\"|" "$CHART_DIR/values.yaml"
  fi

  # Update openssh image
  sed -i "/^  openssh:/{s|    repository:.*|    repository: \"${OPENSSH_SERVER_IMAGE%%:*}\"|}" "$CHART_DIR/values.yaml"
  sed -i "/^  openssh:/{s|    tag:.*|    tag: \"$APP_VERSION\"|}" "$CHART_DIR/values.yaml"

  echo "Image tags updated in values.yaml"
  echo ""
  echo "--------------------------------"
  echo ""
}

# Function to clean helm state without deleting data
clean_helm_state() {
    echo "Cleaning Helm release state..."
    helm uninstall $RELEASE_NAME -n $NAMESPACE --no-hooks 2>/dev/null || true
    kubectl delete secret -n $NAMESPACE -l "owner=helm" --ignore-not-found=true 2>/dev/null || true
    kubectl delete secret -n $NAMESPACE --field-selector type=helm.sh/release.v1 --ignore-not-found=true 2>/dev/null || true
    kubectl delete secret -n $NAMESPACE -l "name=$RELEASE_NAME" --ignore-not-found=true 2>/dev/null || true
    echo "Helm state cleaned!"
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

    # Update values.yaml with deployment version
    sed -i "s/^deploymentVersion:.*/deploymentVersion: \"$DEPLOYMENT_VERSION\"/" "$CHART_DIR/values.yaml"

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

# Generate Supabase secrets (only for full version)
generate_supabase_secrets() {
    if [ "$DEPLOYMENT_VERSION" != "full" ]; then
        echo "Skipping Supabase secrets generation (deployment version is speed)"
        return 0
    fi

    echo "=========================================="
    echo "  Supabase Secrets Generation"
    echo "=========================================="

    # Generate fresh keys for security
    JWT_SECRET=$(openssl rand -base64 32 | tr -d '[:space:]')
    SECRET_KEY_BASE=$(openssl rand -base64 64 | tr -d '[:space:]')
    VAULT_ENC_KEY=$(openssl rand -base64 32 | tr -d '[:space:]')

    # Generate JWT-dependent keys
    local anon_key=$(generate_jwt "anon")
    local service_role_key=$(generate_jwt "service_role")

    # Write to values.yaml
    echo "Updating Supabase secrets in values.yaml..."

    # Update secrets.supabase.jwtSecret
    if grep -q "jwtSecret:" "$CHART_DIR/values.yaml"; then
        sed -i "s|jwtSecret:.*|jwtSecret: \"$JWT_SECRET\"|" "$CHART_DIR/values.yaml"
    fi

    # Update secrets.supabase.secretKeyBase
    if grep -q "secretKeyBase:" "$CHART_DIR/values.yaml"; then
        sed -i "s|secretKeyBase:.*|secretKeyBase: \"$SECRET_KEY_BASE\"|" "$CHART_DIR/values.yaml"
    fi

    # Update secrets.supabase.vaultEncKey
    if grep -q "vaultEncKey:" "$CHART_DIR/values.yaml"; then
        sed -i "s|vaultEncKey:.*|vaultEncKey: \"$VAULT_ENC_KEY\"|" "$CHART_DIR/values.yaml"
    fi

    # Update secrets.supabase.anonKey
    if grep -q "anonKey:" "$CHART_DIR/values.yaml"; then
        sed -i "s|anonKey:.*|anonKey: \"$anon_key\"|" "$CHART_DIR/values.yaml"
    fi

    # Update secrets.supabase.serviceRoleKey
    if grep -q "serviceRoleKey:" "$CHART_DIR/values.yaml"; then
        sed -i "s|serviceRoleKey:.*|serviceRoleKey: \"$service_role_key\"|" "$CHART_DIR/values.yaml"
    fi

    echo "Supabase secrets generated and saved to values.yaml"
    echo ""
    echo "--------------------------------"
    echo ""
}

apply() {
    echo "Deploying Nexent using Helm..."

    # Step 1: Select deployment version (speed or full)
    select_deployment_version

    # Step 2: Select image source environment (mainland China or general)
    choose_image_env

    # Step 3: Update values.yaml with image tags from selected environment
    update_values_yaml

    # Step 4: Generate MinIO Access Key and Secret Key
    echo "=========================================="
    echo "  MinIO Access Key/Secret Key Setup"
    echo "=========================================="
    if grep -q "minio:" "$CHART_DIR/values.yaml" && grep -q "accessKey:" "$CHART_DIR/values.yaml"; then
        MINIO_ACCESS_KEY=$(grep "accessKey:" "$CHART_DIR/values.yaml" | head -1 | sed 's/.*accessKey: *//' | tr -d '"' | tr -d "'" | xargs)
        MINIO_SECRET_KEY=$(grep "secretKey:" "$CHART_DIR/values.yaml" | head -1 | sed 's/.*secretKey: *//' | tr -d '"' | tr -d "'" | xargs)
    fi

    if [ -z "$MINIO_ACCESS_KEY" ] || [ "$MINIO_ACCESS_KEY" = "" ]; then
        echo "Generating new MinIO Access Key and Secret Key..."
        MINIO_ACCESS_KEY="nexent-$(head -c 8 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 12)"
        MINIO_SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)

        # Write to values.yaml
        if grep -q "accessKey:" "$CHART_DIR/values.yaml"; then
            sed -i "s|accessKey:.*|accessKey: \"$MINIO_ACCESS_KEY\"|" "$CHART_DIR/values.yaml"
        else
            sed -i "/minio:/a\\    accessKey: \"$MINIO_ACCESS_KEY\"" "$CHART_DIR/values.yaml"
        fi

        if grep -q "secretKey:" "$CHART_DIR/values.yaml"; then
            sed -i "s|secretKey:.*|secretKey: \"$MINIO_SECRET_KEY\"|" "$CHART_DIR/values.yaml"
        else
            sed -i "/minio:/a\\    secretKey: \"$MINIO_SECRET_KEY\"" "$CHART_DIR/values.yaml"
        fi
        echo "MinIO credentials generated and saved to values.yaml"
        echo "Access Key: $MINIO_ACCESS_KEY"
        echo "Secret Key: $MINIO_SECRET_KEY (saved in values.yaml)"
    else
        echo "MinIO credentials already exist in values.yaml"
        echo "Access Key: $MINIO_ACCESS_KEY"
    fi
    echo ""

    # Step 5: Generate Supabase secrets (only for full version)
    generate_supabase_secrets

    # Step 6: Ask user for Terminal tool (OpenSSH) configuration
    echo "=========================================="
    echo "  Terminal Tool (OpenSSH) Setup"
    echo "=========================================="
    echo "Terminal tool allows AI agents to execute shell commands via SSH."
    echo "This will create an openssh-server pod for secure command execution."
    read -p "Do you want to enable Terminal tool? [Y/N] (default: N): " enable_openssh

    # Default to N if empty
    if [[ "$enable_openssh" =~ ^[Yy]$ ]]; then
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

    # Step 7: Clean up stale PVs
    echo "Checking for stale PersistentVolumes..."
    for pv in nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv; do
        pv_status=$(kubectl get pv $pv -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        if [ "$pv_status" = "Released" ]; then
            echo "  Cleaning up stale PV: $pv"
            kubectl delete pv $pv --ignore-not-found=true || true
        fi
    done

    # Clean up supabase PV if exists
    if [ "$DEPLOYMENT_VERSION" = "full" ]; then
        for pv in nexent-supabase-db-pv; do
            pv_status=$(kubectl get pv $pv -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
            if [ "$pv_status" = "Released" ]; then
                echo "  Cleaning up stale PV: $pv"
                kubectl delete pv $pv --ignore-not-found=true || true
            fi
        done
    fi

    # Step 8: Deploy using Helm
    echo "Deploying Helm chart..."
    helm upgrade --install nexent "$CHART_DIR" \
        --namespace "$NAMESPACE" \
        --create-namespace \
        --set services.openssh.enabled="$ENABLE_OPENSSH" \
        --set secrets.ssh.username="$SSH_USERNAME" \
        --set secrets.ssh.password="$SSH_PASSWORD"

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
                for svc in config runtime data-process mcp northbound; do
                    echo "  Restarting nexent-$svc..."
                    kubectl rollout restart deployment/nexent-$svc -n $NAMESPACE 2>/dev/null || true
                done

                # Wait for backend services to be ready
                echo ""
                echo "Waiting for backend services to be ready..."
                for svc in config runtime data-process mcp northbound; do
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

    # Save deployment options for future use
    persist_deploy_options

    echo "Deployment completed successfully!"
    echo "Access the application at: http://localhost:30000"
    if [ "$ENABLE_OPENSSH" = "true" ]; then
        echo "SSH Terminal at: localhost:30022"
    fi
    if [ "$DEPLOYMENT_VERSION" = "full" ]; then
        echo "Supabase API at: http://localhost:30080"
    fi
    echo "MinIO Console at: http://nexent-minio.local:9001"
}

delete_with_data() {
    echo "Uninstalling Helm release (preserving data)..."
    helm uninstall nexent --namespace "$NAMESPACE" || true

    echo "Cleanup completed! Data is preserved in the host data directories."
    echo "Re-run './deploy-helm.sh apply' to redeploy with existing data."
}

delete_all() {
    echo "Deleting Helm release AND all data..."

    # Uninstall Helm release
    helm uninstall nexent --namespace "$NAMESPACE" || true

    # Wait for pods to terminate
    echo "Waiting for pods to terminate..."
    kubectl wait --for=delete pod -l app=nexent-elasticsearch -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-postgresql -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-redis -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-minio -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-supabase-db -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-supabase-auth -n $NAMESPACE --timeout=120s 2>/dev/null || true
    kubectl wait --for=delete pod -l app=nexent-supabase-kong -n $NAMESPACE --timeout=120s 2>/dev/null || true

    # Delete PVCs to release PVs
    echo "Deleting PVCs to release PersistentVolumes..."
    kubectl delete pvc -n $NAMESPACE --all --ignore-not-found=true || true
    sleep 5

    # Delete PVs
    echo "Deleting PersistentVolumes..."
    kubectl delete pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv nexent-supabase-db-pv --ignore-not-found=true || true

    # Delete namespace
    echo "Deleting namespace..."
    kubectl delete namespace $NAMESPACE --ignore-not-found=true || true

    echo "Cleanup completed! All resources including data have been deleted."
}

case "$COMMAND" in
apply)
    clean_helm_state
    apply
    ;;
clean)
    clean_helm_state
    ;;
delete)
    delete_with_data
    ;;
delete-all)
    delete_all
    ;;
*)
    echo "Usage: $0 {apply|delete|delete-all|clean} [options]"
    echo ""
    echo "Commands:"
    echo "  apply     - Clean helm state and deploy all K8s resources"
    echo "  clean     - Clean helm state only (fixes stuck releases)"
    echo "  delete    - Delete resources but PRESERVE data (PVC/PV)"
    echo "  delete-all - Delete ALL resources including data"
    echo ""
    echo "Options:"
    echo "  --is-mainland Y|N         Specify if server is in mainland China (Y) or not (N)"
    echo "  --version VERSION         Specify app version (auto-detected from const.py if not set)"
    echo "  --deployment-version VER  Specify deployment version: 'speed' (no Supabase) or 'full' (includes Supabase)"
    echo ""
    echo "Examples:"
    echo "  $0 apply                           # Interactive deployment"
    echo "  $0 apply --is-mainland Y            # Deploy with mainland China image sources"
    echo "  $0 apply --is-mainland N            # Deploy with general image sources"
    echo "  $0 apply --deployment-version full # Deploy full version with Supabase"
    echo ""
    echo "Deployment Versions:"
    echo "  speed (default) - Lightweight deployment, essential features only"
    echo "  full            - Full-featured deployment with Supabase authentication"
    echo ""
    echo "Tip: If you see 'Release does not exist' errors, run:"
    echo "  $0 clean"
    exit 1
    ;;
esac
