#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_SQL="$DEPLOY_ROOT/sql/migrations/v2.5.2_unified_tag_management.sql"
INIT_SQL="$DEPLOY_ROOT/sql/init.sql"
POSTGRES_TEST_IMAGE="${POSTGRES_TEST_IMAGE:-postgres:15-alpine}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
POSTGRES_PASSWORD="dtp-test-password"
CONTAINER_NAME="nexent-dtp-test-$$-${RANDOM}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nexent-dtp-test.XXXXXX")"
CONTAINER_STARTED=false

cleanup() {
  if [ "$CONTAINER_STARTED" = true ]; then
    "$DOCKER_BIN" stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [ "$actual" != "$expected" ]; then
    fail "$message (expected='$expected', actual='$actual')"
  fi
}

require_prerequisites() {
  command -v "$DOCKER_BIN" >/dev/null 2>&1 || fail "docker command not found: $DOCKER_BIN"
  [ -f "$MIGRATION_SQL" ] || fail "migration SQL not found: $MIGRATION_SQL"
  [ -f "$INIT_SQL" ] || fail "init SQL not found: $INIT_SQL"
}

start_postgres() {
  "$DOCKER_BIN" run --rm -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    "$POSTGRES_TEST_IMAGE" >/dev/null
  CONTAINER_STARTED=true

  local attempt
  for attempt in {1..30}; do
    if "$DOCKER_BIN" exec "$CONTAINER_NAME" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
      pass "PostgreSQL container is ready ($POSTGRES_TEST_IMAGE)"
      return
    fi
    sleep 1
  done
  fail "PostgreSQL container did not become ready"
}

create_database() {
  local database="$1"
  "$DOCKER_BIN" exec "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -c "CREATE DATABASE \"$database\"" >/dev/null
}

run_sql() {
  local database="$1"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q
}

run_file() {
  local database="$1"
  local file="$2"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q < "$file"
}

run_file_with_search_path() {
  local database="$1"
  local file="$2"
  "$DOCKER_BIN" exec -e PGOPTIONS="-c search_path=nexent,public" -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U root -d "$database" -A -t -q < "$file"
}

run_migration_files_through() {
  local database="$1"
  local stop_at="$2"
  local migration_file
  while IFS= read -r migration_file; do
    run_file_with_search_path "$database" "$migration_file" >/dev/null
    if [ "$(basename "$migration_file")" = "$stop_at" ]; then
      return
    fi
  done < <(printf '%s
' "$DEPLOY_ROOT"/sql/migrations/*.sql | sort -V)
  fail "migration boundary not found: $stop_at"
}

assert_query() {
  local database="$1"
  local sql="$2"
  local expected="$3"
  local message="$4"
  local actual
  actual="$(run_sql "$database" <<< "$sql")"
  assert_eq "$expected" "$actual" "$message"
}

test_migration_ddl() {
  local database="dtp_migration"
  create_database "$database"

  run_sql "$database" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'root') THEN
        CREATE ROLE root LOGIN SUPERUSER;
    END IF;
END;
$$;
SQL
  run_file "$database" "$INIT_SQL" >/dev/null
  run_migration_files_through "$database" "v2.5.2_unified_tag_management.sql"
  assert_query "$database" \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name = 'document_tag_projection';" \
    "1" "migration creates document_tag_projection table"
  assert_query "$database" \
    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'nexent' AND indexname IN ('idx_document_tag_projection_tenant_status', 'idx_document_tag_projection_kb', 'idx_document_tag_projection_resource');" \
    "3" "migration creates the projection lookup indexes"
  assert_query "$database" \
    "SELECT count(*) FROM pg_constraint AS c JOIN pg_class AS cl ON cl.oid = c.conrelid JOIN pg_namespace AS ns ON ns.oid = cl.relnamespace WHERE ns.nspname = 'nexent' AND cl.relname = 'document_tag_projection' AND c.conname = 'uq_document_tag_projection_identity';" \
    "1" "migration creates the document identity unique constraint"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name = 'document_tag_projection';" \
    "1" "migration rerun is idempotent"
  pass "document tag projection remains valid after the consolidated migration reruns"
}

test_fresh_install_requires_versioned_tag_migration() {
  local database="dtp_init"
  create_database "$database"
  run_file "$database" "$INIT_SQL" >/dev/null
  assert_query "$database" \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name IN ('tag_bucket', 'tag_bucket_resource_type', 'tag_definition', 'tag_value', 'resource_tag_assignment', 'document_tag_projection');" \
    "0" "init.sql must not create unified tag management tables"
  assert_query "$database" \
    "SELECT count(*) FROM pg_proc AS procedure JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace WHERE namespace.nspname = 'nexent' AND procedure.proname IN ('provision_unified_tag_management', 'provision_unified_tag_management_after_user_tenant_insert', 'enforce_tag_definition_limit', 'enforce_tag_value_limit', 'enforce_resource_tag_assignment_rules');" \
    "0" "init.sql must not create unified tag management functions"

  run_migration_files_through "$database" "v2.5.2_unified_tag_management.sql"
  assert_query "$database" \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name IN ('tag_bucket', 'tag_bucket_resource_type', 'tag_definition', 'tag_value', 'resource_tag_assignment', 'document_tag_projection');" \
    "6" "the versioned migration chain must create all unified tag management tables"
  pass "fresh installs receive the unified tag schema only through versioned migrations"
}

main() {
  require_prerequisites
  start_postgres
  test_migration_ddl
  test_fresh_install_requires_versioned_tag_migration
  echo "PASS: all document tag projection SQL tests passed"
}

main "$@"
