#!/bin/bash

# Script to install built-in skills from official-skills-zip directory
# This script should be called from deploy.sh with necessary environment variables

# Note: We don't use set -e here because we want to handle errors gracefully

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ZIP_DIR="$SCRIPT_DIR/official-skills-zip"
TOKEN_FILE="$SCRIPT_DIR/.access_token"

# Source environment variables if .env file exists
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

sanitize_input() {
  local input="$1"
  printf "%s" "$input" | tr -d '\r'
}

cleanup_token() {
  # Securely remove access token files and clear variables
  if [ -f "$TOKEN_FILE" ]; then
    shred -f -u "$TOKEN_FILE" 2>/dev/null || rm -f "$TOKEN_FILE"
  fi
  unset ACCESS_TOKEN USER_PASSWORD
}

# Cleanup on exit
trap cleanup_token EXIT INT TERM

get_access_token() {
  # Get access token based on user existence
  # Returns: access_token ONLY (no log messages to stdout)

  local email="$1"
  local password="$2"

  # Check if super admin user exists
  local check_result
  check_super_admin_user_exists "$email"
  check_result=$?

  if [ $check_result -eq 0 ]; then
    # User exists, sign in to get access token
    local response
    response=$(docker exec nexent-config bash -c "curl -s -X POST http://kong:8000/auth/v1/token?grant_type=password -H \"apikey: ${SUPABASE_KEY}\" -H \"Content-Type: application/json\" -d '{\"email\":\"${email}\",\"password\":\"${password}\"}'" 2>/dev/null)

    if echo "$response" | grep -q '"access_token"'; then
      # Extract access_token ONLY
      local access_token
      access_token=$(echo "$response" | grep -o '"access_token":"[^"]*"' | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
      unset response
      echo "$access_token"
      return 0
    else
      unset response
      echo "   ❌ Failed to get access token from sign in response." >&2
      return 1
    fi
  else
    echo "   ❌ Super admin user does not exist. Cannot get access token." >&2
    return 1
  fi
}

check_super_admin_user_exists() {
  # Check if super admin user exists in Supabase
  local email="${1:-suadmin@nexent.com}"

  # Determine which container to use for curl command
  local curl_container="nexent-config"
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ] || ! docker ps | grep -q "nexent-config"; then
    if docker ps | grep -q "supabase-db-mini"; then
      curl_container="supabase-db-mini"
    else
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

install_skills() {
  # Main function to install built-in skills
  local access_token="$1"

  echo "🔧 Installing built-in skills..."

  # Check if skills zip directory exists
  if [ ! -d "$SKILLS_ZIP_DIR" ]; then
    echo "   ⚠️  Warning: official-skills-zip directory not found at $SKILLS_ZIP_DIR"
    echo "   💡 Please ensure the skills zip files are available."
    return 1
  fi

  # Collect all zip files into an array
  local skills_to_install=()
  local skill_file
  for skill_file in "$SKILLS_ZIP_DIR"/*.zip; do
    if [ -f "$skill_file" ]; then
      skills_to_install+=("$skill_file")
    fi
  done

  if [ ${#skills_to_install[@]} -eq 0 ]; then
    echo "   ⚠️  Warning: No skill zip files found in $SKILLS_ZIP_DIR"
    return 1
  fi

  echo "   📦 Found ${#skills_to_install[@]} skills to install:"
  local idx
  for idx in "${!skills_to_install[@]}"; do
    local skill_name
    skill_name=$(basename "${skills_to_install[$idx]}" .zip)
    echo "      $((idx + 1)). $skill_name"
  done
  echo ""

  # Wait for nexent-config container to be ready
  echo "   ⏳ Waiting for nexent-config container to be ready..."
  local retries=0
  local max_retries=60
  while ! docker exec nexent-config echo "ready" >/dev/null 2>&1 && [ $retries -lt $max_retries ]; do
    echo "   ⏳ Waiting for nexent-config... (attempt $((retries + 1))/$max_retries)"
    sleep 5
    retries=$((retries + 1))
  done

  if [ $retries -eq $max_retries ]; then
    echo "   ❌ Error: nexent-config container is not available"
    return 1
  fi
  echo "   ✅ nexent-config container is ready"

  # Query installed skills to skip already installed ones
  echo ""
  echo "   📋 Checking installed skills..."
  local installed_skills=""
  local list_result
  list_result=$(docker exec nexent-config bash -c \
    "curl -s -X GET 'http://localhost:5010/skills' \
     -H \"Authorization: Bearer ${access_token}\" \
     -H 'Content-Type: application/json' 2>&1")
  
  if echo "$list_result" | grep -q '"skills"'; then
    # Extract skill names from the response
    installed_skills=$(echo "$list_result" | grep -o '"name":"[^"]*"' | sed 's/"name":"//g' | sed 's/"//g' | tr '\n' ' ')
    echo "   ✅ Found $(echo "$installed_skills" | wc -w) installed skills"
  else
    echo "   ⚠️  Could not fetch installed skills list, will install all"
    # Log for debugging
    echo "   [DEBUG] List response: $list_result" >> /tmp/install-debug.log 2>/dev/null
  fi

  # Copy skills zip files to container's temp directory
  local temp_dir="/tmp/official-skills-zip"
  echo ""
  echo "   📦 Copying skill files to container..."
  local all_copied=true
  local skip_copy_count=0
  for skill_file in "${skills_to_install[@]}"; do
    local skill_name
    skill_name=$(basename "$skill_file" .zip)

    # Check if skill is already installed
    if echo "$installed_skills" | grep -qw "$skill_name"; then
      echo "      ⏭️  $skill_name - skipped"
      skip_copy_count=$((skip_copy_count + 1))
      continue
    fi

    # Create temp directory first
    docker exec nexent-config bash -c "mkdir -p $temp_dir && chmod 777 $temp_dir" >/dev/null 2>&1

    # Copy file
    if docker cp "$skill_file" "nexent-config:${temp_dir}/${skill_name}.zip" 2>/dev/null; then
      echo -n "      Copying $skill_name... ✅"
      echo ""
    else
      echo -n "      Copying $skill_name... ❌"
      echo ""
      echo "         Failed to copy file to container"
      all_copied=false
    fi
  done

  if [ "$all_copied" = false ]; then
    echo "   ⚠️  Some files failed to copy"
  fi

  # Install each skill
  echo ""
  echo "   🚀 Installing skills..."
  local success_count=0
  local fail_count=0
  local skip_count=0

  for skill_file in "${skills_to_install[@]}"; do
    local skill_name
    skill_name=$(basename "$skill_file" .zip)
    local full_path="${temp_dir}/${skill_name}.zip"

    # Check if skill is already installed
    if echo "$installed_skills" | grep -qw "$skill_name"; then
      echo "      ⏭️  $skill_name - skipped"
      skip_count=$((skip_count + 1))
      continue
    fi

    echo -n "      Installing $skill_name... "

    # Check if file exists in container
    local file_exists
    local file_size
    file_exists=$(docker exec nexent-config bash -c "test -f '${full_path}' && echo 'yes' || echo 'no'" 2>/dev/null)
    file_size=$(docker exec nexent-config bash -c "stat -c%s '${full_path}' 2>/dev/null || stat -f%z '${full_path}' 2>/dev/null || echo 'unknown'" 2>/dev/null)
    
    if [ "$file_exists" != "yes" ]; then
      echo "❌"
      echo "         File not found in container at ${full_path}"
      fail_count=$((fail_count + 1))
      continue
    fi
    
    if [ "$file_size" = "0" ] || [ "$file_size" = "unknown" ]; then
      echo "❌"
      echo "         File is empty or size unknown (${file_size} bytes)"
      fail_count=$((fail_count + 1))
      continue
    fi

    # Call the upload API with source="官方"
    local result
    local debug_log="/tmp/install-debug.log"
    
    # Log the request details
    echo "  [DEBUG] Uploading: $skill_name" >> "$debug_log"
    echo "  File: $full_path" >> "$debug_log"
    echo "  Token prefix: ${access_token:0:20}..." >> "$debug_log"
    
    # Run curl - variables must be in double quotes to expand
    result=$(docker exec nexent-config bash -c \
      "curl -v -X POST 'http://localhost:5010/skills/upload' \
       -H \"Authorization: Bearer ${access_token}\" \
       -F \"file=@${full_path}\" \
       -F 'source=官方' 2>&1")
    local curl_exit_code=$?
    
    echo "  Curl exit code: $curl_exit_code" >> "$debug_log"
    echo "  Response: $result" >> "$debug_log"
    echo "---" >> "$debug_log"

    # Check if installation was successful
    if echo "$result" | grep -q '"success":true\|"id"\|"name"\|"skill_id"'; then
      echo "✅"
      success_count=$((success_count + 1))
    elif echo "$result" | grep -q '"error"\|"message"\|"detail"'; then
      echo "❌"
      # Extract error message
      local error_msg
      error_msg=$(echo "$result" | grep -o '"message":"[^"]*"\|"detail":"[^"]*"' | head -1 | sed 's/"//g' | cut -d':' -f2-)
      if [ -z "$error_msg" ]; then
        error_msg="$result"
      fi
      echo "         $error_msg"
      fail_count=$((fail_count + 1))
    elif echo "$result" | grep -q '{.*}' 2>/dev/null; then
      echo "✅"
      success_count=$((success_count + 1))
    else
      echo "❌"
      echo "         Unknown response: $result"
      fail_count=$((fail_count + 1))
    fi
  done

  # Cleanup temp directory
  docker exec nexent-config bash -c "rm -rf $temp_dir" 2>/dev/null

  echo ""
  echo "   📊 Installation Summary:"
  echo "     ⏭️  Skipped: $skip_count"
  echo "      ✅ Success: $success_count"
  echo "      ❌ Failed: $fail_count"
  echo ""
}

# Main execution
if [ $# -lt 1 ]; then
  echo "Usage: $0 <access_token> [email] [password]"
  echo "   access_token: Bearer token for API authentication (required)"
  echo "   email: User email for sign-in (optional, for existing users)"
  echo "   password: User password for sign-in (optional, for existing users)"
  exit 1
fi

ACCESS_TOKEN="$1"
USER_EMAIL="${2:-suadmin@nexent.com}"
USER_PASSWORD="$3"

# If access token is "GET_TOKEN", we need to get it via sign-in
if [ "$ACCESS_TOKEN" = "GET_TOKEN" ]; then
  if [ -z "$USER_PASSWORD" ]; then
    echo "❌ Error: Password required to get access token for existing user."
    exit 1
  fi

  echo -n "🔐 Getting access token... "
  ACCESS_TOKEN=$(get_access_token "$USER_EMAIL" "$USER_PASSWORD")
  if [ -z "$ACCESS_TOKEN" ]; then
    echo "❌"
    echo "❌ Error: Failed to get access token."
    exit 1
  fi
  echo "✅"
fi

if install_skills "$ACCESS_TOKEN"; then
  exit 0
else
  exit 1
fi
