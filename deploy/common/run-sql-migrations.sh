#!/usr/bin/env bash

set -euo pipefail

MIGRATION_DIR="${NEXENT_SQL_MIGRATION_DIR:-/opt/nexent/sql/migrations}"
INIT_SQL_FILE="${NEXENT_SQL_INIT_FILE:-/opt/nexent/sql/init.sql}"
MIGRATION_TABLE="${NEXENT_SQL_MIGRATION_TABLE:-nexent.schema_migrations}"
LOCK_KEY="${NEXENT_SQL_MIGRATION_LOCK_KEY:-nexent_sql_migrations}"
MANIFEST_SEPARATOR=$'\037'

POSTGRES_HOST="${POSTGRES_HOST:-nexent-postgresql}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-root}"
POSTGRES_DB="${POSTGRES_DB:-nexent}"
POSTGRES_PASSWORD="${NEXENT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"

MODE="${NEXENT_SQL_STARTUP_MODE:-migrate}"
case "${1:-}" in
  --migrate)
    MODE="migrate"
    shift
    ;;
  --wait)
    MODE="wait"
    shift
    ;;
  --off)
    MODE="off"
    shift
    ;;
esac

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
  SQL_SEARCH_PATH="\"$MIGRATION_SCHEMA\", public"
  if [ "$MIGRATION_SCHEMA" != "nexent" ]; then
    SQL_SEARCH_PATH="\"nexent\", $SQL_SEARCH_PATH"
  fi
}

detect_app_version() {
  if [ -n "${NEXENT_APP_VERSION:-}" ]; then
    printf "%s" "$NEXENT_APP_VERSION"
  elif [ -n "${APP_VERSION:-}" ]; then
    printf "%s" "$APP_VERSION"
  elif [ -f /opt/nexent/VERSION ]; then
    sed -n '1p' /opt/nexent/VERSION
  else
    printf ""
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

append_manifest_entry() {
  local migration_id="$1"
  local checksum="$2"
  local source_file="$3"
  printf '%s%s%s%s%s\n' "$migration_id" "$MANIFEST_SEPARATOR" "$checksum" "$MANIFEST_SEPARATOR" "$source_file" >> "$MIGRATION_MANIFEST_FILE"
}

collect_one_migration() {
  local file="$1"
  local migration_id checksum
  migration_id="$(basename "$file")"
  checksum="$(sha256_file "$file")"
  append_manifest_entry "$migration_id" "$checksum" "$file"
}

collect_manifest() {
  MIGRATION_MANIFEST_FILE="$(mktemp /tmp/nexent-sql-migration-manifest.XXXXXX)"
  : > "$MIGRATION_MANIFEST_FILE"

  if [ -d "$MIGRATION_DIR" ]; then
    local file
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      collect_one_migration "$file"
    done < <(find -H "$MIGRATION_DIR" -maxdepth 1 -type f -name '*.sql' -print | sort -V)
  else
    log "migration directory not found: $MIGRATION_DIR"
  fi
}

append_migration_table_sql() {
  cat >> "$MIGRATION_PLAN_FILE" <<SQL
CREATE SCHEMA IF NOT EXISTS "$MIGRATION_SCHEMA";
CREATE TABLE IF NOT EXISTS "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (
  migration_id text PRIMARY KEY,
  checksum text NOT NULL,
  status text NOT NULL DEFAULT 'applied',
  executed_at timestamptz NOT NULL DEFAULT now(),
  app_version text,
  source_file text
);
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ADD COLUMN IF NOT EXISTS status text;
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ADD COLUMN IF NOT EXISTS executed_at timestamptz;
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ADD COLUMN IF NOT EXISTS app_version text;
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ADD COLUMN IF NOT EXISTS source_file text;
UPDATE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
SET status = 'applied'
WHERE status IS NULL;
UPDATE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
SET executed_at = now()
WHERE executed_at IS NULL;
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ALTER COLUMN status SET DEFAULT 'applied';
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ALTER COLUMN status SET NOT NULL;
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ALTER COLUMN executed_at SET DEFAULT now();
ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" ALTER COLUMN executed_at SET NOT NULL;
DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = '${MIGRATION_TABLE_NAME}_status_check'
      AND conrelid = '"$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"'::regclass
  ) THEN
    ALTER TABLE "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
      ADD CONSTRAINT "${MIGRATION_TABLE_NAME}_status_check"
      CHECK (status IN ('applied', 'baselined'));
  END IF;
