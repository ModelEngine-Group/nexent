#!/usr/bin/env bash

set -euo pipefail

SQL_STARTUP_MODE="${NEXENT_SQL_STARTUP_MODE:-off}"

if [ -z "${NEXENT_SQL_STARTUP_MODE+x}" ] && [ -n "${NEXENT_RUN_SQL_MIGRATIONS:-}" ]; then
  if [ "$NEXENT_RUN_SQL_MIGRATIONS" = "true" ]; then
    SQL_STARTUP_MODE="migrate"
  else
    SQL_STARTUP_MODE="off"
  fi
fi

case "$SQL_STARTUP_MODE" in
  migrate)
    /opt/nexent/scripts/run-sql-migrations.sh --migrate
    ;;
  wait)
    /opt/nexent/scripts/run-sql-migrations.sh --wait
    ;;
  off|"")
    ;;
  *)
    printf '[start-backend] ERROR: unsupported NEXENT_SQL_STARTUP_MODE: %s\n' "$SQL_STARTUP_MODE" >&2
    exit 1
    ;;
esac

exec "$@"
