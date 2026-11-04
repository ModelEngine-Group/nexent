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
  [ -n "$SUPABASE_DATA_DIR" ] && [ -f "$SUPABASE_DATA_DIR/PG_VERSION" ] || fail "Set ROOT_DIR or SUPABASE_DATA_DIR to original data containing PG_VERSION; refusing empty source initialization"
  SUPABASE_DATA_DIR="$(cd "$SUPABASE_DATA_DIR" && pwd)"
  export SUPABASE_LOG_DIR="${SUPABASE_LOG_DIR:-${ROOT_DIR:+$ROOT_DIR/volumes/logs}}"
  SUPABASE_LOG_DIR="${SUPABASE_LOG_DIR:-$(dirname "$SUPABASE_DATA_DIR")/logs}"
  source_name=""; get_source
  export SUPABASE_POSTGRES_PASSWORD="$source_password"
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
  args+=(up -d db)
  [ "$with_auth" = false ] || args+=(auth kong)
  platform "${args[@]}" >/dev/null
}
