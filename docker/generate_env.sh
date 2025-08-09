#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

ERROR_OCCURRED=0
echo "ℹ️  Script location: docker/generate_env.sh"
echo "📁 Target .env location: Root directory (../)"
echo ""

# Function to generate MinIO access keys
echo_minio_ak_sk() {
  echo "✅ MinIO access keys generated successfully"
  echo "   MINIO_ACCESS_KEY: $ACCESS_KEY"
  echo "   MINIO_SECRET_KEY: $SECRET_KEY"
}

# Function to generate Elasticsearch API key
generate_elasticsearch_api_key() {
  echo "🔑 Generating ELASTICSEARCH_API_KEY..."

  # Check if docker-compose is available
  if ! command -v docker-compose &> /dev/null; then
    echo "❌ ERROR docker-compose is not available"
    ERROR_OCCURRED=1
    return 1
  fi

  # Check if Elasticsearch container is running and healthy
  if ! docker-compose -p nexent ps nexent-elasticsearch | grep -q "healthy"; then
    echo "⚠️  WARNING: Elasticsearch container is not running or not healthy"
    echo "   Please make sure Elasticsearch is running first by executing:"
    echo "   docker-compose -p nexent up -d nexent-elasticsearch"
    echo "   Then wait for it to become healthy before running this script again."
    echo ""
    echo "   Alternatively, you can manually set ELASTICSEARCH_API_KEY in the .env file"
    echo "   after starting the services."
    ERROR_OCCURRED=1
    return 1
  fi

  # Generate API key - use the same method as in deploy.sh
  # First, source the .env file to get ELASTIC_PASSWORD
  if [ -f "../.env" ]; then
    source ../.env
  elif [ -f ".env" ]; then
    source .env
  else
    echo "❌ ERROR .env file not found, cannot get ELASTIC_PASSWORD"
    ERROR_OCCURRED=1
    return 1
  fi

  # Generate API key
  API_KEY_JSON=$(docker-compose -p nexent exec -T nexent-elasticsearch curl -s -u "elastic:$ELASTIC_PASSWORD" "http://localhost:9200/_security/api_key" -H "Content-Type: application/json" -d '{"name":"nexent_api_key","role_descriptors":{"nexent_role":{"cluster":["all"],"index":[{"names":["*"],"privileges":["all"]}]}}}')

  # Extract API key
  ELASTICSEARCH_API_KEY=$(echo "$API_KEY_JSON" | grep -o '"encoded":"[^"]*"' | awk -F'"' '{print $4}')

  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    export ELASTICSEARCH_API_KEY
    echo "✅ ELASTICSEARCH_API_KEY generated successfully"
  else
    echo "❌ ERROR Failed to generate ELASTICSEARCH_API_KEY"
    echo "   Response: $API_KEY_JSON"
    ERROR_OCCURRED=1
    return 1
  fi
}

add_jwt_to_env() {
  echo "Generating and updating Supabase secrets..."
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
  update_env_var "ANON_KEY" "$anon_key"
  update_env_var "SUPABASE_KEY" "$anon_key"
  update_env_var "SERVICE_ROLE_KEY" "$service_role_key"

  # Reload the environment variables from the updated .env file
  source .env
}

# Function to copy and prepare .env file
prepare_env_file() {
  echo "📝 Preparing .env file..."

  # Check if .env already exists in root directory (parent directory)
  if [ -f "../.env" ]; then
    echo "⚠️  .env file already exists in root directory"
    read -p "   Do you want to overwrite it? [Y/N] (default: N): " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
      echo "   Using existing .env file"
      return 0
    fi
  fi

  # Check if .env exists in current docker directory
  if [ -f ".env" ]; then
    echo "📋 Copying .env to root directory..."
    cp ".env" "../.env"
    echo "✅ Copied docker/.env to ../.env"
  elif [ -f ".env.example" ]; then
    echo "📋 .env not found, copying .env.example to root directory..."
    cp ".env.example" "../.env"
    echo "✅ Copied docker/.env.example to ../.env"
  else
    echo "❌ ERROR Neither .env nor .env.example exists in docker directory"
    ERROR_OCCURRED=1
    return 1
  fi
}

