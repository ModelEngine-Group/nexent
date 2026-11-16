#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Explicit recovery uses only the original data and exact legacy container names.
run_recovery() {
  [ "$mode" = docker ] || fail "Manual legacy recovery is Docker-only"
  export SUPABASE_MIGRATION_PROJECT="${SUPABASE_MIGRATION_PROJECT:-nexent-supabase-migration}"
  export SUPABASE_MIGRATION_NETWORK="${SUPABASE_MIGRATION_NETWORK:-nexent_supabase_migration}"
  export SUPABASE_MIGRATION_DB_CONTAINER="${SUPABASE_MIGRATION_DB_CONTAINER:-supabase-db-mini}"
  export SUPABASE_MIGRATION_AUTH_CONTAINER="${SUPABASE_MIGRATION_AUTH_CONTAINER:-supabase-auth-mini}"
  export SUPABASE_MIGRATION_KONG_CONTAINER="${SUPABASE_MIGRATION_KONG_CONTAINER:-supabase-kong-mini}"
  export SUPABASE_DB_CONFIG_VOLUME="${SUPABASE_DB_CONFIG_VOLUME:-${SUPABASE_MIGRATION_PROJECT}_db-config}"
  local names=("$SUPABASE_MIGRATION_DB_CONTAINER" "$SUPABASE_MIGRATION_AUTH_CONTAINER" "$SUPABASE_MIGRATION_KONG_CONTAINER")
  local name running count=0
  for name in "${names[@]}"; do
    [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ && "${name,,}" == *supabase* ]] || fail "Use distinct Supabase container names for recovery"
  done
  [ "${names[0]}" != "${names[1]}" ] && [ "${names[0]}" != "${names[2]}" ] && [ "${names[1]}" != "${names[2]}" ] || fail "Legacy names must be distinct"
  if [ "$legacy_action" = down ]; then
    for name in "${names[@]}"; do
      if platform inspect "$name" >/dev/null 2>&1; then platform stop "$name" >/dev/null; platform rm "$name" >/dev/null; fi
    done
    if [ "$SUPABASE_MIGRATION_NETWORK" != nexent_network ] &&
      [ "$(platform network inspect --format '{{index .Labels "com.docker.compose.project"}}' "$SUPABASE_MIGRATION_NETWORK" 2>/dev/null || true)" = "$SUPABASE_MIGRATION_PROJECT" ]; then
      platform network rm "$SUPABASE_MIGRATION_NETWORK" >/dev/null
    fi
    return
  fi
  export SUPABASE_DATA_DIR="${SUPABASE_DATA_DIR:-${ROOT_DIR:+$ROOT_DIR/volumes/db/data}}"
  [ -n "$SUPABASE_DATA_DIR" ] && [ -s "$SUPABASE_DATA_DIR/PG_VERSION" ] &&
    [ -s "$SUPABASE_DATA_DIR/global/pg_control" ] || fail "Set ROOT_DIR or SUPABASE_DATA_DIR to the original PostgreSQL data directory (PG_VERSION and global/pg_control required); refusing empty source initialization"
  SUPABASE_DATA_DIR="$(cd "$SUPABASE_DATA_DIR" && pwd)"
  export SUPABASE_LOG_DIR="${SUPABASE_LOG_DIR:-${ROOT_DIR:+$ROOT_DIR/volumes/logs}}"
  SUPABASE_LOG_DIR="${SUPABASE_LOG_DIR:-$(dirname "$SUPABASE_DATA_DIR")/logs}"
  source_name=""; get_source
  export SUPABASE_POSTGRES_PASSWORD="$source_password" SUPABASE_POSTGRES_DB="$source_db" SUPABASE_POSTGRES_PORT="$source_port"
  export SUPABASE_DB="${SUPABASE_DB:-supabase/postgres:15.8.1.060}"
  export SUPABASE_PUBLISHED_PORT="${SUPABASE_PUBLISHED_PORT:-5436}"
  export SUPABASE_MIGRATION_BIND_ADDRESS="${SUPABASE_MIGRATION_BIND_ADDRESS:-127.0.0.1}"
  export SUPABASE_KONG="${SUPABASE_KONG:-kong:2.8.1}" SUPABASE_GOTRUE="${SUPABASE_GOTRUE:-supabase/gotrue:v2.170.0}"
  export SUPABASE_KONG_HTTP_PORT="${SUPABASE_KONG_HTTP_PORT:-8000}" SUPABASE_KONG_HTTPS_PORT="${SUPABASE_KONG_HTTPS_PORT:-8443}"
  local site_url=http://localhost:3000
  [ "$production" = false ] || site_url=http://nexent:3000
  export API_EXTERNAL_URL="${API_EXTERNAL_URL:-http://localhost:8000}" SITE_URL="${SITE_URL:-$site_url}"
  export JWT_SECRET="${JWT_SECRET:-}" SUPABASE_KEY="${SUPABASE_KEY:-}" SERVICE_ROLE_KEY="${SERVICE_ROLE_KEY:-}"
  export DASHBOARD_USERNAME="${DASHBOARD_USERNAME:-supabase}" DASHBOARD_PASSWORD="${DASHBOARD_PASSWORD:-}"
  export JWT_EXPIRY="${JWT_EXPIRY:-7200}" ADDITIONAL_REDIRECT_URLS="${ADDITIONAL_REDIRECT_URLS:-}"
  export DISABLE_SIGNUP="${DISABLE_SIGNUP:-true}" ENABLE_EMAIL_SIGNUP="${ENABLE_EMAIL_SIGNUP:-true}"
  export ENABLE_ANONYMOUS_USERS="${ENABLE_ANONYMOUS_USERS:-false}" ENABLE_EMAIL_AUTOCONFIRM="${ENABLE_EMAIL_AUTOCONFIRM:-true}"
  export ENABLE_PHONE_SIGNUP="${ENABLE_PHONE_SIGNUP:-false}" ENABLE_PHONE_AUTOCONFIRM="${ENABLE_PHONE_AUTOCONFIRM:-false}"
  export MAILER_URLPATHS_INVITE="${MAILER_URLPATHS_INVITE:-/auth/v1/verify}"
  export MAILER_URLPATHS_CONFIRMATION="${MAILER_URLPATHS_CONFIRMATION:-/auth/v1/verify}"
  export MAILER_URLPATHS_RECOVERY="${MAILER_URLPATHS_RECOVERY:-/auth/v1/verify}"
  export MAILER_URLPATHS_EMAIL_CHANGE="${MAILER_URLPATHS_EMAIL_CHANGE:-/auth/v1/verify}"
  if [ "$with_auth" = true ]; then
    for name in JWT_SECRET SUPABASE_KEY SERVICE_ROLE_KEY DASHBOARD_PASSWORD; do [ -n "${!name:-}" ] || fail "Full legacy auth requires original signing keys and tokens"; done
  else
    names=("${names[0]}")
  fi
  for name in "${names[@]}"; do if platform inspect "$name" >/dev/null 2>&1; then count=$((count + 1)); fi; done
  if [ "$count" -gt 0 ]; then
    [ "$count" -eq "${#names[@]}" ] || fail "Partial legacy stack exists; use down then up against original data"
    for name in "${names[@]}"; do
      running="$(platform inspect --format '{{.State.Running}}' "$name")"
      [ "$running" = true ] || platform start "$name" >/dev/null
    done
    return
  fi
  # Compose resolves host bind paths. Native Windows Docker needs native host paths.
  local directory="$SCRIPT_DIR"
  if command -v cygpath >/dev/null 2>&1; then
    directory="$(cygpath -m "$directory")"
    SUPABASE_DATA_DIR="$(cygpath -m "$SUPABASE_DATA_DIR")"
    SUPABASE_LOG_DIR="$(cygpath -m "$SUPABASE_LOG_DIR")"
  fi
  local args=(compose --project-name "$SUPABASE_MIGRATION_PROJECT" --project-directory "$directory" -f "$directory/docker-compose-supabase.yml")
  [ "$production" = false ] || args+=(-f "$directory/docker-compose-supabase.prod.yml")
  [ "$with_auth" = false ] || args+=(--profile legacy-auth)
  args+=(up -d --no-recreate db)
  [ "$with_auth" = false ] || args+=(auth kong)
  platform "${args[@]}" >/dev/null || fail "Cannot start Supabase from the original data directory"
}
