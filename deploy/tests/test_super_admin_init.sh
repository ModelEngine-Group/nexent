#!/usr/bin/env bash

set -uo pipefail

TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/nexent-super-admin-test.XXXXXX")"
trap 'rm -rf "$TEST_TMP"' EXIT

fail() {
  echo "FAIL: $1"
  return 1
}

assert_file_contains() {
  local file="$1"
  local expected="$2"
  local message="$3"

  if ! grep -Fq -- "$expected" "$file"; then
    fail "$message"
  fi
}

assert_file_not_contains() {
  local file="$1"
  local unexpected="$2"
  local message="$3"

  if grep -Fq -- "$unexpected" "$file"; then
    fail "$message"
  fi
}

assert_event_order() {
  local file="$1"
  local first="$2"
  local second="$3"
  local message="$4"
  local first_line second_line

  first_line="$(awk -v pattern="$first" 'index($0, pattern) { line=NR } END { print line+0 }' "$file")"
  second_line="$(awk -v pattern="$second" 'index($0, pattern) { print NR; exit }' "$file")"
  if [ "$first_line" -eq 0 ] || [ -z "$second_line" ] || [ "$first_line" -ge "$second_line" ]; then
    fail "$message"
  fi
}

prepare_case() {
  local name="$1"

  MOCK_DIR="$TEST_TMP/$name"
  mkdir -p "$MOCK_DIR"
  EVENT_LOG="$MOCK_DIR/events.log"
  : > "$EVENT_LOG"
  printf '0\n' > "$MOCK_DIR/schema-attempts"
  printf '0\n' > "$MOCK_DIR/time"

  MOCK_SCHEMA_FAILURES=0
  MOCK_INSERT_FAILURE=false
  MOCK_USER_QUERY_FAILURE=false
  MOCK_EXISTING_USER_ID=""
  MOCK_SIGNUP_RESPONSE='{"access_token":"token","user":{"id":"new-user-id"}}'
  MOCK_KUBECTL_WAIT_FAILURE=false

  NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS=10
  NEXENT_SQL_MIGRATION_WAIT_INTERVAL_SECONDS=0
  export MOCK_DIR EVENT_LOG MOCK_SCHEMA_FAILURES MOCK_INSERT_FAILURE
  export MOCK_USER_QUERY_FAILURE MOCK_EXISTING_USER_ID MOCK_SIGNUP_RESPONSE
  export MOCK_KUBECTL_WAIT_FAILURE NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS
  export NEXENT_SQL_MIGRATION_WAIT_INTERVAL_SECONDS
}

date() {
  if [ "${1:-}" != "+%s" ]; then
    command date "$@"
    return
  fi

  local value
  value="$(sed -n '1p' "$MOCK_DIR/time")"
  printf '%s\n' "$((value + 1))" > "$MOCK_DIR/time"
  printf '%s\n' "$value"
}

sleep() {
  return 0
}

mock_schema_contract() {
  local attempt
  attempt="$(sed -n '1p' "$MOCK_DIR/schema-attempts")"
  printf '%s\n' "$((attempt + 1))" > "$MOCK_DIR/schema-attempts"
  [ "$attempt" -ge "$MOCK_SCHEMA_FAILURES" ]
}

docker() {
  local command_line="$*"
  printf 'docker %s\n' "$command_line" >> "$EVENT_LOG"

  if [ "$command_line" = "ps" ]; then
    printf '%s\n' 'nexent-config' 'supabase-db-mini'
    return 0
  fi
  if [[ "$command_line" == *"SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by"* ]]; then
    mock_schema_contract
    return $?
  fi
  if [[ "$command_line" == *"INSERT INTO nexent.user_tenant_t"* ]]; then
    [ "$MOCK_INSERT_FAILURE" != "true" ]
    return $?
  fi
  if [[ "$command_line" == *"SELECT id FROM auth.users"* ]]; then
    if [ "$MOCK_USER_QUERY_FAILURE" = "true" ]; then
      return 1
    fi
    printf '%s\n' "$MOCK_EXISTING_USER_ID"
    return 0
  fi
  if [[ "$command_line" == *"command -v jq"* ]]; then
    return 1
  fi
  if [[ "$command_line" == *"curl -s -X POST"* ]]; then
    printf '%s\n' "$MOCK_SIGNUP_RESPONSE"
    return 0
  fi

  return 0
}

