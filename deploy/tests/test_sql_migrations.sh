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

assert_file_not_contains() {
  local file="$1"
  local needle="$2"
  local message="$3"
  if grep -Fq "$needle" "$file"; then
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
CREATE TABLE IF NOT EXISTS nexent.test_table(id int);
ALTER TABLE nexent.test_table ADD COLUMN IF NOT EXISTS name text;
SQL
cat > "$SQL_DIR/v2_test.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS nexent.test_table_v2(id int);
SQL

SYMLINK_SQL_DIR="$TMP_DIR/sql/migrations-link"
ln -s "$SQL_DIR" "$SYMLINK_SQL_DIR" 2>/dev/null || cp -R "$SQL_DIR" "$SYMLINK_SQL_DIR"

INIT_SQL_FILE="$TMP_DIR/init.sql"
printf 'create schema if not exists nexent;\ncreate table if not exists nexent.model_record_t(id int);\ncreate table if not exists nexent.knowledge_record_t(id int);\ncreate table if not exists nexent.ag_tenant_agent_t(id int);\ncreate table if not exists nexent.conversation_record_t(id int);\ncreate table if not exists nexent.conversation_message_t(id int);\ncreate table if not exists nexent.ag_tool_info_t(id int);\n' > "$INIT_SQL_FILE"

if grep -Eq '^COMMENT ON COLUMN nexent\.ag_tenant_agent_t\.prompt ' "$DEPLOY_ROOT/sql/init.sql"; then
  fail "init SQL should not comment ag_tenant_agent_t.prompt because a later migration drops that column"
fi
if grep -Eq '^COMMENT ON COLUMN nexent\.model_record_t\.is_deep_thinking ' "$DEPLOY_ROOT/sql/init.sql"; then
  fail "init SQL should not comment model_record_t.is_deep_thinking because a later migration drops that column"
fi

PLAN_FILE="$TMP_DIR/plan.sql"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$PLAN_FILE" \
CAPTURE_QUERY="" \
NEXENT_SQL_INIT_FILE="$INIT_SQL_FILE" \
NEXENT_SQL_MIGRATION_DIR="$SYMLINK_SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
NEXENT_APP_VERSION="v-test" \
  bash "$MIGRATION_SCRIPT" --migrate >/tmp/nexent-sql-migration-test.log

[ -f "$PLAN_FILE" ] || fail "migration plan should be captured"
assert_file_contains "$PLAN_FILE" "pg_advisory_lock" "plan should acquire advisory lock"
assert_file_contains "$PLAN_FILE" "pg_advisory_unlock" "plan should release advisory lock"
assert_file_contains "$PLAN_FILE" "status text NOT NULL DEFAULT 'applied'" "plan should create extended migration table status"
assert_file_contains "$PLAN_FILE" "app_version text" "plan should create app_version field"
assert_file_contains "$PLAN_FILE" "source_file text" "plan should create source_file field"
assert_file_contains "$PLAN_FILE" "CHECK (status IN ('applied', 'baselined'))" "plan should keep compatibility with prior baselined records"
assert_file_not_contains "$PLAN_FILE" "_nexent_migration_probe_result" "plan should not use probe temp tables"
assert_file_not_contains "$PLAN_FILE" "nexent-migration-probe" "plan should not require SQL marker comments"
assert_file_contains "$PLAN_FILE" "\\i '$INIT_SQL_FILE'" "plan should always apply init SQL"
assert_file_contains "$PLAN_FILE" "VALUES ('__init.sql'" "plan should record init SQL"
assert_file_contains "$PLAN_FILE" "'applied', 'v-test'" "plan should record applied status and app version"
assert_file_contains "$PLAN_FILE" "ON CONFLICT (migration_id) DO UPDATE SET" "plan should update migration records after execution"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] check v1_merged_migrations.sql" "plan should check migrations by file name"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] skip v1_merged_migrations.sql" "plan should skip matching checksums"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] apply v1_merged_migrations.sql" "plan should apply new migration files"
assert_file_contains "$PLAN_FILE" "\\echo [sql-migrations] reapply v1_merged_migrations.sql" "plan should reapply changed migration files"
assert_file_contains "$PLAN_FILE" "migration_checksum_matched" "plan should compare recorded checksum with current file checksum"
assert_file_contains "$PLAN_FILE" "executed_at = now()" "plan should refresh execution time on reapply"
assert_file_contains "$PLAN_FILE" "SET search_path TO \"nexent\", public;" "plan should set search path for legacy migrations"

first_check="$(grep -nF '\echo [sql-migrations] check v' "$PLAN_FILE" | head -1 | cut -d: -f2-)"
[ "$first_check" = "\\echo [sql-migrations] check v1_merged_migrations.sql" ] || fail "migrations should be sorted before execution"

WAIT_QUERY_FILE="$TMP_DIR/wait-query.sql"
WAIT_TABLE_PLAN="$TMP_DIR/wait-table-plan.sql"
PATH="$BIN_DIR:$PATH" \
CAPTURE_PLAN="$WAIT_TABLE_PLAN" \
CAPTURE_QUERY="$WAIT_QUERY_FILE" \
FAKE_WAIT_STATUS="ready" \
NEXENT_SQL_INIT_FILE="$INIT_SQL_FILE" \
NEXENT_SQL_MIGRATION_DIR="$SYMLINK_SQL_DIR" \
NEXENT_SQL_WAIT_TIMEOUT_SECONDS=1 \
  bash "$MIGRATION_SCRIPT" --wait >/tmp/nexent-sql-migration-wait-test.log

[ -f "$WAIT_TABLE_PLAN" ] || fail "wait mode should ensure migration table"
[ -f "$WAIT_QUERY_FILE" ] || fail "wait mode should query migration target state"
assert_file_contains "$WAIT_QUERY_FILE" "__init.sql" "wait query should include init migration target"
assert_file_contains "$WAIT_QUERY_FILE" "v1_merged_migrations.sql" "wait query should include file-name migration target"
assert_file_contains "$WAIT_QUERY_FILE" "v2_test.sql" "wait query should include all migration files"
assert_file_contains "$WAIT_QUERY_FILE" "actual_checksum = expected_checksum" "wait query should wait for current checksums"
assert_file_contains "$WAIT_QUERY_FILE" "status IN ('applied', 'baselined')" "wait query should accept applied and prior baselined records"
assert_file_not_contains "$WAIT_QUERY_FILE" "checksum_mismatch" "wait mode should allow migrator to reapply checksum changes"

if grep -R -n '^-- nexent-migration-' "$DEPLOY_ROOT/sql/migrations" --include='*.sql' >/tmp/nexent-sql-marker-check.log; then
  cat /tmp/nexent-sql-marker-check.log
  fail "migration SQL files should not contain nexent-migration marker comments"
fi

if grep -R -n 'nexent-migration-' "$DEPLOY_ROOT/common/run-sql-migrations.sh" >/tmp/nexent-runner-marker-check.log; then
  cat /tmp/nexent-runner-marker-check.log
  fail "migration runner should not parse nexent-migration marker comments"
fi

echo "All SQL migration tests passed."
