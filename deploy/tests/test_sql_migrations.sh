#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_SCRIPT="$DEPLOY_ROOT/common/run-sql-migrations.sh"
TMP_DIR="${TMPDIR:-/tmp}/nexent-sql-migration-test-$$"
SQL_DIR="$TMP_DIR/sql/migrations"
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
  if ! grep -Fq "$needle" "$file"; then
    fail "$message"
  fi
}

create_fake_psql() {
  cat > "$BIN_DIR/psql" <<'SH'
#!/bin/sh
prev=""
capture_next_query=false
for arg in "$@"; do
  if [ "$prev" = "-f" ]; then
    if [ -n "$CAPTURE_PLAN" ]; then
      cp "$arg" "$CAPTURE_PLAN"
    fi
    exit 0
  fi
  if [ "$prev" = "-c" ] || [ "$capture_next_query" = true ]; then
    if [ -n "$CAPTURE_QUERY" ]; then
      printf '%s\n' "$arg" >> "$CAPTURE_QUERY"
    fi
    case "$arg" in
      "SELECT 1")
        printf '1\n'
        ;;
      *)
        printf '%s\n' "${FAKE_WAIT_STATUS:-ready}"
        ;;
    esac
    exit 0
  fi
  case "$arg" in
    -*c*)
      capture_next_query=true
      ;;
  esac
  prev="$arg"
done
cat >/dev/null
exit 0
SH
  chmod +x "$BIN_DIR/psql"
}

create_fake_psql

cat > "$SQL_DIR/v1_merged_migrations.sql" <<'SQL'
-- nexent-migration-source: v1_test.sql
-- nexent-migration-checksum: checksum-v1
-- nexent-migration-probe: SELECT to_regclass('nexent.test_table') IS NOT NULL;
CREATE TABLE IF NOT EXISTS nexent.test_table(id int);
-- nexent-migration-source: v1_second.sql
-- nexent-migration-checksum: checksum-v1-second
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'test_table' AND column_name = 'name');
ALTER TABLE nexent.test_table ADD COLUMN IF NOT EXISTS name text;
SQL
cat > "$SQL_DIR/v2_test.sql" <<'SQL'
-- nexent-migration-checksum: checksum-v2
-- nexent-migration-probe: SELECT to_regclass('nexent.test_table_v2') IS NOT NULL;
CREATE TABLE IF NOT EXISTS nexent.test_table_v2(id int);
SQL
INIT_SQL_FILE="$TMP_DIR/init.sql"
printf 'create schema if not exists nexent;\ncreate table if not exists nexent.model_record_t(id int);\ncreate table if not exists nexent.knowledge_record_t(id int);\ncreate table if not exists nexent.ag_tenant_agent_t(id int);\ncreate table if not exists nexent.conversation_record_t(id int);\ncreate table if not exists nexent.conversation_message_t(id int);\ncreate table if not exists nexent.ag_tool_info_t(id int);\n' > "$INIT_SQL_FILE"

PLAN_FILE="$TMP_DIR/plan.sql"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$PLAN_FILE" \
CAPTURE_QUERY="" \
NEXENT_SQL_INIT_FILE="$INIT_SQL_FILE" \
NEXENT_SQL_MIGRATION_DIR="$SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
NEXENT_APP_VERSION="v-test" \
  bash "$MIGRATION_SCRIPT" --migrate >/tmp/nexent-sql-migration-test.log

[ -f "$PLAN_FILE" ] || fail "migration plan should be captured"
assert_file_contains "$PLAN_FILE" "pg_advisory_lock" "plan should acquire advisory lock"
assert_file_contains "$PLAN_FILE" "pg_advisory_unlock" "plan should release advisory lock"
assert_file_contains "$PLAN_FILE" "status text NOT NULL DEFAULT 'applied'" "plan should create extended migration table status"
assert_file_contains "$PLAN_FILE" "app_version text" "plan should create app_version field"
assert_file_contains "$PLAN_FILE" "source_file text" "plan should create source_file field"
assert_file_contains "$PLAN_FILE" "CHECK (status IN ('applied', 'baselined'))" "plan should constrain migration status"
assert_file_contains "$PLAN_FILE" "CREATE TEMP TABLE _nexent_migration_probe_result(probe_result boolean);" "plan should keep probe temp table for the psql session"
if grep -Fq "ON COMMIT DROP" "$PLAN_FILE"; then
  fail "probe temp table should not be dropped on transaction commit"