kubectl() {
  local command_line="$*"
  printf 'kubectl %s\n' "$command_line" >> "$EVENT_LOG"

  if [[ "$command_line" == wait\ * ]]; then
    [ "$MOCK_KUBECTL_WAIT_FAILURE" != "true" ]
    return $?
  fi
  if [[ "$command_line" == *"SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by"* ]]; then
    mock_schema_contract
    return $?
  fi
  if [[ "$command_line" == *"SELECT 1 FROM auth.users"* ]]; then
    return 0
  fi
  if [[ "$command_line" == *"SELECT id FROM auth.users"* ]]; then
    if [ "$MOCK_USER_QUERY_FAILURE" = "true" ]; then
      return 1
    fi
    printf '%s\n' "$MOCK_EXISTING_USER_ID"
    return 0
  fi
  if [[ "$command_line" == *"INSERT INTO nexent.user_tenant_t"* ]]; then
    [ "$MOCK_INSERT_FAILURE" != "true" ]
    return $?
  fi
  if [[ "$command_line" == *"curl -s -X POST"* ]]; then
    printf '%s\n' "$MOCK_SIGNUP_RESPONSE"
    return 0
  fi
  if [[ "$command_line" == get\ secret\ * ]]; then
    return 0
  fi

  return 0
}

load_docker_script() {
  # Load only function definitions; production scripts always execute their entrypoint.
  # shellcheck source=/dev/null
  source "$TEST_ROOT/deploy/common/common.sh"
  # shellcheck source=/dev/null
  source <(sed -n '/^wait_for_user_tenant_schema_ready()/,/^# Main execution\./p' \
    "$TEST_ROOT/deploy/docker/create-su.sh" | sed '$d')
  set +e

  POSTGRES_USER=root
  POSTGRES_DB=nexent
  SUPABASE_POSTGRES_DB=supabase
  SUPABASE_KEY=test-key
  DEPLOYMENT_VERSION=full
  DEPLOYMENT_MODE=development
  export POSTGRES_USER POSTGRES_DB SUPABASE_POSTGRES_DB SUPABASE_KEY
  export DEPLOYMENT_VERSION DEPLOYMENT_MODE
}

load_k8s_script() {
  # Load only function definitions; production scripts always execute their entrypoint.
  # shellcheck source=/dev/null
  source "$TEST_ROOT/deploy/common/common.sh"
  # shellcheck source=/dev/null
  source <(sed -n '/^prompt_super_admin_password()/,/^# Run main function\./p' \
    "$TEST_ROOT/deploy/k8s/create-suadmin.sh" | sed '$d')
  set +e

  NAMESPACE=nexent
  SUPER_ADMIN_EMAIL=suadmin@nexent.com

  get_supabase_service_role_key() {
    printf '%s\n' 'service-role-key'
  }
  get_supabase_anon_key() {
    printf '%s\n' 'anon-key'
  }
}

test_docker_waits_before_insert() (
  prepare_case docker-waits
  MOCK_SCHEMA_FAILURES=2
  export MOCK_SCHEMA_FAILURES
  load_docker_script

  if ! create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output.log" 2>&1; then
    fail "Docker initialization should succeed after the schema becomes ready"
    return
  fi
  assert_event_order "$EVENT_LOG" \
    "curl -s -X POST" \
    "SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by" \
    "Docker should check the schema only when it is ready to insert"
  assert_event_order "$EVENT_LOG" \
    "SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by" \
    "INSERT INTO nexent.user_tenant_t" \
    "Docker must wait for the schema contract immediately before INSERT"
)

test_docker_timeout_prevents_insert() (
  prepare_case docker-timeout
  MOCK_SCHEMA_FAILURES=99
  NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS=1
  export MOCK_SCHEMA_FAILURES NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS
  load_docker_script

  if create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output.log" 2>&1; then
    fail "Docker schema timeout should fail initialization"
    return
  fi
  assert_file_contains "$EVENT_LOG" "curl -s -X POST" \
    "Docker should reach signup before checking the insert schema"
  assert_file_not_contains "$EVENT_LOG" "INSERT INTO nexent.user_tenant_t" \
    "Docker schema timeout must prevent INSERT"
)

test_docker_insert_failure_is_fatal() (
  prepare_case docker-insert-failure
  MOCK_INSERT_FAILURE=true
  export MOCK_INSERT_FAILURE
  load_docker_script

  if create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output.log" 2>&1; then
    fail "Docker INSERT failure should fail initialization"
  fi
)

test_docker_existing_user_repairs_idempotently() (
  prepare_case docker-existing
  MOCK_EXISTING_USER_ID=existing-user-id
  MOCK_SIGNUP_RESPONSE='{"error_code":"user_already_exists"}'
  export MOCK_EXISTING_USER_ID MOCK_SIGNUP_RESPONSE
  load_docker_script

  if ! create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output-1.log" 2>&1 || \
    ! create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output-2.log" 2>&1; then
    fail "Docker should repair an existing user's tenant relationship on every retry"
    return
  fi
  assert_file_contains "$EVENT_LOG" "ON CONFLICT (user_id, tenant_id) DO NOTHING" \
    "Docker repair INSERT should be idempotent"
)

test_docker_user_query_failure_is_fatal() (
  prepare_case docker-query-failure
  MOCK_USER_QUERY_FAILURE=true
  MOCK_SIGNUP_RESPONSE='{"error_code":"user_already_exists"}'
  export MOCK_USER_QUERY_FAILURE MOCK_SIGNUP_RESPONSE
  load_docker_script

  if create_default_super_admin_user 'ValidAdmin123' false > "$MOCK_DIR/output.log" 2>&1; then
    fail "Docker existing user query failure should fail initialization"
  fi
)

