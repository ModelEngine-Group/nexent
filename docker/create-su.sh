#!/bin/bash

# Script to create super admin user and insert into user_tenant_t table
# This script should be called from deploy.sh with necessary environment variables

# Note: We don't use set -e here because we want to handle errors gracefully
# and return appropriate exit codes from functions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source environment variables if .env file exists
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

generate_random_password() {
  # Generate a URL/JSON safe random password (alphanumeric only)
  local pwd=""
  if command -v openssl >/dev/null 2>&1; then
    pwd=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 20)
  else
    pwd=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)
  fi
  if [ -z "$pwd" ]; then
    # Fallback (should be extremely rare)
    pwd=$(date +%s%N | tr -dc '0-9' | head -c 20)
  fi
  echo "$pwd"
}

wait_for_postgresql_ready() {
  # Function to wait for PostgreSQL to become ready
  local retries=0
  local max_retries=${1:-30}  # Default 5 minutes, can be overridden
  while [ $retries -lt $max_retries ]; do
      if docker exec nexent-postgresql pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
          echo "   ✅ PostgreSQL is now ready!"
          return 0
      fi
      echo "⏳ Waiting for PostgreSQL to become ready... (attempt $((retries + 1))/$max_retries)"
      sleep 10
      retries=$((retries + 1))
  done

  if [ $retries -eq $max_retries ]; then
      echo "   ⚠️  Warning: PostgreSQL did not become ready within expected time"
      echo "     You may need to check the container logs and try again"
      return 1
  fi
}

create_default_super_admin_user() {
  local email="suadmin@nexent.com"
  local password
  
  # Get password from command line argument, or generate random one if not provided
  if [ -n "$1" ]; then
    password="$1"
  else
    # Fallback to random password if no argument provided (for backward compatibility)
    password="$(generate_random_password)"
    echo "   ⚠️  Warning: No password provided, using random password"
  fi

  echo "🔧 Creating super admin user..."
  
  # Determine which container to use for curl command
  local curl_container="nexent-config"
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ] || ! docker ps | grep -q "nexent-config"; then
    # In infrastructure mode or if nexent-config is not running, use supabase-db-mini
    if docker ps | grep -q "supabase-db-mini"; then
      curl_container="supabase-db-mini"
      echo "   ℹ️  Using supabase-db-mini container (infrastructure mode)"
    else
      echo "   ❌ Neither nexent-config nor supabase-db-mini container is available."
      return 1
    fi
  fi

  RESPONSE=$(docker exec "$curl_container" bash -c "curl -s -X POST http://kong:8000/auth/v1/signup -H \"apikey: ${SUPABASE_KEY}\" -H \"Authorization: Bearer ${SUPABASE_KEY}\" -H \"Content-Type: application/json\" -d '{\"email\":\"${email}\",\"password\":\"${password}\",\"email_confirm\":true}'" 2>/dev/null)

  if [ -z "$RESPONSE" ]; then
    echo "   ❌ No response received from Supabase."
    return 1
  elif echo "$RESPONSE" | grep -q '"access_token"' && echo "$RESPONSE" | grep -q '"user"'; then
    echo "   ✅ Default super admin user has been successfully created."
    echo ""
    echo "      Please save the following credentials carefully."
    echo "   📧 Email:    ${email}"
    if [ -n "$1" ]; then
      echo "   🔏 Password: [User provided password]"
    else
      echo "   🔏 Password: ${password}"
    fi

    # Extract user.id from RESPONSE JSON
    local user_id
    # Try using jq first (if available in the container or on host)
    if docker exec "$curl_container" command -v jq >/dev/null 2>&1; then
      user_id=$(echo "$RESPONSE" | docker exec -i "$curl_container" jq -r '.user.id // empty' 2>/dev/null)
    elif command -v jq >/dev/null 2>&1; then
      user_id=$(echo "$RESPONSE" | jq -r '.user.id // empty' 2>/dev/null)
    fi

    # Fallback: use grep and sed (works without any special tools)
    if [ -z "$user_id" ]; then
      user_id=$(echo "$RESPONSE" | grep -o '"user"[^}]*"id":"[^"]*"' | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' 2>/dev/null)
    fi

    if [ -z "$user_id" ]; then
      echo "   ⚠️  Warning: Could not extract user.id from response. Skipping database insertion."
    else
      # Wait for PostgreSQL to be ready
      echo "   ⏳ Waiting for PostgreSQL to be ready..."
      if ! wait_for_postgresql_ready; then
        echo "   ⚠️  Warning: PostgreSQL is not ready. Skipping database insertion."
        return 0
      fi

      # Insert user_tenant_t record
      echo "   🔧 Inserting super admin user into user_tenant_t table..."
      local sql="INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by) VALUES ('${user_id}', '', 'SU', '${email}', 'system', 'system') ON CONFLICT (user_id, tenant_id) DO NOTHING;"

      if docker exec -i nexent-postgresql psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$sql" >/dev/null 2>&1; then
        echo "   ✅ Super admin user inserted into user_tenant_t table successfully."
      else
        echo "   ⚠️  Warning: Failed to insert super admin user into user_tenant_t table."
      fi
    fi
  elif echo "$RESPONSE" | grep -q '"error_code":"user_already_exists"' || echo "$RESPONSE" | grep -q '"code":422'; then
    echo "   🚧 Default super admin user already exists. Skipping creation."
    echo "   📧 Email:    ${email}"

    # Even if user already exists, try to ensure the user_tenant_t record exists
    # Get user_id from Supabase auth.users table
    echo "   🔧 Retrieving user_id from Supabase database..."
    local user_id
    if [ "$DEPLOYMENT_VERSION" = "full" ] && docker ps | grep -q "supabase-db-mini"; then
      # Query Supabase auth.users table to get user_id by email
      user_id=$(docker exec supabase-db-mini psql -U postgres -d "$SUPABASE_POSTGRES_DB" -t -c "SELECT id FROM auth.users WHERE email = '${email}' LIMIT 1;" 2>/dev/null | tr -d '[:space:]')
    fi

    if [ -z "$user_id" ]; then
      echo "   ⚠️  Warning: Could not retrieve user_id. Skipping database insertion."
      echo "   💡 Note: If user_tenant_t record is missing, you may need to insert it manually."
      return 0
    fi

    # Wait for PostgreSQL to be ready
    echo "   ⏳ Waiting for PostgreSQL to be ready..."
    if ! wait_for_postgresql_ready; then
      echo "   ⚠️  Warning: PostgreSQL is not ready. Skipping database insertion."
      return 0
    fi

    # Insert user_tenant_t record
    echo "   🔧 Inserting super admin user into user_tenant_t table..."
    local sql="INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by) VALUES ('${user_id}', '', 'SU', '${email}', 'system', 'system') ON CONFLICT (user_id, tenant_id) DO NOTHING;"

    if docker exec -i nexent-postgresql psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$sql" >/dev/null 2>&1; then
      echo "   ✅ Super admin user inserted into user_tenant_t table successfully."
    else
      echo "   ⚠️  Warning: Failed to insert super admin user into user_tenant_t table."
    fi
  else
    echo "   ❌ Response from Supabase does not contain 'access_token' or 'user'."
    return 1
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

# Main execution
# Pass password as first argument if provided
if create_default_super_admin_user "$1"; then
  exit 0
else
  exit 1
fi