# Function to update .env file with generated keys
update_env_file() {
  echo "📝 Updating .env file with generated keys..."

  if [ ! -f "../.env" ]; then
    echo "❌ ERROR .env file does not exist in root directory"
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

  # Force update development environment service URLs for localhost access
  echo "🔧 Updating service URLs for localhost development environment..."

  # ELASTICSEARCH_HOST
  if grep -q "^ELASTICSEARCH_HOST=" ../.env; then
    sed -i.bak "s~^ELASTICSEARCH_HOST=.*~ELASTICSEARCH_HOST=http://localhost:9210~" ../.env
  else
    echo "" >> ../.env
    echo "# Development Environment URLs" >> ../.env
    echo "ELASTICSEARCH_HOST=http://localhost:9210" >> ../.env
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

  # Supabase PostgreSQL Configuration (only for full version)
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    echo ""
    echo "# Supabase PostgreSQL Configuration" >> ../.env
    
    # Additional Supabase configuration
    if grep -q "^SUPABASE_URL=" ../.env; then
      sed -i.bak "s~^SUPABASE_URL=.*~SUPABASE_URL=http://localhost:8000~" ../.env
    else
      echo "SUPABASE_URL=http://localhost:8000" >> ../.env
    fi
    
    # Additional Supabase configuration
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

  echo "✅ .env file updated successfully with localhost development URLs"
}

# Function to show summary
show_summary() {
  echo "🎉 Environment generation completed!"

  echo ""
  echo "--------------------------------"
  echo ""

  echo "Generated keys:"
  echo "  ✅ MINIO_ACCESS_KEY: $MINIO_ACCESS_KEY"
  echo "  ✅ MINIO_SECRET_KEY: $MINIO_SECRET_KEY"
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    echo "  ✅ ELASTICSEARCH_API_KEY: $ELASTICSEARCH_API_KEY"
  else
    echo "  ⚠️  ELASTICSEARCH_API_KEY: Not generated (Elasticsearch not available)"
  fi
  echo ""
  echo "📁 .env file location: $(cd .. && pwd)/.env"
  echo ""
  if [ -z "$ELASTICSEARCH_API_KEY" ]; then
    echo "⚠️  Note: To generate ELASTICSEARCH_API_KEY later, please:"
    echo "   1. Start Elasticsearch: docker-compose -p nexent up -d nexent-elasticsearch"
    echo "   2. Wait for it to become healthy"
    echo "   3. Run this script again or manually generate the API key"
  fi
}

# Main execution
main() {
  # Step 1: Prepare .env file
  prepare_env_file || { echo "❌ Failed to prepare .env file"; exit 1; }

  # Step 2: Echo MinIO keys
  echo_minio_ak_sk || { echo "❌ Failed to echo MinIO keys"; exit 1; }

  # Step 3: Try to generate Elasticsearch API key (optional)
  echo ""
  generate_elasticsearch_api_key || {
    echo "⚠️  Warning: Elasticsearch API key generation failed"
    echo "   Continuing with MinIO keys only..."
    ERROR_OCCURRED=0  # Reset error flag for optional step
  }

  # Step 4: Generate JWT secrets only if DEPLOYMENT_VERSION is "full"
  if [ "$DEPLOYMENT_VERSION" = "full" ]; then
    echo "🎯 Full version detected - generating JWT secrets for Supabase..."
    add_jwt_to_env || { echo "❌ Failed to generate JWT secrets"; exit 1; }
  else
    echo "⚡ Speed version detected - skipping JWT secrets generation"
  fi

  # Step 5: Update .env file
  echo ""
  update_env_file || { echo "❌ Failed to update .env file"; exit 1; }

  # Step 6: Show summary
  show_summary
}

# Run main function
main "$@"