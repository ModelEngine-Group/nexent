#!/usr/bin/env bash

set -euo pipefail

MIGRATION_DIR="${NEXENT_SQL_MIGRATION_DIR:-/opt/nexent/sql/migrations}"
INIT_SQL_FILE="${NEXENT_SQL_INIT_FILE:-/opt/nexent/sql/init.sql}"
MIGRATION_TABLE="${NEXENT_SQL_MIGRATION_TABLE:-nexent.schema_migrations}"
LOCK_KEY="${NEXENT_SQL_MIGRATION_LOCK_KEY:-nexent_sql_migrations}"

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

strip_trailing_semicolon() {
  printf "%s" "$1" | sed -E 's/[[:space:]]*;[[:space:]]*$//'
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

ensure_bundle_segment_dir() {
  if [ -z "${BUNDLE_SEGMENT_DIR:-}" ]; then
    BUNDLE_SEGMENT_DIR="$(mktemp -d /tmp/nexent-sql-migration-segments.XXXXXX)"
  fi
}

split_bundle_migration() {
  local file="$1"
  ensure_bundle_segment_dir
  awk -v outdir="$BUNDLE_SEGMENT_DIR" '
    function close_current() {
      if (out != "") {
        close(out)
      }
      out = ""
    }
    /^-- nexent-migration-source: / {
      close_current()
      id = $0
      sub(/^-- nexent-migration-source: /, "", id)
      sub(/\r$/, "", id)
      out = outdir "/" id
      next
    }
    /^-- nexent-migration-checksum: / { next }
    /^-- nexent-migration-probe: / { next }
    {
      if (out != "") {
        print $0 > out
      }
    }
    END {
      close_current()
    }
  ' "$file"
}

bundle_source_ids() {
  awk '
    /^-- nexent-migration-source: / {
      id = $0
      sub(/^-- nexent-migration-source: /, "", id)
      sub(/\r$/, "", id)
      print id
    }
  ' "$1"
}

bundle_source_marker() {
  local file="$1"
  local source_id="$2"
  local marker="$3"
  awk -v want="$source_id" -v marker="$marker" '
    /^-- nexent-migration-source: / {
      id = $0
      sub(/^-- nexent-migration-source: /, "", id)
      sub(/\r$/, "", id)
      active = (id == want)
      next
    }
    active && index($0, marker) == 1 {
      value = $0
      sub(marker, "", value)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' "$file"
}

file_marker() {
  local file="$1"
  local marker="$2"
  awk -v marker="$marker" '
    index($0, marker) == 1 {
      value = $0
      sub(marker, "", value)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' "$file"
}

append_manifest_entry() {
  local migration_id="$1"
  local checksum="$2"
  local probe="$3"
  local source_file="$4"
  printf '%s\t%s\t%s\t%s\n' "$migration_id" "$checksum" "$probe" "$source_file" >> "$MIGRATION_MANIFEST_FILE"
}

collect_one_migration() {
  local file="$1"
  local source_id source_file source_checksum source_probe migration_id checksum probe

  if grep -q '^-- nexent-migration-source: ' "$file"; then
    split_bundle_migration "$file"
    while IFS= read -r source_id; do
      [ -n "$source_id" ] || continue
      source_file="$BUNDLE_SEGMENT_DIR/$source_id"
      source_checksum="$(bundle_source_marker "$file" "$source_id" "-- nexent-migration-checksum: ")"
      source_probe="$(bundle_source_marker "$file" "$source_id" "-- nexent-migration-probe: ")"
      if [ -z "$source_checksum" ]; then
        source_checksum="$(sha256_file "$source_file")"
      fi
      append_manifest_entry "$source_id" "$source_checksum" "$source_probe" "$source_file"
    done < <(bundle_source_ids "$file")
    return 0
  fi

  migration_id="$(basename "$file")"
  checksum="$(file_marker "$file" "-- nexent-migration-checksum: ")"
  probe="$(file_marker "$file" "-- nexent-migration-probe: ")"
  if [ -z "$checksum" ]; then
    checksum="$(sha256_file "$file")"
  fi
  append_manifest_entry "$migration_id" "$checksum" "$probe" "$file"
}

collect_manifest() {
  MIGRATION_MANIFEST_FILE="$(mktemp /tmp/nexent-sql-migration-manifest.XXXXXX)"
  : > "$MIGRATION_MANIFEST_FILE"

  if [ -d "$MIGRATION_DIR" ]; then
    local file
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      collect_one_migration "$file"
    done < <(find "$MIGRATION_DIR" -maxdepth 1 -type f -name 'v*.sql' -print | sort -V)
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
\echo [sql-migrations] apply __init.sql
\i '$init_file_escaped'
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum, status, app_version, source_file)
VALUES ('__init.sql', '$(escape_sql_literal "$init_checksum")', 'applied', '$app_version_escaped', '$init_file_escaped')
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
  local probe="$3"
  local source_file="$4"
  local migration_id_escaped checksum_escaped source_file_escaped app_version_escaped probe_sql

  migration_id_escaped="$(escape_sql_literal "$migration_id")"
  checksum_escaped="$(escape_sql_literal "$checksum")"
  source_file_escaped="$(escape_sql_literal "$source_file")"
  app_version_escaped="$(escape_sql_literal "$APP_VERSION_VALUE")"

  cat >> "$MIGRATION_PLAN_FILE" <<SQL
\echo [sql-migrations] check $migration_id
DO \$\$
DECLARE existing_checksum text;
BEGIN
  SELECT checksum INTO existing_checksum
  FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
  WHERE migration_id = '$migration_id_escaped';

  IF existing_checksum IS NOT NULL AND existing_checksum <> '$checksum_escaped' THEN
    RAISE EXCEPTION 'checksum changed for already executed migration %', '$migration_id_escaped';
  END IF;
END
\$\$;
SELECT CASE WHEN EXISTS (
  SELECT 1 FROM "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME"
  WHERE migration_id = '$migration_id_escaped'
) THEN 'true' ELSE 'false' END AS migration_recorded \gset
\if :migration_recorded
\echo [sql-migrations] skip $migration_id
\else
SQL

  if [ -z "$probe" ]; then
    cat >> "$MIGRATION_PLAN_FILE" <<SQL
DO \$\$
BEGIN
  RAISE EXCEPTION 'migration % is missing nexent-migration-probe; cannot safely baseline missing history', '$migration_id_escaped';
END
\$\$;
SQL
  else
    probe_sql="$(strip_trailing_semicolon "$probe")"
    cat >> "$MIGRATION_PLAN_FILE" <<SQL
\echo [sql-migrations] probe $migration_id
TRUNCATE TABLE _nexent_migration_probe_result;
INSERT INTO _nexent_migration_probe_result(probe_result)
$probe_sql;
SELECT CASE WHEN COALESCE((SELECT probe_result FROM _nexent_migration_probe_result LIMIT 1), false)
  THEN 'true' ELSE 'false' END AS probe_matched \gset
\if :probe_matched
\echo [sql-migrations] baseline $migration_id
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum, status, app_version, source_file)
VALUES ('$migration_id_escaped', '$checksum_escaped', 'baselined', '$app_version_escaped', '$source_file_escaped');
\else
\echo [sql-migrations] apply $migration_id
\i '$source_file_escaped'
INSERT INTO "$MIGRATION_SCHEMA"."$MIGRATION_TABLE_NAME" (migration_id, checksum, status, app_version, source_file)
VALUES ('$migration_id_escaped', '$checksum_escaped', 'applied', '$app_version_escaped', '$source_file_escaped');
\endif
SQL
  fi

  cat >> "$MIGRATION_PLAN_FILE" <<SQL
\endif
SQL
}

append_all_migrations_sql() {
  local migration_id checksum probe source_file
  while IFS=$'\t' read -r migration_id checksum probe source_file; do
    [ -n "${migration_id:-}" ] || continue
    append_one_migration_sql "$migration_id" "$checksum" "$probe" "$source_file"
  done < "$MIGRATION_MANIFEST_FILE"
}

manifest_count() {
  local count
  count="$(wc -l < "$MIGRATION_MANIFEST_FILE" | tr -d '[:space:]')"
  printf "%s" "$count"
}

expected_values_sql() {
  local init_checksum migration_id checksum probe source_file first=true
  init_checksum="$(sha256_file "$INIT_SQL_FILE")"
  printf "('__init.sql', '%s')" "$(escape_sql_literal "$init_checksum")"
  while IFS=$'\t' read -r migration_id checksum probe source_file; do
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
  query="WITH expected(migration_id, checksum) AS (VALUES $values), joined AS (SELECT e.migration_id, e.checksum AS expected_checksum, m.checksum AS actual_checksum, m.status FROM expected e LEFT JOIN \"$MIGRATION_SCHEMA\".\"$MIGRATION_TABLE_NAME\" m ON m.migration_id = e.migration_id) SELECT CASE WHEN EXISTS (SELECT 1 FROM joined WHERE migration_id <> '__init.sql' AND actual_checksum IS NOT NULL AND actual_checksum <> expected_checksum) THEN 'checksum_mismatch' WHEN (SELECT count(*) FROM joined WHERE actual_checksum = expected_checksum AND status IN ('applied', 'baselined')) = (SELECT count(*) FROM expected) THEN 'ready' ELSE 'waiting' END;"

  ensure_migration_table

  start="$(date +%s)"
  while true; do
    status="$(psql_base -Atqc "$query" | tr -d '[:space:]')"
    case "$status" in
      ready)
        log "migration target is ready"
        return 0
        ;;
      checksum_mismatch)
        log "ERROR: migration records contain a checksum mismatch"
        return 1
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
CREATE TEMP TABLE _nexent_migration_probe_result(probe_result boolean);
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
  if [ -n "${BUNDLE_SEGMENT_DIR:-}" ]; then
    rm -rf "$BUNDLE_SEGMENT_DIR"
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
