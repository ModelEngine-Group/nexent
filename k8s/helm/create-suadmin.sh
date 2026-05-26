#!/bin/bash

# Script to create super admin user and insert into user_tenant_t table for K8s deployment
# This script should be called from deploy.sh after Helm deployment completes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$SCRIPT_DIR/nexent"
COMMON_VALUES="$CHART_DIR/charts/nexent-common/values.yaml"
NAMESPACE="nexent"
RELEASE_NAME="nexent"
SUPER_ADMIN_EMAIL="suadmin@nexent.com"

# Prompt user to enter password for super admin user with confirmation
prompt_super_admin_password() {
  local password=""
  local password_confirm=""
  local max_attempts=3
  local attempts=0

  echo "" >&2
  echo "🔐 Super Admin User Password Setup" >&2
  echo "   Email: suadmin@nexent.com" >&2
  echo "" >&2

  while [ $attempts -lt $max_attempts ]; do
    echo "   🔐 Please enter password for super admin user:" >&2
    read -s password
    echo "" >&2

    if [ -z "$password" ]; then
      echo "   ❌ Password cannot be empty. Please try again." >&2
      attempts=$((attempts + 1))
      continue
    fi

    echo "   🔐 Please confirm the password:" >&2
    read -s password_confirm
    echo "" >&2

    if [ "$password" != "$password_confirm" ]; then
      echo "   ❌ Passwords do not match. Please try again." >&2
      attempts=$((attempts + 1))
      continue
    fi

    echo "$password"
    return 0
  done

  echo "   ❌ Maximum attempts reached. Failed to set password." >&2
  return 1
}

# Wait for PostgreSQL pod to be ready
wait_for_nexent_postgresql_ready() {
  local retries=0
  local max_retries=${1:-30}

  while [ $retries -lt $max_retries ]; do
    if kubectl exec -n $NAMESPACE deploy/nexent-postgresql -- pg_isready -U root -d nexent >/dev/null 2>&1; then
      echo "   ✅ PostgreSQL is now ready!"
      return 0
    fi
    echo "   ⏳ Waiting for PostgreSQL to become ready... (attempt $((retries + 1))/$max_retries)"
    sleep 10
    retries=$((retries + 1))
  done

  echo "   ⚠️  Warning: PostgreSQL did not become ready within expected time"
  return 1
}

decode_base64() {
  if base64 --help 2>&1 | grep -q -- '--decode'; then
    base64 --decode
  else
    base64 -D
  fi
}

get_supabase_anon_key() {
  local encoded_key
  encoded_key=$(kubectl get secret nexent-secrets -n "$NAMESPACE" -o jsonpath='{.data.SUPABASE_KEY}' 2>/dev/null || true)
  if [ -n "$encoded_key" ]; then
    printf '%s' "$encoded_key" | decode_base64
    return 0
  fi

  grep "anonKey:" "$COMMON_VALUES" | sed 's/.*anonKey: *//' | tr -d '"' | tr -d "'" | xargs
}

get_existing_super_admin_user_id() {
  local email="$1"
  kubectl exec -n "$NAMESPACE" deploy/nexent-supabase-db -- \
    psql -U postgres -d supabase -t -c "SELECT id FROM auth.users WHERE email = '${email}' LIMIT 1;" 2>/dev/null | tr -d '[:space:]'
}

insert_super_admin_tenant_record() {
  local user_id="$1"
  local email="$2"
  local postgres_pod="nexent-postgresql"

  if [ -z "$user_id" ]; then
    echo "   ⚠️  Warning: user_id is empty. Skipping database insertion."
    return 0
  fi

  echo "   ⏳ Waiting for PostgreSQL to be ready..."
  if ! wait_for_nexent_postgresql_ready; then
    echo "   ⚠️  Warning: PostgreSQL is not ready. Skipping database insertion."
    return 0
  fi

  echo "   🔧 Inserting super admin user into user_tenant_t table..."
  local sql="INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by) VALUES ('${user_id}', '', 'SU', '${email}', 'system', 'system') ON CONFLICT (user_id, tenant_id) DO NOTHING;"

  if kubectl exec -n "$NAMESPACE" deploy/$postgres_pod -- psql -U root -d nexent -c "$sql" >/dev/null 2>&1; then
    echo "   ✅ Super admin user inserted into user_tenant_t table successfully."
  else
    echo "   ⚠️  Warning: Failed to insert super admin user into user_tenant_t table."
  fi
}