test_k8s_waits_before_insert() (
  prepare_case k8s-waits
  MOCK_SCHEMA_FAILURES=2
  export MOCK_SCHEMA_FAILURES
  load_k8s_script

  if ! create_supabase_super_admin_user > "$MOCK_DIR/output.log" 2>&1; then
    fail "K8s initialization should succeed after the schema becomes ready"
    return
  fi
  assert_event_order "$EVENT_LOG" \
    "curl -s -X POST" \
    "SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by" \
    "K8s should check the schema only when it is ready to insert"
  assert_event_order "$EVENT_LOG" \
    "SELECT user_id, tenant_id, user_role, user_email, created_by, updated_by" \
    "INSERT INTO nexent.user_tenant_t" \
    "K8s must wait for the schema contract immediately before INSERT"
)

test_k8s_timeout_prevents_insert() (
  prepare_case k8s-timeout
  MOCK_SCHEMA_FAILURES=99
  NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS=1
  export MOCK_SCHEMA_FAILURES NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS
  load_k8s_script

  if create_supabase_super_admin_user > "$MOCK_DIR/output.log" 2>&1; then
    fail "K8s schema timeout should fail initialization"
    return
  fi
  assert_file_contains "$EVENT_LOG" "curl -s -X POST" \
    "K8s should reach signup before checking the insert schema"
  assert_file_not_contains "$EVENT_LOG" "INSERT INTO nexent.user_tenant_t" \
    "K8s schema timeout must prevent INSERT"
)

test_k8s_insert_failure_is_fatal() (
  prepare_case k8s-insert-failure
  MOCK_INSERT_FAILURE=true
  export MOCK_INSERT_FAILURE
  load_k8s_script

  if create_supabase_super_admin_user > "$MOCK_DIR/output.log" 2>&1; then
    fail "K8s INSERT failure should fail initialization"
  fi
)

test_k8s_existing_user_repairs_idempotently() (
  prepare_case k8s-existing
  MOCK_EXISTING_USER_ID=existing-user-id
  export MOCK_EXISTING_USER_ID
  load_k8s_script

  if ! create_supabase_super_admin_user > "$MOCK_DIR/output-1.log" 2>&1 || \
    ! create_supabase_super_admin_user > "$MOCK_DIR/output-2.log" 2>&1; then
    fail "K8s should repair an existing user's tenant relationship on every retry"
    return
  fi
  assert_file_not_contains "$EVENT_LOG" "curl -s -X POST" \
    "K8s existing-user recovery must not recreate the Supabase user"
  assert_file_contains "$EVENT_LOG" "ON CONFLICT (user_id, tenant_id) DO NOTHING" \
    "K8s repair INSERT should be idempotent"
)

test_k8s_user_query_failure_is_fatal() (
  prepare_case k8s-query-failure
  MOCK_USER_QUERY_FAILURE=true
  export MOCK_USER_QUERY_FAILURE
  load_k8s_script

  if create_supabase_super_admin_user > "$MOCK_DIR/output.log" 2>&1; then
    fail "K8s existing user query failure should fail initialization"
  fi
)

test_k8s_pod_readiness_failure_is_fatal() (
  prepare_case k8s-pod-failure
  MOCK_KUBECTL_WAIT_FAILURE=true
  export MOCK_KUBECTL_WAIT_FAILURE
  load_k8s_script

  if main > "$MOCK_DIR/output.log" 2>&1; then
    fail "K8s pod readiness failure should fail initialization"
  fi
)

run_test() {
  local name="$1"
  local test_function="$2"

  if "$test_function"; then
    echo "PASS: $name"
    return 0
  fi
  return 1
}

run_test "Docker waits for the schema before INSERT" test_docker_waits_before_insert || exit 1
run_test "Docker timeout prevents INSERT" test_docker_timeout_prevents_insert || exit 1
run_test "Docker INSERT failure is fatal" test_docker_insert_failure_is_fatal || exit 1
run_test "Docker existing-user repair is idempotent" test_docker_existing_user_repairs_idempotently || exit 1
run_test "Docker user query failure is fatal" test_docker_user_query_failure_is_fatal || exit 1
run_test "K8s waits for the schema before INSERT" test_k8s_waits_before_insert || exit 1
run_test "K8s timeout prevents INSERT" test_k8s_timeout_prevents_insert || exit 1
run_test "K8s INSERT failure is fatal" test_k8s_insert_failure_is_fatal || exit 1
run_test "K8s existing-user repair is idempotent" test_k8s_existing_user_repairs_idempotently || exit 1
run_test "K8s user query failure is fatal" test_k8s_user_query_failure_is_fatal || exit 1
run_test "K8s pod readiness failure is fatal" test_k8s_pod_readiness_failure_is_fatal || exit 1

echo "All super admin initialization tests passed."
