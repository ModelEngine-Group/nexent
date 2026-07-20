#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
MIGRATION_RUNNER="${NEXENT_SQL_MIGRATION_RUNNER:-$SCRIPT_DIR/run-sql-migrations.sh}"

if ! command -v psql >/dev/null 2>&1; then
  printf '[local-sql-migrations] ERROR: PostgreSQL psql is required on PATH.\n' >&2
  exit 1
fi

psql_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s' "$1"
  fi
}

export NEXENT_SQL_INIT_FILE="${NEXENT_SQL_INIT_FILE:-$(psql_path "$REPOSITORY_ROOT/deploy/sql/init.sql")}"
export NEXENT_SQL_MIGRATION_DIR="${NEXENT_SQL_MIGRATION_DIR:-$(psql_path "$REPOSITORY_ROOT/deploy/sql/migrations")}"

if [ "$#" -eq 0 ]; then
  set -- --migrate
fi

"$MIGRATION_RUNNER" "$@"

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-root}"
POSTGRES_DB="${POSTGRES_DB:-nexent}"
POSTGRES_PASSWORD="${NEXENT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"
MIGRATION_TABLE="${NEXENT_SQL_MIGRATION_TABLE:-nexent.schema_migrations}"
MIGRATION_SCHEMA="${MIGRATION_TABLE%.*}"
MIGRATION_TABLE_NAME="${MIGRATION_TABLE##*.}"

if [ "$MIGRATION_SCHEMA" = "$MIGRATION_TABLE_NAME" ]; then
  MIGRATION_SCHEMA="public"
fi

validation_status="$(
  PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -Atqc "
SELECT CASE
  WHEN NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'nexent'
      AND table_name = 'nl2agent_session_t'
      AND column_name = 'runner_agent_id'
  ) THEN 'missing_runner_column'
  WHEN NOT EXISTS (
    SELECT 1
    FROM \"$MIGRATION_SCHEMA\".\"$MIGRATION_TABLE_NAME\"
    WHERE migration_id = 'v2.3.0_0718_persist_nl2agent_runner.sql'
      AND status IN ('applied', 'baselined')
  ) THEN 'missing_migration_record'
  WHEN EXISTS (
    SELECT 1
    FROM nexent.nl2agent_session_t
    WHERE status = 'active'
      AND delete_flag <> 'Y'
      AND runner_agent_id IS NULL
  ) THEN 'active_session_without_runner'
  ELSE 'ready'
END;" | tr -d '[:space:]'
)"

if [ "$validation_status" != "ready" ]; then
  printf '[local-sql-migrations] ERROR: NL2AGENT schema validation failed: %s\n' "$validation_status" >&2
  if [ "$validation_status" = "active_session_without_runner" ]; then
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -h "$POSTGRES_HOST" \
      -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" \
      -d "$POSTGRES_DB" \
      -c "
SELECT tenant_id, count(*) AS affected_sessions
FROM nexent.nl2agent_session_t
WHERE status = 'active'
  AND delete_flag <> 'Y'
  AND runner_agent_id IS NULL
GROUP BY tenant_id
ORDER BY tenant_id;"
  fi
  exit 1
fi

printf '[local-sql-migrations] Database schema is ready.\n'
