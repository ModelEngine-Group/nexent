#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${DEPLOYMENT_ROOT_ENV:-$DEPLOY_ROOT/env/.env}"
ENV_EXAMPLE="$DEPLOY_ROOT/env/.env.example"
DOCKER_ENV="$PROJECT_ROOT/docker/.env"

if [ "${NEXENT_GENERATE_ENV_SKIP_MAIN:-false}" != "true" ]; then
  echo "   📁 Target .env location: $ENV_FILE"
fi

update_env_var() {
  local key="$1"
  local value="$2"
  local escaped_value
  local current_value

  touch "$ENV_FILE"
  escaped_value=$(printf '%s' "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')

  if grep -q "^${key}=" "$ENV_FILE"; then
    current_value="$(grep "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d'=' -f2- | sed 's/[[:space:]]*$//;s/^"//;s/"$//;s/^'\''//;s/'\''$//')"
    if [ "$current_value" = "$value" ]; then
      echo "   ↺ deploy/env/.env unchanged: $key"
      return 0
    fi
    sed -i.bak "s~^${key}=.*~${key}=${escaped_value}~" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
  echo "   📝 deploy/env/.env updated: $key"
}

# Function to copy and prepare .env file
prepare_env_file() {
  echo "   📝 Preparing deploy/env/.env file..."
  mkdir -p "$(dirname "$ENV_FILE")"

  if [ -f "$ENV_FILE" ]; then
    echo "   ✅ Using existing deploy/env/.env"
  elif [ -f "$DOCKER_ENV" ]; then
    echo "   deploy/env/.env not found, copying docker/.env..."
    cp "$DOCKER_ENV" "$ENV_FILE"
    echo "   Created deploy/env/.env from docker/.env"
  elif [ -f "$ENV_EXAMPLE" ]; then
    echo "   📋 deploy/env/.env not found, copying .env.example..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "   ✅ Created deploy/env/.env from .env.example"
  else
    echo "   ERROR Neither deploy/env/.env nor docker/.env nor deploy/env/.env.example exists"
    ERROR_OCCURRED=1
    return 1
  fi
}

# Function to update .env file with generated keys
update_env_file() {
  echo "   📝 Updating deploy/env/.env file with generated keys..."

  if [ ! -f "$ENV_FILE" ]; then
    echo "   ❌ ERROR deploy/env/.env file does not exist"
    ERROR_OCCURRED=1
    return 1
  fi

  update_env_var "MINIO_ACCESS_KEY" "$MINIO_ACCESS_KEY"
  update_env_var "MINIO_SECRET_KEY" "$MINIO_SECRET_KEY"

  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    update_env_var "ELASTICSEARCH_API_KEY" "$ELASTICSEARCH_API_KEY"
  fi

  if [ -n "$SSH_USERNAME" ]; then
    update_env_var "SSH_USERNAME" "$SSH_USERNAME"
  fi

  if [ -n "$SSH_PASSWORD" ]; then
    update_env_var "SSH_PASSWORD" "$SSH_PASSWORD"
  fi
  echo "   ✅ Generated keys updated successfully"

  # Force update development environment service URLs for localhost access
  echo "   🔧 Updating service URLs for localhost development environment..."

  update_env_var "ELASTICSEARCH_HOST" "http://localhost:9210"
  update_env_var "CONFIG_SERVICE_URL" "http://localhost:5010"
  update_env_var "RUNTIME_SERVICE_URL" "http://localhost:5014"
  update_env_var "ELASTICSEARCH_SERVICE" "http://localhost:5010/api"
  update_env_var "NEXENT_MCP_SERVER" "http://localhost:5011"
  update_env_var "DATA_PROCESS_SERVICE" "http://localhost:5012/api"
  update_env_var "NORTHBOUND_API_SERVER" "http://localhost:5013/api"
  update_env_var "MCP_MANAGEMENT_API" "http://localhost:5015"
  update_env_var "NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS" "${NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS:-false}"
  update_env_var "MINIO_ENDPOINT" "http://localhost:9010"
  update_env_var "REDIS_URL" "redis://localhost:6379/0"
  update_env_var "REDIS_BACKEND_URL" "redis://localhost:6379/1"
  update_env_var "POSTGRES_HOST" "localhost"
  update_env_var "POSTGRES_PORT" "5434"

  # Supabase Configuration (Only for full version)
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    if [ -n "$SUPABASE_KEY" ]; then
      update_env_var "SUPABASE_KEY" "$SUPABASE_KEY"
    fi

    if [ -n "$SERVICE_ROLE_KEY" ]; then
      update_env_var "SERVICE_ROLE_KEY" "$SERVICE_ROLE_KEY"
    fi

    update_env_var "SUPABASE_URL" "http://localhost:8000"
    update_env_var "API_EXTERNAL_URL" "http://localhost:8000"
    update_env_var "SITE_URL" "http://localhost:3011"
  fi

  echo "   ✅ deploy/env/.env updated successfully with localhost development URLs"
}

# Function to show summary
show_summary() {
  echo "🎉 Environment generation completed!"

  echo ""
  echo "--------------------------------"
  echo ""

  echo "🔣 Generated keys:"
  echo "  🔑 MINIO_ACCESS_KEY: $MINIO_ACCESS_KEY"
  echo "  🔑 MINIO_SECRET_KEY: $MINIO_SECRET_KEY"
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    echo "  🔑 ELASTICSEARCH_API_KEY: $ELASTICSEARCH_API_KEY"
  else
    echo "  ⚠️  ELASTICSEARCH_API_KEY: Not generated (Elasticsearch not available)"
  fi
  if [ -n "$SUPABASE_KEY" ]; then
    echo "  🔑 SUPABASE_KEY: $SUPABASE_KEY"
  fi
  if [ -n "$SERVICE_ROLE_KEY" ]; then
    echo "  🔑 SERVICE_ROLE_KEY: $SERVICE_ROLE_KEY"
  fi
  if [ -n "$SSH_USERNAME" ]; then
    echo "  👤 SSH_USERNAME: $SSH_USERNAME"
  fi
  if [ -n "$SSH_PASSWORD" ]; then
    echo "  🔑 SSH_PASSWORD: [HIDDEN]"
  fi
  if [ -z "$ELASTICSEARCH_API_KEY" ]; then
    echo "   ⚠️  Note: To generate ELASTICSEARCH_API_KEY later, please:"
    echo "      1. Start Elasticsearch: docker-compose -p nexent up -d nexent-elasticsearch"
    echo "      2. Wait for it to become healthy"
    echo "      3. Run this script again or manually generate the API key"
  fi
}

# Main execution
main() {
  # Step 1: Prepare .env file
  prepare_env_file || { echo "❌ Failed to prepare .env file"; exit 1; }

  # Step 2: Update .env file
  echo ""
  update_env_file || { echo "❌ Failed to update .env file"; exit 1; }

  # Step 3: Show summary
  show_summary
}

# Run main function
if [ "${NEXENT_GENERATE_ENV_SKIP_MAIN:-false}" != "true" ]; then
  main "$@"
fi
