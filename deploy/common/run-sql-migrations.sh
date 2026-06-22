#!/usr/bin/env bash

set -euo pipefail

MIGRATION_DIR="${NEXENT_SQL_MIGRATION_DIR:-/opt/nexent/sql}"
MIGRATION_TABLE="${NEXENT_SQL_MIGRATION_TABLE:-nexent.schema_migrations}"
LOCK_KEY="${NEXENT_SQL_MIGRATION_LOCK_KEY:-nexent_sql_migrations}"

POSTGRES_HOST="${POSTGRES_HOST:-nexent-postgresql}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-root}"
POSTGRES_DB="${POSTGRES_DB:-nexent}"
POSTGRES_PASSWORD="${NEXENT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"

log() {
  printf '[sql-migrations] %s\n' "$*"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    log "ERROR: sha256sum or shasum is required"
    exit 1
  fi
}

psql_base() {
  PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 \
    "$@"
}

escape_sql_literal() {
  printf "%s" "$1" | sed "s/'/''/g"
}

split_migration_table() {
  MIGRATION_SCHEMA="${MIGRATION_TABLE%.*}"
  MIGRATION_TABLE_NAME="${MIGRATION_TABLE##*.}"
  if [ "$MIGRATION_SCHEMA" = "$MIGRATION_TABLE_NAME" ]; then
    MIGRATION_SCHEMA="public"
  fi
}

wait_for_postgres() {
  local timeout="${NEXENT_SQL_WAIT_TIMEOUT_SECONDS:-120}"
  local start
  start="$(date +%s)"
  until psql_base -Atqc "SELECT 1" >/dev/null 2>&1; do
    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      log "ERROR: PostgreSQL did not become ready within ${timeout}s"
      return 1
    fi
    sleep 2
  done
}

run_one_migration() {
  local file="$1"
  local migration_id checksum escaped_file
  migration_id="$(basename "$file")"
  checksum="$(sha256_file "$file")"
  escaped_file="$(escape_sql_literal "$file")"

  cat >> "$MIGRATION_PLAN_FILE" <<SQL
\echo [sql-migrations] check $migration_id
DO \$\$
DECLARE existing_checksum text;
BEGIN
  SELECT checksum INTO existing_checksum
  FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
  WHERE migration_id = '$(escape_sql_literal "$migration_id")';

  IF existing_checksum IS NOT NULL AND existing_checksum <> '$(escape_sql_literal "$checksum")' THEN
    RAISE EXCEPTION 'checksum changed for already executed migration %', '$(escape_sql_literal "$migration_id")';
  END IF;
END
\$\$;
SELECT CASE
  WHEN EXISTS (
    SELECT 1 FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
    WHERE migration_id = '$(escape_sql_literal "$migration_id")'
  )
  THEN 'false'
  ELSE 'true'
END AS should_run \gset
\if :should_run
\echo [sql-migrations] apply $migration_id
\i '$escaped_file'
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum)
VALUES ('$(escape_sql_literal "$migration_id")', '$(escape_sql_literal "$checksum")');
\else
\echo [sql-migrations] skip $migration_id
\endif
SQL
}

main() {
  if [ ! -d "$MIGRATION_DIR" ]; then
    log "migration directory not found, skipping: $MIGRATION_DIR"
    return 0
  fi

  wait_for_postgres
  split_migration_table

  MIGRATION_PLAN_FILE="$(mktemp /tmp/nexent-sql-migrations.XXXXXX.sql)"
  trap 'rm -f "$MIGRATION_PLAN_FILE"' EXIT
  {
    echo "SELECT pg_advisory_lock(hashtext('$(escape_sql_literal "$LOCK_KEY")'));"
    echo "CREATE SCHEMA IF NOT EXISTS \"$MIGRATION_SCHEMA\";"
    echo "CREATE TABLE IF NOT EXISTS \"$MIGRATION_SCHEMA\".\"$MIGRATION_TABLE_NAME\" (migration_id text PRIMARY KEY, checksum text NOT NULL, executed_at timestamptz NOT NULL DEFAULT now());"
  } > "$MIGRATION_PLAN_FILE"

  local found=false file
  while IFS= read -r file; do
    found=true
    run_one_migration "$file"
  done < <(find "$MIGRATION_DIR" -maxdepth 1 -type f -name 'v*.sql' -print | sort -V)

  echo "SELECT pg_advisory_unlock(hashtext('$(escape_sql_literal "$LOCK_KEY")'));" >> "$MIGRATION_PLAN_FILE"
  psql_base -f "$MIGRATION_PLAN_FILE"

  if [ "$found" = false ]; then
    log "no migration files found in $MIGRATION_DIR"
  else
    log "migration check complete"
  fi
}

main "$@"
