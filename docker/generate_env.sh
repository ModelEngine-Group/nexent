#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e
echo "   📁 Target .env location: Root directory (../)"

# Function to copy and prepare .env file
prepare_env_file() {
  echo "   📝 Preparing root .env file..."

  # Check if .env already exists in root directory (parent directory)
  if [ -f "../.env" ]; then
    echo "   ⚠️  .env already exists in root directory"
    echo ""
    read -p "👉 Do you want to overwrite it? [Y/N] (default: Y): " overwrite
    # If input is empty, use default "Y"
    overwrite=${overwrite:-Y}
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
      echo "   Using existing .env file"
      return 0
    fi
  fi

  # Check if .env exists in current docker directory
  if [ -f ".env" ]; then
    echo "   📋 Copying docker/.env to root directory..."
    cp ".env" "../.env"
    echo "   ✅ Copied docker/.env to ../.env"
  elif [ -f ".env.example" ]; then
    echo "   📋 docker/.env not found, copying .env.example to root directory..."
    cp ".env.example" "../.env"
    echo "   ✅ Copied docker/.env.example to ../.env"
  else
    echo "   ❌ ERROR Neither docker/.env nor docker/.env.example exists in docker directory"
    ERROR_OCCURRED=1
    return 1
  fi
}

# Function to update .env file with generated keys
update_env_file() {
  echo "   📝 Updating root .env file with generated keys..."

  if [ ! -f "../.env" ]; then
    echo "   ❌ ERROR .env file does not exist in root directory"
    ERROR_OCCURRED=1
    return 1
  fi

  # Update or add MINIO_ACCESS_KEY
  if grep -q "^MINIO_ACCESS_KEY=" ../.env; then
    sed -i.bak "s~^MINIO_ACCESS_KEY=.*~MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY~" ../.env
  else
    echo "" >> ../.env
    echo "# Generated MinIO Keys" >> ../.env
    echo "MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY" >> ../.env
  fi

  # Update or add MINIO_SECRET_KEY
  if grep -q "^MINIO_SECRET_KEY=" ../.env; then
    sed -i.bak "s~^MINIO_SECRET_KEY=.*~MINIO_SECRET_KEY=$MINIO_SECRET_KEY~" ../.env
  else
    echo "MINIO_SECRET_KEY=$MINIO_SECRET_KEY" >> ../.env
  fi

  # Update or add ELASTICSEARCH_API_KEY (only if it was generated successfully)
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    if grep -q "^ELASTICSEARCH_API_KEY=" ../.env; then
      sed -i.bak "s~^ELASTICSEARCH_API_KEY=.*~ELASTICSEARCH_API_KEY=$ELASTICSEARCH_API_KEY~" ../.env
    else
      echo "" >> ../.env
      echo "# Generated Elasticsearch API Key" >> ../.env
      echo "ELASTICSEARCH_API_KEY=$ELASTICSEARCH_API_KEY" >> ../.env
    fi
  fi

  # Update or add SSH credentials (only if they were set)
  if [ -n "$SSH_USERNAME" ]; then
    if grep -q "^SSH_USERNAME=" ../.env; then
      sed -i.bak "s~^SSH_USERNAME=.*~SSH_USERNAME=$SSH_USERNAME~" ../.env
    else
      echo "" >> ../.env
      echo "# SSH Terminal Tool Credentials" >> ../.env
      echo "SSH_USERNAME=$SSH_USERNAME" >> ../.env
    fi
  fi

  if [ -n "$SSH_PASSWORD" ]; then
    if grep -q "^SSH_PASSWORD=" ../.env; then
      sed -i.bak "s~^SSH_PASSWORD=.*~SSH_PASSWORD=$SSH_PASSWORD~" ../.env
    else
      echo "SSH_PASSWORD=$SSH_PASSWORD" >> ../.env
    fi
  fi
  echo "   ✅ Generated keys updated successfully"

  # Force update development environment service URLs for localhost access
  echo "   🔧 Updating service URLs for localhost development environment..."

  # ELASTICSEARCH_HOST
  if grep -q "^ELASTICSEARCH_HOST=" ../.env; then
    sed -i.bak "s~^ELASTICSEARCH_HOST=.*~ELASTICSEARCH_HOST=http://localhost:9210~" ../.env
  else
    echo "" >> ../.env
    echo "# Development Environment URLs" >> ../.env
    echo "ELASTICSEARCH_HOST=http://localhost:9210" >> ../.env
  fi

  # Main Services
  # CONFIG_SERVICE_URL
  if grep -q "^CONFIG_SERVICE_URL=" ../.env; then
    sed -i.bak "s~^CONFIG_SERVICE_URL=.*~CONFIG_SERVICE_URL=http://localhost:5010~" ../.env
  else
    echo "" >> ../.env
    echo "# Main Services" >> ../.env
    echo "CONFIG_SERVICE_URL=http://localhost:5010" >> ../.env
  fi

  # RUNTIME_SERVICE_URL
  if grep -q "^RUNTIME_SERVICE_URL=" ../.env; then
    sed -i.bak "s~^RUNTIME_SERVICE_URL=.*~RUNTIME_SERVICE_URL=http://localhost:5014~" ../.env
  else
    echo "RUNTIME_SERVICE_URL=http://localhost:5014" >> ../.env
  fi

  # ELASTICSEARCH_SERVICE
  if grep -q "^ELASTICSEARCH_SERVICE=" ../.env; then
    sed -i.bak "s~^ELASTICSEARCH_SERVICE=.*~ELASTICSEARCH_SERVICE=http://localhost:5010/api~" ../.env
  else
    echo "ELASTICSEARCH_SERVICE=http://localhost:5010/api" >> ../.env
  fi

  # NEXENT_MCP_SERVER
  if grep -q "^NEXENT_MCP_SERVER=" ../.env; then
    sed -i.bak "s~^NEXENT_MCP_SERVER=.*~NEXENT_MCP_SERVER=http://localhost:5011~" ../.env
  else
    echo "NEXENT_MCP_SERVER=http://localhost:5011" >> ../.env
  fi

  # DATA_PROCESS_SERVICE
  if grep -q "^DATA_PROCESS_SERVICE=" ../.env; then
    sed -i.bak "s~^DATA_PROCESS_SERVICE=.*~DATA_PROCESS_SERVICE=http://localhost:5012/api~" ../.env
  else
    echo "DATA_PROCESS_SERVICE=http://localhost:5012/api" >> ../.env
  fi

  # NORTHBOUND_API_SERVER
  if grep -q "^NORTHBOUND_API_SERVER=" ../.env; then
    sed -i.bak "s~^NORTHBOUND_API_SERVER=.*~NORTHBOUND_API_SERVER=http://localhost:5013/api~" ../.env
  else
    echo "NORTHBOUND_API_SERVER=http://localhost:5013/api" >> ../.env
  fi

  # MINIO_ENDPOINT
  if grep -q "^MINIO_ENDPOINT=" ../.env; then
    sed -i.bak "s~^MINIO_ENDPOINT=.*~MINIO_ENDPOINT=http://localhost:9010~" ../.env
  else
    echo "MINIO_ENDPOINT=http://localhost:9010" >> ../.env
  fi

  # REDIS_URL
  if grep -q "^REDIS_URL=" ../.env; then
    sed -i.bak "s~^REDIS_URL=.*~REDIS_URL=redis://localhost:6379/0~" ../.env
  else
    echo "REDIS_URL=redis://localhost:6379/0" >> ../.env
  fi

  # REDIS_BACKEND_URL
  if grep -q "^REDIS_BACKEND_URL=" ../.env; then
    sed -i.bak "s~^REDIS_BACKEND_URL=.*~REDIS_BACKEND_URL=redis://localhost:6379/1~" ../.env
  else
    echo "REDIS_BACKEND_URL=redis://localhost:6379/1" >> ../.env
  fi

  # DOCKER_HOST (set default per platform)
  local docker_host_value="unix:///var/run/docker.sock"
  case "$(uname -s)" in
    MINGW*|CYGWIN*|MSYS*|Windows_NT)
      docker_host_value="npipe:////./pipe/docker_engine"
      ;;
  esac
  if grep -q "^DOCKER_HOST=" ../.env; then
    sed -i.bak "s~^DOCKER_HOST=.*~DOCKER_HOST=$docker_host_value~" ../.env
  else
    echo "DOCKER_HOST=$docker_host_value" >> ../.env
  fi

  # POSTGRES_HOST
  if grep -q "^POSTGRES_HOST=" ../.env; then
    sed -i.bak "s~^POSTGRES_HOST=.*~POSTGRES_HOST=localhost~" ../.env
  else
    echo "POSTGRES_HOST=localhost" >> ../.env
  fi

  # POSTGRES_PORT
  if grep -q "^POSTGRES_PORT=" ../.env; then
    sed -i.bak "s~^POSTGRES_PORT=.*~POSTGRES_PORT=5434~" ../.env
  else
    echo "POSTGRES_PORT=5434" >> ../.env
  fi

  # Supabase Configuration (Only for full version)
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    if [ -n "$SUPABASE_KEY" ]; then      
      if grep -q "^SUPABASE_KEY=" ../.env; then
        sed -i.bak "s~^SUPABASE_KEY=.*~SUPABASE_KEY=$SUPABASE_KEY~" ../.env
      else
        echo "" >> ../.env
        echo "# Supabase Keys" >> ../.env
        echo "SUPABASE_KEY=$SUPABASE_KEY" >> ../.env
      fi
    fi

    if [ -n "$SERVICE_ROLE_KEY" ]; then
      if grep -q "^SERVICE_ROLE_KEY=" ../.env; then
        sed -i.bak "s~^SERVICE_ROLE_KEY=.*~SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY~" ../.env
      else
        echo "SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY" >> ../.env
      fi
    fi
    
    # Additional Supabase configuration
    if grep -q "^SUPABASE_URL=" ../.env; then
      sed -i.bak "s~^SUPABASE_URL=.*~SUPABASE_URL=http://localhost:8000~" ../.env
    else
      echo "SUPABASE_URL=http://localhost:8000" >> ../.env
    fi
    
    if grep -q "^API_EXTERNAL_URL=" ../.env; then
      sed -i.bak "s~^API_EXTERNAL_URL=.*~API_EXTERNAL_URL=http://localhost:8000~" ../.env
    else
      echo "API_EXTERNAL_URL=http://localhost:8000" >> ../.env
    fi
    
    if grep -q "^SITE_URL=" ../.env; then
      sed -i.bak "s~^SITE_URL=.*~SITE_URL=http://localhost:3011~" ../.env
    else
      echo "SITE_URL=http://localhost:3011" >> ../.env
    fi
  fi

  # Remove backup file
  rm -f ../.env.bak

  echo "   ✅ Root .env file updated successfully with localhost development URLs"
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
main "$@"