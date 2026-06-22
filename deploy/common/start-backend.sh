#!/usr/bin/env bash

set -euo pipefail

if [ "${NEXENT_RUN_SQL_MIGRATIONS:-true}" = "true" ]; then
  /opt/nexent/scripts/run-sql-migrations.sh
fi

exec "$@"