END
\$\$;
SQL
}

append_init_sql() {
  local init_checksum init_file_escaped app_version_escaped
  if [ ! -f "$INIT_SQL_FILE" ]; then
    cat >> "$MIGRATION_PLAN_FILE" <<SQL
DO \$\$
BEGIN
  RAISE EXCEPTION 'init SQL file was not found: %', '$(escape_sql_literal "$INIT_SQL_FILE")';
END
\$\$;
SQL
    return 0
  fi

  init_checksum="$(sha256_file "$INIT_SQL_FILE")"
  init_file_escaped="$(escape_sql_literal "$INIT_SQL_FILE")"
  app_version_escaped="$(escape_sql_literal "$APP_VERSION_VALUE")"

  cat >> "$MIGRATION_PLAN_FILE" <<SQL
SELECT CASE
  WHEN to_regclass('nexent.conversation_message_t') IS NULL THEN 'true'
  ELSE 'false'
END AS nexent_schema_is_fresh \gset
\if :nexent_schema_is_fresh
\echo [sql-migrations] apply __init.sql
\i '$init_file_escaped'
\set init_migration_status 'applied'
\else
\echo [sql-migrations] baseline __init.sql
\set init_migration_status 'baselined'
\endif
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum, status, app_version, source_file)
VALUES ('__init.sql', '$(escape_sql_literal "$init_checksum")', :'init_migration_status', '$app_version_escaped', '$init_file_escaped')
ON CONFLICT (migration_id) DO UPDATE SET
  checksum = EXCLUDED.checksum,
  status = EXCLUDED.status,
  executed_at = now(),
  app_version = EXCLUDED.app_version,
  source_file = EXCLUDED.source_file;
SQL
}

append_one_migration_sql() {
  local migration_id="$1"
  local checksum="$2"
  local source_file="$3"
  local migration_id_escaped checksum_escaped source_file_escaped app_version_escaped

  migration_id_escaped="$(escape_sql_literal "$migration_id")"
  checksum_escaped="$(escape_sql_literal "$checksum")"
  source_file_escaped="$(escape_sql_literal "$source_file")"
  app_version_escaped="$(escape_sql_literal "$APP_VERSION_VALUE")"

  cat >> "$MIGRATION_PLAN_FILE" <<SQL
\echo [sql-migrations] check $migration_id
SELECT CASE WHEN EXISTS (
  SELECT 1 FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
  WHERE migration_id = '$migration_id_escaped' AND checksum = '$checksum_escaped'
) THEN 'true' ELSE 'false' END AS migration_checksum_matched \gset
\if :migration_checksum_matched
\echo [sql-migrations] skip $migration_id
\else
SELECT CASE WHEN EXISTS (
  SELECT 1 FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
  WHERE migration_id = '$migration_id_escaped'
) THEN 'true' ELSE 'false' END AS migration_recorded \gset
\if :migration_recorded
\echo [sql-migrations] reapply $migration_id
\else
\echo [sql-migrations] apply $migration_id
\endif
\i '$source_file_escaped'
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum, status, app_version, source_file)
VALUES ('$migration_id_escaped', '$checksum_escaped', 'applied', '$app_version_escaped', '$source_file_escaped')
ON CONFLICT (migration_id) DO UPDATE SET
  checksum = EXCLUDED.checksum,
  status = EXCLUDED.status,
  executed_at = now(),
  app_version = EXCLUDED.app_version,
  source_file = EXCLUDED.source_file;
\endif
SQL
}

append_all_migrations_sql() {
  local migration_id checksum source_file
  while IFS="$MANIFEST_SEPARATOR" read -r migration_id checksum source_file; do
    [ -n "${migration_id:-}" ] || continue
    append_one_migration_sql "$migration_id" "$checksum" "$source_file"
  done < "$MIGRATION_MANIFEST_FILE"
}

manifest_count() {
  local count
  count="$(wc -l < "$MIGRATION_MANIFEST_FILE" | tr -d '[:space:]')"
  printf "%s" "$count"
}