fi
assert_file_contains "$PLAN_FILE" "SELECT CASE WHEN to_regclass('nexent.model_record_t') IS NOT NULL" "plan should check required base objects"
assert_file_contains "$PLAN_FILE" "\\i '$INIT_SQL_FILE'" "plan should apply init SQL for an empty database"
assert_file_contains "$PLAN_FILE" "VALUES ('__init.sql'" "plan should record init SQL"
assert_file_contains "$PLAN_FILE" "'applied', 'v-test'" "plan should record applied status and app version"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] baseline __init.sql" "plan should support init baseline mode"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] probe v1_test.sql" "plan should probe bundle source migrations"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] baseline v1_test.sql" "plan should baseline probed migrations"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] apply v1_test.sql" "plan should apply unprobed-current migrations"
assert_file_contains "$PLAN_FILE" "checksum-v1" "plan should preserve source migration checksum from bundle metadata"
assert_file_contains "$PLAN_FILE" "checksum-v2" "plan should preserve standalone migration checksum metadata"
assert_file_contains "$PLAN_FILE" "RAISE EXCEPTION 'checksum changed" "plan should fail on checksum changes"
assert_file_contains "$PLAN_FILE" "SET search_path TO \"nexent\", public;" "plan should set search path for legacy migrations"

first_check="$(grep -nF '\echo [sql-migrations] check v' "$PLAN_FILE" | head -1 | cut -d: -f2-)"
[ "$first_check" = "\\echo [sql-migrations] check v1_test.sql" ] || fail "migrations should be sorted before execution"

WAIT_QUERY_FILE="$TMP_DIR/wait-query.sql"
WAIT_TABLE_PLAN="$TMP_DIR/wait-table-plan.sql"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$WAIT_TABLE_PLAN" \
CAPTURE_QUERY="$WAIT_QUERY_FILE" \
FAKE_WAIT_STATUS="ready" \
NEXENT_SQL_INIT_FILE="$INIT_SQL_FILE" \
NEXENT_SQL_MIGRATION_DIR="$SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
  bash "$MIGRATION_SCRIPT" --wait >/tmp/nexent-sql-migration-wait-test.log

[ -f "$WAIT_TABLE_PLAN" ] || fail "wait mode should ensure migration table"
[ -f "$WAIT_QUERY_FILE" ] || fail "wait mode should query migration target state"
assert_file_contains "$WAIT_QUERY_FILE" "__init.sql" "wait query should include init migration target"
assert_file_contains "$WAIT_QUERY_FILE" "v1_test.sql" "wait query should include bundle source target"
assert_file_contains "$WAIT_QUERY_FILE" "v1_second.sql" "wait query should include all bundle sources"
assert_file_contains "$WAIT_QUERY_FILE" "v2_test.sql" "wait query should include standalone migration target"
assert_file_contains "$WAIT_QUERY_FILE" "checksum_mismatch" "wait query should fail fast on checksum mismatch"
assert_file_contains "$WAIT_QUERY_FILE" "status IN ('applied', 'baselined')" "wait query should accept applied and baselined records"

SOURCE_COUNT="$(awk '/^-- nexent-migration-source: / {count++} END {print count + 0}' "$DEPLOY_ROOT"/sql/migrations/*.sql)"
CHECKSUM_COUNT="$(awk '/^-- nexent-migration-checksum: / {count++} END {print count + 0}' "$DEPLOY_ROOT"/sql/migrations/*.sql)"
PROBE_COUNT="$(awk '/^-- nexent-migration-probe: / {count++} END {print count + 0}' "$DEPLOY_ROOT"/sql/migrations/*.sql)"
[ "$SOURCE_COUNT" -gt 0 ] || fail "real migration files should contain source markers"
[ "$SOURCE_COUNT" = "$CHECKSUM_COUNT" ] || fail "every real migration source should have a checksum"
[ "$SOURCE_COUNT" = "$PROBE_COUNT" ] || fail "every real migration source should have a probe"

DUPLICATE_SOURCE="$(awk '/^-- nexent-migration-source: / {source=$0; sub(/^-- nexent-migration-source: /, "", source); count[source]++} END {for (source in count) if (count[source] > 1) print source}' "$DEPLOY_ROOT"/sql/migrations/*.sql | head -1)"
[ -z "$DUPLICATE_SOURCE" ] || fail "migration source should be unique: $DUPLICATE_SOURCE"

echo "All SQL migration tests passed."
