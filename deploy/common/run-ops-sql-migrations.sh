#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
set -euo pipefail

mode="${1:---migrate}"
case "$mode" in
  --off) exit 0 ;;
  --migrate|--wait) ;;
  *) printf '%s\n' 'Unsupported Ops SQL startup mode.' >&2; exit 1 ;;
esac

business_database="${POSTGRES_DB:-nexent}"
export POSTGRES_HOST="${POSTGRES_HOST:-nexent-postgresql}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-root}"
export POSTGRES_PASSWORD="${NEXENT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"
OPS_POSTGRES_DB="${OPS_POSTGRES_DB:-${business_database}_ops}"

if [[ "$OPS_POSTGRES_DB" == "$business_database" ]]; then
  printf '%s\n' 'Ops migrations require a database distinct from the Nexent database.' >&2
  exit 1
fi
if [[ "$(printf '%s' "$OPS_POSTGRES_DB" | wc -c)" -gt 63 ]]; then
  printf '%s\n' 'OPS_POSTGRES_DB must not exceed 63 UTF-8 bytes.' >&2
  exit 1
fi

ops_psql() {
  PGPASSWORD="$POSTGRES_PASSWORD" PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-3}" psql -X \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
    -v ON_ERROR_STOP=1 "$@"
}

if [[ "$mode" == --migrate ]] && ! ops_psql -d "$OPS_POSTGRES_DB" -Atqc 'SELECT 1' >/dev/null 2>&1; then
  started="$(date +%s)"
  until ops_psql -d postgres -Atqc 'SELECT 1' >/dev/null 2>&1; do
    if [[ $(( $(date +%s) - started )) -ge "${NEXENT_SQL_WAIT_TIMEOUT_SECONDS:-120}" ]]; then
      printf '%s\n' 'Ops PostgreSQL did not become ready before initialization.' >&2
      exit 1
    fi
    sleep 2
  done
  # CREATE DATABASE cannot run in a transaction; a maintenance-session lock serializes creators.
  ops_psql -d postgres -qAt -v ops_database="$OPS_POSTGRES_DB" <<'SQL' >/dev/null
SELECT pg_advisory_lock(hashtext('nexent_ops_database'), hashtext(:'ops_database'));
SELECT format('CREATE DATABASE %I', :'ops_database')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'ops_database') \gexec
SELECT pg_advisory_unlock(hashtext('nexent_ops_database'), hashtext(:'ops_database'));
SQL
fi

export POSTGRES_DB="$OPS_POSTGRES_DB"
script_dir="$(dirname "$0")"
if [[ -f "$script_dir/../sql/ops-init.sql" ]]; then
  export NEXENT_SQL_MIGRATION_DIR="$script_dir/../sql/migrations/ops"
  export NEXENT_SQL_INIT_FILE="$script_dir/../sql/ops-init.sql"
else
  export NEXENT_SQL_MIGRATION_DIR=/opt/nexent/ops-sql/migrations
  export NEXENT_SQL_INIT_FILE=/opt/nexent/ops-sql/ops-init.sql
fi
export NEXENT_SQL_MIGRATION_TABLE=ops.schema_migrations
export NEXENT_SQL_MIGRATION_LOCK_KEY=nexent_ops_sql_migrations

exec bash "$script_dir/run-sql-migrations.sh" "$mode"