expected_values_sql() {
  local init_checksum migration_id checksum source_file first=true
  init_checksum="$(sha256_file "$INIT_SQL_FILE")"
  printf "('__init.sql', '%s')" "$(escape_sql_literal "$init_checksum")"
  while IFS="$MANIFEST_SEPARATOR" read -r migration_id checksum source_file; do
    [ -n "${migration_id:-}" ] || continue
    if [ "$first" = true ]; then
      first=false
    fi
    printf ", ('%s', '%s')" "$(escape_sql_literal "$migration_id")" "$(escape_sql_literal "$checksum")"
  done < "$MIGRATION_MANIFEST_FILE"
}

ensure_migration_table() {
  local plan
  plan="$(mktemp /tmp/nexent-sql-migration-table.XXXXXX.sql)"
  MIGRATION_PLAN_FILE="$plan"
  append_migration_table_sql
  psql_base -q -f "$plan"
  rm -f "$plan"
}

run_wait_mode() {
  local timeout="${NEXENT_SQL_MIGRATION_WAIT_TIMEOUT_SECONDS:-${NEXENT_SQL_WAIT_TIMEOUT_SECONDS:-300}}"
  local interval="${NEXENT_SQL_MIGRATION_WAIT_INTERVAL_SECONDS:-2}"
  local start status query values

  if [ ! -f "$INIT_SQL_FILE" ]; then
    log "ERROR: init SQL file was not found: $INIT_SQL_FILE"
    return 1
  fi

  values="$(expected_values_sql)"
  query="WITH expected(migration_id, checksum) AS (VALUES $values), joined AS (SELECT e.migration_id, e.checksum AS expected_checksum, m.checksum AS actual_checksum, m.status FROM expected e LEFT JOIN \"$MIGRATION_SCHEMA\".\"$MIGRATION_TABLE_NAME\" m ON m.migration_id = e.migration_id) SELECT CASE WHEN (SELECT count(*) FROM joined WHERE actual_checksum = expected_checksum AND status IN ('applied', 'baselined')) = (SELECT count(*) FROM expected) THEN 'ready' ELSE 'waiting' END;"

  ensure_migration_table

  start="$(date +%s)"
  while true; do
    status="$(psql_base -Atqc "$query" | tr -d '[:space:]')"
    case "$status" in
      ready)
        log "migration target is ready"
        return 0
        ;;
      waiting|"")
        ;;
      *)
        log "ERROR: unexpected wait status from PostgreSQL: $status"
        return 1
        ;;
    esac

    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      log "ERROR: migrations did not reach target state within ${timeout}s"
      return 1
    fi
    sleep "$interval"
  done
}

run_migrate_mode() {
  MIGRATION_PLAN_FILE="$(mktemp /tmp/nexent-sql-migrations.XXXXXX.sql)"
  {
    echo "SELECT pg_advisory_lock(hashtext('$(escape_sql_literal "$LOCK_KEY")'));"
  } > "$MIGRATION_PLAN_FILE"
  append_migration_table_sql
  cat >> "$MIGRATION_PLAN_FILE" <<SQL
SET search_path TO $SQL_SEARCH_PATH;
SQL
  append_init_sql
  append_all_migrations_sql
  echo "SELECT pg_advisory_unlock(hashtext('$(escape_sql_literal "$LOCK_KEY")'));" >> "$MIGRATION_PLAN_FILE"

  psql_base -f "$MIGRATION_PLAN_FILE"

  if [ "$(manifest_count)" = "0" ]; then
    log "no migration files found in $MIGRATION_DIR"
  fi
  log "migration check complete"
}

cleanup() {
  if [ -n "${MIGRATION_PLAN_FILE:-}" ]; then
    rm -f "$MIGRATION_PLAN_FILE"
  fi
  if [ -n "${MIGRATION_MANIFEST_FILE:-}" ]; then
    rm -f "$MIGRATION_MANIFEST_FILE"
  fi
}

main() {
  case "$MODE" in
    off)
      log "SQL migration startup mode is off"
      return 0
      ;;
    migrate|wait)
      ;;
    *)
      log "ERROR: unsupported NEXENT_SQL_STARTUP_MODE: $MODE"
      return 1
      ;;
  esac

  wait_for_postgres
  split_migration_table
  APP_VERSION_VALUE="$(detect_app_version)"
  collect_manifest
  trap cleanup EXIT

  case "$MODE" in
    migrate)
      run_migrate_mode
      ;;
    wait)
      run_wait_mode
      ;;
  esac
}

main "$@"
