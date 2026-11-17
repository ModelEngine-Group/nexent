#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
set -euo pipefail

: "${OPS_POSTGRES_HOST:?Set the Ops PostgreSQL host}"
: "${OPS_POSTGRES_USER:?Set the Ops migration role}"
: "${OPS_POSTGRES_DB:?Set the independent Ops database name}"

if [[ "$OPS_POSTGRES_DB" == "${POSTGRES_DB:-nexent}" ]]; then
  printf '%s\n' 'Ops migrations require a database distinct from the Nexent database.' >&2
  exit 1
fi

export POSTGRES_HOST="$OPS_POSTGRES_HOST"
export POSTGRES_PORT="${OPS_POSTGRES_PORT:-5432}"
export POSTGRES_USER="$OPS_POSTGRES_USER"
export POSTGRES_DB="$OPS_POSTGRES_DB"
export NEXENT_POSTGRES_PASSWORD="${OPS_POSTGRES_PASSWORD:-}"
export POSTGRES_PASSWORD="${OPS_POSTGRES_PASSWORD:-}"
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

exec bash "$script_dir/run-sql-migrations.sh" "${1:---migrate}"
