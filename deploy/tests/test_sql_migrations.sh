#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_SCRIPT="$SCRIPT_DIR/../common/run-sql-migrations.sh"
TMP_DIR="${TMPDIR:-/tmp}/nexent-sql-migration-test-$$"
SQL_DIR="$TMP_DIR/sql"
BIN_DIR="$TMP_DIR/bin"

mkdir -p "$SQL_DIR" "$BIN_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "FAIL: $*"
  exit 1
}

assert_file_contains() {
  local file="$1"
  local needle="$2"
  local message="$3"
  if ! grep -q "$needle" "$file"; then
    fail "$message"
  fi
}

create_fake_psql() {
  cat > "$BIN_DIR/psql" <<'SH'
#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-f" ]; then
    cp "$2" "$CAPTURE_PLAN"
    exit 0
  fi
  shift
done
cat >/dev/null
exit 0
SH
  chmod +x "$BIN_DIR/psql"
}

create_fake_psql

printf 'select 2;\n' > "$SQL_DIR/v2_test.sql"
printf 'select 1;\n' > "$SQL_DIR/v1_test.sql"

PLAN_FILE="$TMP_DIR/plan.sql"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$PLAN_FILE" \
NEXENT_SQL_MIGRATION_DIR="$SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
  bash "$MIGRATION_SCRIPT" >/tmp/nexent-sql-migration-test.log

[ -f "$PLAN_FILE" ] || fail "migration plan should be captured"
assert_file_contains "$PLAN_FILE" "pg_advisory_lock" "plan should acquire advisory lock"
assert_file_contains "$PLAN_FILE" "pg_advisory_unlock" "plan should release advisory lock"
assert_file_contains "$PLAN_FILE" "CREATE TABLE IF NOT EXISTS" "plan should create migration table"
assert_file_contains "$PLAN_FILE" "schema_migrations" "plan should use migration table"
assert_file_contains "$PLAN_FILE" "RAISE EXCEPTION 'checksum changed" "plan should fail on checksum changes"
assert_file_contains "$PLAN_FILE" "INSERT INTO" "plan should record applied migrations"

first_apply="$(grep -n 'apply v' "$PLAN_FILE" | head -1 | cut -d: -f2-)"
[ "$first_apply" = "\\echo [sql-migrations] apply v1_test.sql" ] || fail "migrations should be sorted before execution"

EMPTY_SQL_DIR="$TMP_DIR/empty-sql"
EMPTY_PLAN_FILE="$TMP_DIR/empty-plan.sql"
mkdir -p "$EMPTY_SQL_DIR"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$EMPTY_PLAN_FILE" \
NEXENT_SQL_MIGRATION_DIR="$EMPTY_SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
  bash "$MIGRATION_SCRIPT" >/tmp/nexent-sql-migration-empty-test.log

[ -f "$EMPTY_PLAN_FILE" ] || fail "empty migration plan should be captured"
assert_file_contains "$EMPTY_PLAN_FILE" "pg_advisory_lock" "empty plan should acquire advisory lock"
assert_file_contains "$EMPTY_PLAN_FILE" "pg_advisory_unlock" "empty plan should release advisory lock"
assert_file_contains "$EMPTY_PLAN_FILE" "CREATE TABLE IF NOT EXISTS" "empty plan should create migration table"

echo "All SQL migration tests passed."
