#!/bin/bash

# Script to create super admin user and insert into user_tenant_t table
# This script should be called from deploy.sh with necessary environment variables

# Note: We don't use set -e here because we want to handle errors gracefully
# and return appropriate exit codes from functions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT_ENV_FILE="$DEPLOY_ROOT/env/.env"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
else
  echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON"
  exit 1
fi

# Source environment variables if deploy/env/.env file exists
if [ -f "$ROOT_ENV_FILE" ]; then
  set -a
  source "$ROOT_ENV_FILE"
  set +a
fi

wait_for_user_tenant_schema_ready() {
  local timeout="${NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS:-300}"
  local interval="${NEXENT_SQL_MIGRATION_WAIT_INTERVAL_SECONDS:-2}"
  local start
  local contract_sql="SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by FROM nexent.user_tenant_t LIMIT 0;"

  start="$(date +%s)"
  while true; do
    if docker exec nexent-postgresql \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -v ON_ERROR_STOP=1 \
      -c "$contract_sql" >/dev/null 2>&1; then
      echo "   ✅ user_tenant_t schema is ready."
      return 0
    fi

    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      echo "   ❌ user_tenant_t schema did not become ready within ${timeout}s."
      return 1
    fi

    echo "   ⏳ Waiting for user_tenant_t schema migration to complete..."
    sleep "$interval"
  done
}

get_existing_super_admin_user_id() {
  local email="$1"
  local result

  if [ "$DEPLOYMENT_VERSION" != "full" ] || ! docker ps | grep -q "supabase-db-mini"; then
    return 1
  fi

  if ! result="$(docker exec supabase-db-mini \
    psql -U postgres -d "$SUPABASE_POSTGRES_DB" -X -A -t -v ON_ERROR_STOP=1 \
    -c "SELECT id FROM auth.users WHERE email = '${email}' LIMIT 1;" 2>/dev/null)"; then
    return 1
  fi

  printf '%s' "$result" | tr -d '[:space:]'
}

insert_super_admin_tenant_record() {
  local user_id="$1"
  local email="$2"
  local sql

  if [ -z "$user_id" ]; then
    echo "   ❌ Cannot insert super admin tenant record: user_id is empty."
    return 1
  fi

  wait_for_user_tenant_schema_ready || return 1

  echo "   🔧 Inserting super admin user into user_tenant_t table..."
  sql="INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by) VALUES ('${user_id}', '', 'SU', '${email}', 'system', 'system') ON CONFLICT (user_id, tenant_id) DO NOTHING;"

  if docker exec -i nexent-postgresql \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -v ON_ERROR_STOP=1 \
    -c "$sql" >/dev/null 2>&1; then
    echo "   ✅ Super admin user inserted into user_tenant_t table successfully."
    return 0
  fi

  echo "   ❌ Failed to insert super admin user into user_tenant_t table."
  return 1
}

create_default_super_admin_user() {
  local email="suadmin@nexent.com"
  local password
  local display_password="${2:-true}"

  # Get password from the deploy script, or use the non-interactive default.
  if [ -n "$1" ]; then
    password="$1"
  else
    password="$(deployment_super_admin_password)"
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

  local response
  response=$(docker exec "$curl_container" bash -c "curl -s -X POST http://kong:8000/auth/v1/signup -H \"apikey: ${SUPABASE_KEY}\" -H \"Authorization: Bearer ${SUPABASE_KEY}\" -H \"Content-Type: application/json\" -d '{\"email\":\"${email}\",\"password\":\"${password}\",\"email_confirm\":true}'" 2>/dev/null)

  if [ -z "$response" ]; then
    echo "   ❌ No response received from Supabase."
    return 1
  elif echo "$response" | grep -q '"access_token"' && echo "$response" | grep -q '"user"'; then
    echo "   ✅ Default super admin user has been successfully created."
    echo ""
    echo "      Please save the following credentials carefully."
    echo "   📧 Email:    ${email}"
    if [ "$display_password" = "true" ]; then
      echo "   🔏 Password: ${password}"
    else
      echo "   🔏 Password: [hidden]"
    fi

    # Extract user.id from the response JSON.
    local user_id
    # Try using jq first (if available in the container or on host)
    if docker exec "$curl_container" command -v jq >/dev/null 2>&1; then
      user_id=$(echo "$response" | docker exec -i "$curl_container" jq -r '.user.id // empty' 2>/dev/null)
    elif command -v jq >/dev/null 2>&1; then
      user_id=$(echo "$response" | jq -r '.user.id // empty' 2>/dev/null)
    fi

    # Fallback: use grep and sed (works without any special tools)
    if [ -z "$user_id" ]; then
      user_id=$(echo "$response" | grep -o '"user"[^}]*"id":"[^"]*"' | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' 2>/dev/null)
    fi

    if [ -z "$user_id" ]; then
      echo "   ❌ Could not extract user.id from the Supabase response."
      return 1
    else
      insert_super_admin_tenant_record "$user_id" "$email" || return 1
    fi
  elif echo "$response" | grep -q '"error_code":"user_already_exists"' || echo "$response" | grep -q '"code":422'; then
    echo "   🚧 Default super admin user already exists. Skipping creation."
    echo "   📧 Email:    ${email}"

    # Even if user already exists, try to ensure the user_tenant_t record exists
    # Get user_id from Supabase auth.users table
    echo "   🔧 Retrieving user_id from Supabase database..."
    local user_id
    user_id="$(get_existing_super_admin_user_id "$email")"

    if [ -z "$user_id" ]; then
      echo "   ❌ Could not retrieve the existing super admin user_id."
      return 1
    fi

    insert_super_admin_tenant_record "$user_id" "$email" || return 1
  else
    echo "   ❌ Response from Supabase does not contain 'access_token' or 'user'."
    return 1
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

# Main execution.
create_default_super_admin_user "${1:-}" "${2:-true}"