# Create default super admin user
create_supabase_super_admin_user() {
  local email="$SUPER_ADMIN_EMAIL"
  local password

  local existing_user_id
  existing_user_id="$(get_existing_super_admin_user_id "$email")"
  if [ -n "$existing_user_id" ]; then
    echo "   🚧 Default super admin user already exists. Skipping password setup."
    echo "   📧 Email:    ${email}"
    insert_super_admin_tenant_record "$existing_user_id" "$email"
    echo ""
    echo "--------------------------------"
    echo ""
    return 0
  fi

  echo "   🔧 Creating super admin user..."

  local anon_key
  anon_key="$(get_supabase_anon_key)"
  if [ -z "$anon_key" ]; then
    echo "   ❌ Could not load SUPABASE_KEY from Kubernetes secret."
    return 1
  fi

  # Prompt user to enter password only when the user does not exist.
  password="$(prompt_super_admin_password)" || return 1

  # Try to create user via Kong API
  local signup_response
  signup_response=$(kubectl exec -n $NAMESPACE deploy/nexent-supabase-db -- \
    curl -s -X POST http://nexent-supabase-kong:8000/auth/v1/signup \
    -H "apikey: ${anon_key}" \
    -H "Authorization: Bearer ${anon_key}" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"email_confirm\":true}" 2>/dev/null)

  if [ -z "$signup_response" ]; then
    echo "   ❌ No response received from Supabase."
    return 1
  fi

  # Check if user was created successfully
  if echo "$signup_response" | grep -q '"access_token"' && echo "$signup_response" | grep -q '"user"'; then
    echo "   ✅ Default super admin user has been successfully created."
    echo ""
    echo "      Please save the following credentials carefully."
    echo "   📧 Email:    ${email}"
    echo "   🔏 Password: [hidden]"

    # Extract user.id from response
    local user_id
    if command -v jq >/dev/null 2>&1; then
      user_id=$(echo "$signup_response" | jq -r '.user.id // empty' 2>/dev/null)
    else
      user_id=$(echo "$signup_response" | grep -o '"user"[^}]*"id":"[^"]*"' | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' 2>/dev/null)
    fi

    if [ -z "$user_id" ]; then
      echo "   ⚠️  Warning: Could not extract user.id from response. Skipping database insertion."
    else
      insert_super_admin_tenant_record "$user_id" "$email"
    fi
  elif echo "$signup_response" | grep -q '"error_code":"user_already_exists"' || echo "$signup_response" | grep -q '"code":422'; then
    echo "   🚧 Default super admin user already exists. Skipping creation."
    echo "   📧 Email:    ${email}"

    # Get user_id from Supabase auth.users table
    echo "   🔧 Retrieving user_id from Supabase database..."
    local user_id
    user_id="$(get_existing_super_admin_user_id "$email")"

    if [ -z "$user_id" ]; then
      echo "   ⚠️  Warning: Could not retrieve user_id. Skipping database insertion."
      echo "   💡 Note: If user_tenant_t record is missing, you may need to insert it manually."
      return 0
    fi

    insert_super_admin_tenant_record "$user_id" "$email"
  else
    echo "   ❌ Response from Supabase does not contain 'access_token' or 'user'."
    return 1
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

# Main execution
main() {
  echo ""
  echo "=========================================="
  echo "  Supabase Super Admin User Creation"
  echo "=========================================="

  # Check if Supabase pods are available
  echo "Checking for Supabase pods..."

  # Wait for supabase-kong
  if ! kubectl wait --for=condition=ready pod -l app=nexent-supabase-kong -n $NAMESPACE --timeout=180s 2>/dev/null; then
    echo "   ⚠️  Warning: Supabase Kong pod is not ready yet."
    echo "   💡 The super admin user will not be created, but deployment will continue."
    return 0
  fi

  # Wait for supabase-db
  if ! kubectl wait --for=condition=ready pod -l app=nexent-supabase-db -n $NAMESPACE --timeout=180s 2>/dev/null; then
    echo "   ⚠️  Warning: Supabase DB pod is not ready yet."
    echo "   💡 The super admin user will not be created, but deployment will continue."
    return 0
  fi

  # Wait for supabase-auth
  if ! kubectl wait --for=condition=ready pod -l app=nexent-supabase-auth -n $NAMESPACE --timeout=180s 2>/dev/null; then
    echo "   ⚠️  Warning: Supabase Auth pod is not ready yet."
    echo "   💡 The super admin user will not be created, but deployment will continue."
    return 0
  fi

  # Create super admin user
  if create_supabase_super_admin_user; then
    return 0
  else
    return 1
  fi
}

# Run main function
main "$@"
