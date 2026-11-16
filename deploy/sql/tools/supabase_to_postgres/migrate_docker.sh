#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Docker resources are controlled only by the host Shell.
container_name="" migration_token="account-migration-$(date +%s)-$$-$RANDOM"
finish_docker() {
  local owner
  if [ -n "$container_name" ]; then
    owner="$(platform inspect --format '{{index .Config.Labels "nexent.account-migration"}}' "$container_name" 2>/dev/null || true)"
    if [ "$owner" = "$migration_token" ]; then platform rm -f "$container_name" >/dev/null 2>&1 || printf 'Migration worker cleanup incomplete: %s\n' "$container_name" >&2; fi
  fi
}
trap finish_docker EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
network_of() { platform inspect --format '{{range $name,$network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$1" | head -n 1; }
address_of() { platform inspect --format "{{with index .NetworkSettings.Networks \"$2\"}}{{.IPAddress}}{{end}}" "$1"; }
run_migration() {
  local host="${SUPABASE_POSTGRES_HOST:-}" source_network target_network names name output code
  local auth_name="${SUPABASE_MIGRATION_AUTH_CONTAINER:-supabase-auth-mini}"
  local kong_name="${SUPABASE_MIGRATION_KONG_CONTAINER:-supabase-kong-mini}"
  local candidates=()
  source_name="${source_name:-${SUPABASE_MIGRATION_DB_CONTAINER:-}}"
  case "$host" in ''|supabase_db|supabase-db-mini|nexent-supabase-db) host="" ;; esac
  if [ -z "$host" ] || [ -n "$source_name" ]; then
    names="$(platform ps -a --format '{{.Names}}')" || fail "Cannot inspect Docker source containers"
    while IFS= read -r name; do
      [[ "$name" != "$auth_name" && "$name" != "$kong_name" ]] || continue
      case "${name,,}" in *supabase*db*) candidates+=("$name") ;; esac
    done <<< "$names"
    if [ -z "$source_name" ]; then
      [ "${#candidates[@]}" -le 1 ] || fail "Multiple Supabase databases exist; configure the original source container"
      source_name="${candidates[0]:-supabase-db-mini}"
    fi
    local peers=("$source_name" "$auth_name" "$kong_name")
    for name in "${peers[@]}"; do
      [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ && "${name,,}" == *supabase* ]] || fail "Use Supabase names for source cleanup"
      [ "$name" != "$database" ] || fail "Source cleanup must not select the target database"
    done
    [ "${peers[0]}" != "${peers[1]}" ] && [ "${peers[0]}" != "${peers[2]}" ] && [ "${peers[1]}" != "${peers[2]}" ] || fail "Source cleanup names must be distinct"
    if ! grep -Fxq -- "$source_name" <<< "$names"; then
      [ "${#candidates[@]}" -eq 0 ] || fail "Configured source container is missing; verify which existing Supabase database is original"
      [ "$allow_start" = true ] || fail "Original Supabase source is missing and source startup is disabled"
      log_stage source "Source container $source_name is missing; checking original PostgreSQL data before recovery."
      (
        export SUPABASE_MIGRATION_DB_CONTAINER="$source_name"
        source "$SCRIPT_DIR/legacy.sh"
        legacy_action=up with_auth=false production=false run_recovery
      )
    fi
    platform inspect "$source_name" >/dev/null 2>&1 || fail "Cannot inspect the original Supabase source container"
    if [ "$(platform inspect --format '{{.State.Running}}' "$source_name")" != true ]; then
      [ "$allow_start" = true ] || fail "Original Supabase source is stopped"
      platform start "$source_name" >/dev/null || fail "Cannot start original Supabase"
    fi
    source_network="$(network_of "$source_name")"
    source_host="$(address_of "$source_name" "$source_network")"
  else
    source_host="$host"
  fi
  log_stage source "Original source selected: ${source_name:-remote}; resolving credentials without logging them."
  get_source
  target_network="$(network_of "$database")"
  target_host="$(address_of "$database" "$target_network")"
  [ -n "$target_host" ] || fail "Target PostgreSQL needs a reachable Docker bridge network"
  if [ -n "$source_name" ]; then [ -n "$source_host" ] || fail "Source PostgreSQL needs a reachable Docker bridge network"; fi
  case "$source_host" in localhost|127.0.0.1)
    source_host="$(platform network inspect --format '{{(index .IPAM.Config 0).Gateway}}' "$target_network")" ;;
  esac
  export_connections
  if ! platform image inspect "$NEXENT_IMAGE" >/dev/null 2>&1; then
    [ "${DEPLOYMENT_IMAGE_SOURCE:-}" != local-latest ] || fail "Migration backend image is unavailable locally"
    platform pull "$NEXENT_IMAGE" >/dev/null || fail "Cannot pull migration backend image"
  fi
  container_name="$migration_token"
  platform create --name "$container_name" --label "nexent.account-migration=$migration_token" \
    --network "$target_network" --entrypoint python \
    -e POSTGRES_HOST -e POSTGRES_PORT -e POSTGRES_USER -e POSTGRES_DB -e NEXENT_POSTGRES_PASSWORD \
    -e SUPABASE_POSTGRES_HOST -e SUPABASE_POSTGRES_PORT -e SUPABASE_POSTGRES_USER -e SUPABASE_POSTGRES_DB -e SUPABASE_POSTGRES_PASSWORD \
    "$NEXENT_IMAGE" "${worker_command[@]:1}" >/dev/null || fail "Cannot create migration worker"
  if [ -n "${source_network:-}" ] && [ "$source_network" != "$target_network" ]; then
    platform network connect "$source_network" "$container_name" || fail "Cannot connect migration worker to the source network"
  fi
  # Running an image entrypoint directly cannot execute application startup SQL.
  log_stage worker "Starting isolated database worker (apply=$apply); source snapshot, import and coverage validation run before commit."
  output="$(platform start -a "$container_name")" || fail "Container account migration failed; original source was retained"
  code="$(platform inspect --format '{{.State.ExitCode}}' "$container_name")"
  [ "$code" = 0 ] || fail "Container account migration failed; original source was retained"
  printf '%s\n' "$output"
  log_stage result "Worker result: $output"
  if worker_flag skipped "$output"; then log_stage skipped "Concurrent inspection found complete data; source cleanup was not attempted."; return; fi
  if [ "$apply" = true ]; then
    worker_flag committed "$output" || fail "Worker did not confirm a committed migration; original source was retained"
    log_stage committed "Account schema, business profiles and credential coverage committed."
  fi
  if [ "$apply" = true ] && [ -n "$source_name" ]; then
    log_stage cleanup "Committed migration; stopping and removing selected source DB/Auth/Kong containers, retaining data volumes."
    for name in "$kong_name" "$auth_name" "$source_name"; do
      if platform inspect "$name" >/dev/null 2>&1; then
        log_stage cleanup "Removing source container $name."
        platform stop "$name" >/dev/null && platform rm "$name" >/dev/null || cleanup_warning
      else
        log_stage cleanup "Configured source container $name is absent; nothing removed."
      fi
    done
  elif [ "$apply" = true ]; then
    log_stage cleanup "Remote source has no managed local containers; manual source cleanup is required."
  else
    log_stage preview "Preview rolled back; source workloads were retained."
  fi
}
