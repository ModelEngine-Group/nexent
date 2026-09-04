#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_SQL="$DEPLOY_ROOT/sql/migrations/v2.5.2_0818_document_tag_projection.sql"
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
  "$DOCKER_BIN" run --rm -d +    --name "$CONTAINER_NAME" +    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" +    "$POSTGRES_TEST_IMAGE" >/dev/null
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
  "$DOCKER_BIN" exec "$CONTAINER_NAME" +    psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres +    -c "CREATE DATABASE \"$database\"" >/dev/null
}

run_sql() {
  local database="$1"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" +    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q
}

run_file() {
  local database="$1"
  local file="$2"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" +    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q < "$file"
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

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" +    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name = 'document_tag_projection';" +    "1" "migration creates document_tag_projection table"
  assert_query "$database" +    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'nexent' AND indexname IN ('idx_document_tag_projection_tenant_status', 'idx_document_tag_projection_kb', 'idx_document_tag_projection_resource');" +    "3" "migration creates the projection lookup indexes"
  assert_query "$database" +    "SELECT count(*) FROM pg_constraint AS c JOIN pg_class AS cl ON cl.oid = c.conrelid JOIN pg_namespace AS ns ON ns.oid = cl.relnamespace WHERE ns.nspname = 'nexent' AND cl.relname = 'document_tag_projection' AND c.conname = 'uq_document_tag_projection_identity';" +    "1" "migration creates the document identity unique constraint"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" +    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name = 'document_tag_projection';" +    "1" "migration rerun is idempotent"
  pass "document tag projection migration DDL and rerun idempotency"
}

test_init_sql_fresh_schema() {
  local database="dtp_init"
  create_database "$database"
  run_file "$database" "$INIT_SQL" >/dev/null
  assert_query "$database" +    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nexent' AND table_name = 'document_tag_projection';" +    "1" "init.sql creates document_tag_projection for fresh installs"
  pass "fresh install init.sql includes the document tag projection ledger"
}

main() {
  require_prerequisites
  start_postgres
  test_migration_ddl
  test_init_sql_fresh_schema
  echo "PASS: all document tag projection SQL tests passed"
}

main "$@"
